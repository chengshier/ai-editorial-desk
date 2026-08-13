from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import TypeVar
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.budget import AIBudgetGate, AIBudgetReservation
from packages.ai_gateway.costs import (
    approximate_input_tokens,
    estimate_cost,
    pricing_snapshot,
    reserve_estimate,
)
from packages.ai_gateway.domain import (
    AIMessage,
    AIModelTarget,
    AIRouteSnapshot,
    AIUsage,
    EmbeddingProviderRequest,
    EmbeddingProviderResponse,
    GatewayEmbeddingResult,
    GatewayStructuredResult,
    GatewayTextResult,
    InvocationContext,
    StructuredProviderRequest,
    StructuredProviderResponse,
    TextProviderRequest,
    TextProviderResponse,
)
from packages.ai_gateway.errors import (
    AIErrorCode,
    AIGatewayError,
    AIProviderError,
    provider_error_metadata,
)
from packages.ai_gateway.generation_policy import resolve_max_output_tokens
from packages.ai_gateway.invocations import AIInvocationStore
from packages.ai_gateway.openai_compatible import DefaultProviderAdapterFactory
from packages.ai_gateway.providers import AIProviderAdapter, ProviderAdapterFactory
from packages.ai_gateway.routing import AIRouteRepository
from packages.database.session import get_async_sessionmaker

logger = logging.getLogger(__name__)
ProviderResponseT = TypeVar(
    "ProviderResponseT",
    EmbeddingProviderResponse,
    TextProviderResponse,
    StructuredProviderResponse,
)
ProviderCall = Callable[
    [AIProviderAdapter, AIModelTarget, float],
    Awaitable[ProviderResponseT],
]

_RETRYABLE_FALLBACK_ERRORS = frozenset(
    {
        AIErrorCode.RATE_LIMITED,
        AIErrorCode.TIMEOUT,
        AIErrorCode.NETWORK_ERROR,
        AIErrorCode.PROVIDER_UNAVAILABLE,
        AIErrorCode.INVALID_RESPONSE,
        AIErrorCode.STRUCTURED_OUTPUT_INVALID,
    }
)
_POSSIBLY_BILLED_ERRORS = frozenset(
    {AIErrorCode.TIMEOUT, AIErrorCode.NETWORK_ERROR, AIErrorCode.INVALID_RESPONSE}
)


class AIGateway:
    """Task-routed AI calls with immutable audit, bounded retries, fallback and budget gates."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        provider_factory: ProviderAdapterFactory | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.provider_factory = provider_factory or DefaultProviderAdapterFactory()
        self.budgets = AIBudgetGate(self.session_factory)
        self.invocations = AIInvocationStore(self.session_factory)

    async def embed(
        self,
        *,
        task_key: str,
        texts: tuple[str, ...],
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
        primary_only: bool = False,
    ) -> GatewayEmbeddingResult:
        if not texts or any(not text.strip() for text in texts):
            raise AIGatewayError(AIErrorCode.INVALID_REQUEST, "Embedding 输入不能为空")
        route = await self.route_snapshot(
            task_key=task_key,
            capability="embedding",
            primary_only=primary_only,
        )
        request = EmbeddingProviderRequest(texts=texts)
        input_hash = _input_hash({"texts": list(texts)})
        estimated_input_tokens = sum(approximate_input_tokens(text) for text in texts)

        async def call(
            provider: AIProviderAdapter,
            target: AIModelTarget,
            timeout_seconds: float,
        ) -> EmbeddingProviderResponse:
            return await provider.embed(
                target=target,
                request=request,
                timeout_seconds=timeout_seconds,
            )

        target, response, cost, inv_id = await self._execute(
            route=route,
            capability="embedding",
            input_hash=input_hash,
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=0,
            context=context or InvocationContext(),
            invocation_id=invocation_id,
            provider_call=call,
        )
        return GatewayEmbeddingResult(
            invocation_id=inv_id,
            provider_key=target.provider_key,
            model_name=target.model_name,
            vectors=response.vectors,
            usage=response.usage,
            estimated_cost=cost,
        )

    async def generate_text(
        self,
        *,
        task_key: str,
        messages: tuple[AIMessage, ...],
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayTextResult:
        _validate_messages(messages)
        route = await self.route_snapshot(task_key=task_key, capability="text_generation")
        effective_max_output_tokens = resolve_max_output_tokens(
            route_config=route.config,
            fallback=max_output_tokens,
        )
        request = TextProviderRequest(
            messages=messages,
            max_output_tokens=effective_max_output_tokens,
            temperature=temperature,
        )
        normalized = {
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "max_output_tokens": effective_max_output_tokens,
            "temperature": temperature,
        }
        estimated_input_tokens = sum(
            approximate_input_tokens(f"{item.role}:{item.content}") for item in messages
        )
        reserved_output = effective_max_output_tokens or int(
            route.budget_policy.get("reserve_output_tokens", 512)
        )

        async def call(
            provider: AIProviderAdapter,
            target: AIModelTarget,
            timeout_seconds: float,
        ) -> TextProviderResponse:
            return await provider.generate_text(
                target=target,
                request=request,
                timeout_seconds=timeout_seconds,
            )

        target, response, cost, inv_id = await self._execute(
            route=route,
            capability="text_generation",
            input_hash=_input_hash(normalized),
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=reserved_output,
            context=context or InvocationContext(),
            invocation_id=invocation_id,
            provider_call=call,
        )
        return GatewayTextResult(
            invocation_id=inv_id,
            provider_key=target.provider_key,
            model_name=target.model_name,
            text=response.text,
            usage=response.usage,
            estimated_cost=cost,
        )

    async def generate_structured(
        self,
        *,
        task_key: str,
        messages: tuple[AIMessage, ...],
        schema: dict[str, object],
        schema_name: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayStructuredResult:
        _validate_messages(messages)
        if not schema_name.strip():
            raise AIGatewayError(AIErrorCode.INVALID_REQUEST, "schema_name 不能为空")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise AIGatewayError(AIErrorCode.INVALID_REQUEST, "JSON Schema 无效") from exc
        route = await self.route_snapshot(task_key=task_key, capability="structured_output")
        effective_max_output_tokens = resolve_max_output_tokens(
            route_config=route.config,
            fallback=max_output_tokens,
        )
        request = StructuredProviderRequest(
            messages=messages,
            schema=schema,
            schema_name=schema_name,
            max_output_tokens=effective_max_output_tokens,
            temperature=temperature,
        )
        normalized = {
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "schema": schema,
            "schema_name": schema_name,
            "max_output_tokens": effective_max_output_tokens,
            "temperature": temperature,
        }
        estimated_input_tokens = sum(
            approximate_input_tokens(f"{item.role}:{item.content}") for item in messages
        ) + approximate_input_tokens(json.dumps(schema, sort_keys=True, ensure_ascii=False))
        reserved_output = effective_max_output_tokens or int(
            route.budget_policy.get("reserve_output_tokens", 512)
        )

        async def call(
            provider: AIProviderAdapter,
            target: AIModelTarget,
            timeout_seconds: float,
        ) -> StructuredProviderResponse:
            response = await provider.generate_structured(
                target=target,
                request=request,
                timeout_seconds=timeout_seconds,
            )
            try:
                Draft202012Validator(schema).validate(response.data)
            except ValidationError as exc:
                raise AIProviderError(
                    AIErrorCode.STRUCTURED_OUTPUT_INVALID,
                    "Structured output 未通过 JSON Schema 校验",
                    retryable=True,
                ) from exc
            return response

        target, response, cost, inv_id = await self._execute(
            route=route,
            capability="structured_output",
            input_hash=_input_hash(normalized),
            estimated_input_tokens=estimated_input_tokens,
            reserved_output_tokens=reserved_output,
            context=context or InvocationContext(),
            invocation_id=invocation_id,
            provider_call=call,
        )
        return GatewayStructuredResult(
            invocation_id=inv_id,
            provider_key=target.provider_key,
            model_name=target.model_name,
            data=response.data,
            usage=response.usage,
            estimated_cost=cost,
        )

    async def route_snapshot(
        self,
        *,
        task_key: str,
        capability: str,
        primary_only: bool = False,
    ) -> AIRouteSnapshot:
        async with self.session_factory() as session:
            return await AIRouteRepository(session).active_snapshot(
                task_key=task_key,
                capability=capability,
                primary_only=primary_only,
            )

    async def _execute(
        self,
        *,
        route: AIRouteSnapshot,
        capability: str,
        input_hash: str,
        estimated_input_tokens: int,
        reserved_output_tokens: int,
        context: InvocationContext,
        invocation_id: UUID | None,
        provider_call: ProviderCall[ProviderResponseT],
    ) -> tuple[AIModelTarget, ProviderResponseT, Decimal | None, UUID]:
        inv_id = invocation_id or uuid4()
        created = await self.invocations.ensure_invocation(
            invocation_id=inv_id,
            route=route,
            capability=capability,
            input_hash=input_hash,
            prompt_version=context.prompt_version,
            schema_version=context.schema_version,
            subject_type=context.subject_type,
            subject_id=context.subject_id,
            metadata={**context.metadata, "test": context.test},
        )
        if not created:
            raise AIGatewayError(
                AIErrorCode.INVALID_REQUEST,
                "相同 Invocation 已存在，未重复调用 Provider",
            )
        invocation_started = perf_counter()
        attempt_no = 0
        retry_total = 0
        last_error: AIGatewayError | None = None
        last_target: AIModelTarget | None = None
        last_fallback_index = 0

        for fallback_index, target in enumerate(route.targets):
            last_target = target
            last_fallback_index = fallback_index
            adapter = self.provider_factory.build(target.provider_type)
            max_retries = min(route.retry_limit, target.provider_retry_limit, 3)
            for retry_index in range(max_retries + 1):
                attempt_no += 1
                reserve_cost, reserve_tokens = reserve_estimate(
                    target=target,
                    capability=capability,
                    estimated_input_tokens=estimated_input_tokens,
                    reserved_output_tokens=reserved_output_tokens,
                )
                reservation: AIBudgetReservation | None = None
                started_at = datetime.now(UTC)
                attempt_started = perf_counter()
                try:
                    reservation = await self.budgets.reserve(
                        task_key=route.task_key,
                        provider_key=target.provider_key,
                        estimated_cost=reserve_cost,
                        estimated_tokens=reserve_tokens,
                    )
                    response = await provider_call(
                        adapter,
                        target,
                        float(min(route.timeout_seconds, target.provider_timeout_seconds)),
                    )
                    usage = response.usage
                    cost = estimate_cost(target=target, capability=capability, usage=usage)
                    actual_tokens = _actual_tokens(usage)
                    await self.budgets.settle(
                        reservation,
                        completed=True,
                        actual_cost=cost,
                        actual_tokens=actual_tokens,
                    )
                    latency_ms = max(0, round((perf_counter() - attempt_started) * 1000))
                    finished_at = datetime.now(UTC)
                    price_snapshot = pricing_snapshot(target)
                    await self.invocations.add_attempt(
                        invocation_id=inv_id,
                        attempt_no=attempt_no,
                        retry_index=retry_index,
                        fallback_index=fallback_index,
                        provider_key=target.provider_key,
                        model_name=target.model_name,
                        status="succeeded",
                        started_at=started_at,
                        finished_at=finished_at,
                        usage=usage,
                        estimated_cost=cost,
                        pricing_snapshot=price_snapshot,
                        latency_ms=latency_ms,
                        provider_request_id=response.provider_request_id,
                        error_code=None,
                        error_message=None,
                    )
                    total_latency = max(0, round((perf_counter() - invocation_started) * 1000))
                    await self.invocations.finish_success(
                        invocation_id=inv_id,
                        provider_key=target.provider_key,
                        model_name=target.model_name,
                        usage=usage,
                        estimated_cost=cost,
                        pricing_snapshot=price_snapshot,
                        latency_ms=total_latency,
                        retry_count=retry_total,
                        fallback_index=fallback_index,
                        provider_request_id=response.provider_request_id,
                    )
                    self._log_final(
                        invocation_id=inv_id,
                        route=route,
                        target=target,
                        status="succeeded",
                        latency_ms=total_latency,
                        usage=usage,
                        cost=cost,
                        retry_count=retry_total,
                        fallback_index=fallback_index,
                    )
                    return target, response, cost, inv_id
                except AIGatewayError as exc:
                    last_error = exc
                    failure_usage = exc.provider_usage
                    cost = (
                        estimate_cost(
                            target=target,
                            capability=capability,
                            usage=failure_usage,
                        )
                        if failure_usage is not None
                        else None
                    )
                    if reservation is not None:
                        possibly_billed = (
                            exc.code in _POSSIBLY_BILLED_ERRORS
                            or failure_usage is not None
                        )
                        await self.budgets.settle(
                            reservation,
                            completed=possibly_billed,
                            actual_cost=cost,
                            actual_tokens=(
                                _actual_tokens(failure_usage)
                                if failure_usage is not None
                                else None
                            ),
                        )
                    latency_ms = max(0, round((perf_counter() - attempt_started) * 1000))
                    await self.invocations.add_attempt(
                        invocation_id=inv_id,
                        attempt_no=attempt_no,
                        retry_index=retry_index,
                        fallback_index=fallback_index,
                        provider_key=target.provider_key,
                        model_name=target.model_name,
                        status="blocked" if exc.code is AIErrorCode.BUDGET_EXCEEDED else "failed",
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        usage=failure_usage,
                        estimated_cost=cost,
                        pricing_snapshot=pricing_snapshot(target),
                        latency_ms=latency_ms,
                        provider_request_id=exc.provider_request_id,
                        error_code=exc.code.value,
                        error_message=exc.message,
                        metadata=provider_error_metadata(exc),
                    )
                    can_retry = exc.retryable and retry_index < max_retries
                    if can_retry:
                        delay = exc.retry_after_seconds or 0.0
                        max_delay = float(route.config.get("max_retry_delay_seconds", 5.0))
                        if delay <= max(0.0, max_delay):
                            retry_total += 1
                            if delay > 0:
                                await asyncio.sleep(delay)
                            continue
                    break
            if last_error is None or last_error.code not in _RETRYABLE_FALLBACK_ERRORS:
                break

        error = last_error or AIGatewayError(
            AIErrorCode.UNKNOWN_PROVIDER_ERROR,
            "AI Gateway 未获得 Provider 结果",
        )
        total_latency = max(0, round((perf_counter() - invocation_started) * 1000))
        await self.invocations.finish_failure(
            invocation_id=inv_id,
            error_code=error.code.value,
            provider_key=last_target.provider_key if last_target else None,
            model_name=last_target.model_name if last_target else None,
            latency_ms=total_latency,
            retry_count=retry_total,
            fallback_index=last_fallback_index,
            usage=error.provider_usage,
            estimated_cost=(
                estimate_cost(
                    target=last_target,
                    capability=capability,
                    usage=error.provider_usage,
                )
                if last_target is not None and error.provider_usage is not None
                else None
            ),
            pricing_snapshot=pricing_snapshot(last_target) if last_target is not None else None,
            provider_request_id=error.provider_request_id,
        )
        if last_target is not None:
            self._log_final(
                invocation_id=inv_id,
                route=route,
                target=last_target,
                status="failed",
                latency_ms=total_latency,
                usage=AIUsage(),
                cost=None,
                retry_count=retry_total,
                fallback_index=last_fallback_index,
                error_code=error.code.value,
            )
        raise error

    @staticmethod
    def _log_final(
        *,
        invocation_id: UUID,
        route: AIRouteSnapshot,
        target: AIModelTarget,
        status: str,
        latency_ms: int,
        usage: AIUsage,
        cost: Decimal | None,
        retry_count: int,
        fallback_index: int,
        error_code: str | None = None,
    ) -> None:
        logger.info(
            "ai_invocation_complete",
            extra={
                "invocation_id": str(invocation_id),
                "ai_task": route.task_key,
                "ai_route_version": route.version,
                "ai_provider_key": target.provider_key,
                "ai_model": target.model_name,
                "ai_status": status,
                "ai_latency_ms": latency_ms,
                "ai_tokens": _actual_tokens(usage),
                "ai_cost": str(cost) if cost is not None else None,
                "ai_retry": retry_count,
                "ai_fallback": fallback_index,
                "ai_error_code": error_code,
            },
        )


def _input_hash(value: dict[str, object]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _actual_tokens(usage: AIUsage) -> int | None:
    if usage.total_tokens is not None:
        return usage.total_tokens
    if usage.input_tokens is not None and usage.output_tokens is not None:
        return usage.input_tokens + usage.output_tokens
    return usage.input_tokens


def _validate_messages(messages: tuple[AIMessage, ...]) -> None:
    if not messages:
        raise AIGatewayError(AIErrorCode.INVALID_REQUEST, "AI messages 不能为空")
    for message in messages:
        if message.role not in {"system", "user", "assistant"} or not message.content.strip():
            raise AIGatewayError(AIErrorCode.INVALID_REQUEST, "AI message role/content 无效")
