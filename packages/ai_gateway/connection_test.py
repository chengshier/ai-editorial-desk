from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import select
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
    AIUsage,
    EmbeddingProviderRequest,
    StructuredProviderRequest,
    TextProviderRequest,
)
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError, provider_error_metadata
from packages.ai_gateway.invocations import AIInvocationStore
from packages.ai_gateway.openai_compatible import DefaultProviderAdapterFactory
from packages.ai_gateway.providers import ProviderAdapterFactory
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    AIInvocationAttemptRecord,
    AIInvocationRecord,
    AIModelRecord,
    AIProviderRecord,
)


class AIConnectionTester:
    """Execute one tiny, explicit provider test without route fallback shortcuts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        provider_factory: ProviderAdapterFactory | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.production_validation_eligible = provider_factory is None
        self.provider_factory = provider_factory or DefaultProviderAdapterFactory()
        self.budgets = AIBudgetGate(session_factory)
        self.invocations = AIInvocationStore(session_factory)

    async def test(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
        actor: str,
    ) -> tuple[UUID | None, str, str | None]:
        target, capability = await self._target(
            provider_id=provider_id,
            model_id=model_id,
        )
        invocation_id = uuid4()
        started_at = datetime.now(UTC)
        input_hash = hashlib.sha256(b"provider-connection-test-v1:ping").hexdigest()
        async with self.session_factory() as session:
            async with session.begin():
                session.add(
                    AIInvocationRecord(
                        id=invocation_id,
                        task_key="provider_connection_test",
                        route_id=None,
                        route_version=1,
                        capability=capability,
                        status="running",
                        input_hash=input_hash,
                        metadata_json={
                            "test": True,
                            "production_validation_eligible": (
                                self.production_validation_eligible
                            ),
                        },
                        started_at=started_at,
                    )
                )
        estimated_tokens = approximate_input_tokens("ping")
        reserve_cost, reserve_tokens = reserve_estimate(
            target=target,
            capability=capability,
            estimated_input_tokens=estimated_tokens,
            reserved_output_tokens=1,
        )
        reservation: AIBudgetReservation | None = None
        attempt_started = perf_counter()
        try:
            reservation = await self.budgets.reserve(
                task_key="provider_connection_test",
                provider_key=target.provider_key,
                estimated_cost=reserve_cost,
                estimated_tokens=reserve_tokens,
            )
            usage, request_id = await self._call(
                target=target,
                capability=capability,
            )
            cost = estimate_cost(
                target=target,
                capability=capability,
                usage=usage,
            )
            actual_tokens = usage.total_tokens or usage.input_tokens
            await self.budgets.settle(
                reservation,
                completed=True,
                actual_cost=cost,
                actual_tokens=actual_tokens,
            )
            latency_ms = max(0, round((perf_counter() - attempt_started) * 1000))
            await self.invocations.add_attempt(
                invocation_id=invocation_id,
                attempt_no=1,
                retry_index=0,
                fallback_index=0,
                provider_key=target.provider_key,
                model_name=target.model_name,
                status="succeeded",
                started_at=started_at,
                finished_at=datetime.now(UTC),
                usage=usage,
                estimated_cost=cost,
                pricing_snapshot=pricing_snapshot(target),
                latency_ms=latency_ms,
                provider_request_id=request_id,
                error_code=None,
                error_message=None,
                metadata={
                    "test": True,
                    "production_validation_eligible": (
                        self.production_validation_eligible
                    ),
                },
            )
            await self.invocations.finish_success(
                invocation_id=invocation_id,
                provider_key=target.provider_key,
                model_name=target.model_name,
                usage=usage,
                estimated_cost=cost,
                pricing_snapshot=pricing_snapshot(target),
                latency_ms=latency_ms,
                retry_count=0,
                fallback_index=0,
                provider_request_id=request_id,
            )
            await self._validation_status(provider_id, "PASSED", actor)
            return invocation_id, "succeeded", None
        except AIGatewayError as exc:
            if reservation is not None:
                await self.budgets.settle(
                    reservation,
                    completed=exc.code
                    in {
                        AIErrorCode.TIMEOUT,
                        AIErrorCode.NETWORK_ERROR,
                        AIErrorCode.INVALID_RESPONSE,
                    },
                    actual_cost=None,
                    actual_tokens=None,
                )
            latency_ms = max(0, round((perf_counter() - attempt_started) * 1000))
            await self.invocations.add_attempt(
                invocation_id=invocation_id,
                attempt_no=1,
                retry_index=0,
                fallback_index=0,
                provider_key=target.provider_key,
                model_name=target.model_name,
                status=(
                    "blocked"
                    if exc.code is AIErrorCode.BUDGET_EXCEEDED
                    else "failed"
                ),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                usage=None,
                estimated_cost=None,
                pricing_snapshot=pricing_snapshot(target),
                latency_ms=latency_ms,
                provider_request_id=None,
                error_code=exc.code.value,
                error_message=exc.message,
                metadata={
                    "test": True,
                    "production_validation_eligible": (
                        self.production_validation_eligible
                    ),
                    **provider_error_metadata(exc),
                },
            )
            await self.invocations.finish_failure(
                invocation_id=invocation_id,
                error_code=exc.code.value,
                provider_key=target.provider_key,
                model_name=target.model_name,
                latency_ms=latency_ms,
                retry_count=0,
                fallback_index=0,
            )
            if exc.code is not AIErrorCode.CREDENTIAL_NOT_CONFIGURED:
                await self._validation_status(provider_id, "FAILED", actor)
            return invocation_id, "failed", exc.code.value

    async def error_detail(self, invocation_id: UUID | None) -> dict[str, str] | None:
        """Return only persisted, sanitized provider diagnostics for validation output."""

        if invocation_id is None:
            return None
        async with self.session_factory() as session:
            attempt = await session.scalar(
                select(AIInvocationAttemptRecord)
                .where(AIInvocationAttemptRecord.invocation_id == invocation_id)
                .order_by(AIInvocationAttemptRecord.attempt_no.desc())
                .limit(1)
            )
            if attempt is None:
                return None
            value = attempt.metadata_json.get("provider_error_detail")
            if not isinstance(value, dict):
                return None
            allowed = {
                "provider_error_type",
                "provider_error_code",
                "provider_error_param",
                "provider_error_message",
            }
            detail = {
                key: item
                for key, item in value.items()
                if key in allowed and isinstance(item, str)
            }
            return detail or None

    async def _call(
        self,
        *,
        target: AIModelTarget,
        capability: str,
    ) -> tuple[AIUsage, str | None]:
        adapter = self.provider_factory.build(target.provider_type)
        timeout = float(min(target.provider_timeout_seconds, 10))
        if capability == "embedding":
            response = await adapter.embed(
                target=target,
                request=EmbeddingProviderRequest(texts=("ping",)),
                timeout_seconds=timeout,
            )
            return response.usage, response.provider_request_id
        if capability == "structured_output":
            response = await adapter.generate_structured(
                target=target,
                request=StructuredProviderRequest(
                    messages=(
                        AIMessage(
                            role="user",
                            content='Return {"ok":true}.',
                        ),
                    ),
                    schema={
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                    schema_name="connection_test",
                    max_output_tokens=8,
                    temperature=0,
                ),
                timeout_seconds=timeout,
            )
            return response.usage, response.provider_request_id
        response = await adapter.generate_text(
            target=target,
            request=TextProviderRequest(
                messages=(AIMessage(role="user", content="ping"),),
                max_output_tokens=1,
                temperature=0,
            ),
            timeout_seconds=timeout,
        )
        return response.usage, response.provider_request_id

    async def _target(
        self,
        *,
        provider_id: UUID,
        model_id: UUID,
    ) -> tuple[AIModelTarget, str]:
        async with self.session_factory() as session:
            model = await session.get(AIModelRecord, model_id)
            provider = await session.get(AIProviderRecord, provider_id)
            if model is None or provider is None or model.provider_id != provider.id:
                raise AIGatewayError(
                    AIErrorCode.INVALID_REQUEST,
                    "Connection test Model/Provider 无效",
                )
            if not provider.enabled or not model.enabled:
                raise AIGatewayError(
                    AIErrorCode.INVALID_REQUEST,
                    "Connection test 要求 enabled Provider/Model",
                )
            if "embedding" in model.capabilities:
                capability = "embedding"
            elif "text_generation" in model.capabilities:
                capability = "text_generation"
            elif "structured_output" in model.capabilities:
                capability = "structured_output"
            else:
                raise AIGatewayError(
                    AIErrorCode.CAPABILITY_NOT_SUPPORTED,
                    "没有可测试的 M4-A capability",
                )
            return (
                AIModelTarget(
                    model_id=model.id,
                    provider_id=provider.id,
                    provider_key=provider.provider_key,
                    provider_type=provider.provider_type,
                    base_url=provider.base_url,
                    credential_ref=provider.credential_ref,
                    provider_timeout_seconds=provider.timeout_seconds,
                    provider_retry_limit=provider.retry_limit,
                    provider_config=dict(provider.config),
                    model_key=model.model_key,
                    model_name=model.model_name,
                    capabilities=tuple(str(value) for value in model.capabilities),
                    dimensions=model.dimensions,
                    input_price_per_million=model.input_price_per_million,
                    output_price_per_million=model.output_price_per_million,
                    embedding_price_per_million=model.embedding_price_per_million,
                    pricing_version=model.pricing_version,
                    model_config=dict(model.config),
                ),
                capability,
            )

    async def _validation_status(
        self,
        provider_id: UUID,
        status: str,
        actor: str,
    ) -> None:
        if not self.production_validation_eligible:
            return
        async with self.session_factory() as session:
            async with session.begin():
                provider = await session.get(
                    AIProviderRecord,
                    provider_id,
                    with_for_update=True,
                )
                if provider is None:
                    return
                before = {
                    "validation_status": provider.validation_status,
                    "last_validated_at": (
                        provider.last_validated_at.isoformat()
                        if provider.last_validated_at
                        else None
                    ),
                }
                provider.validation_status = status
                provider.last_validated_at = datetime.now(UTC)
                provider.updated_by = actor
                AuditLogRepository(session).add(
                    entity_type="ai_provider",
                    entity_id=provider.id,
                    action="connection_test",
                    actor=actor,
                    before_data=before,
                    after_data={
                        "validation_status": provider.validation_status,
                        "last_validated_at": provider.last_validated_at.isoformat(),
                    },
                )
