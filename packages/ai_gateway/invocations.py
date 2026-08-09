from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.domain import AIRouteSnapshot, AIUsage
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.database.models import AIInvocationAttemptRecord, AIInvocationRecord
from packages.database.types import sanitize_context


class AIInvocationStore:
    """Persist logical invocations and append-only attempts in short transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ensure_invocation(
        self,
        *,
        invocation_id: UUID,
        route: AIRouteSnapshot,
        capability: str,
        input_hash: str,
        prompt_version: str | None,
        schema_version: str | None,
        subject_type: str | None,
        subject_id: str | None,
        metadata: dict[str, object],
    ) -> bool:
        async with self.session_factory() as session:
            async with session.begin():
                existing = await session.get(AIInvocationRecord, invocation_id)
                if existing is not None:
                    if (
                        existing.task_key == route.task_key
                        and existing.route_version == route.version
                        and existing.input_hash == input_hash
                        and existing.capability == capability
                    ):
                        return False
                    raise AIGatewayError(
                        AIErrorCode.INVALID_REQUEST,
                        "Invocation id 已被不同请求占用",
                    )
                clean_metadata = sanitize_context(metadata)
                if not isinstance(clean_metadata, dict):
                    clean_metadata = {}
                session.add(
                    AIInvocationRecord(
                        id=invocation_id,
                        task_key=route.task_key,
                        route_id=route.route_id,
                        route_version=route.version,
                        capability=capability,
                        status="running",
                        input_hash=input_hash,
                        prompt_version=prompt_version,
                        schema_version=schema_version,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        metadata_json=clean_metadata,
                        started_at=datetime.now(UTC),
                    )
                )
        return True

    async def add_attempt(
        self,
        *,
        invocation_id: UUID,
        attempt_no: int,
        retry_index: int,
        fallback_index: int,
        provider_key: str,
        model_name: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        usage: AIUsage | None,
        estimated_cost: Decimal | None,
        pricing_snapshot: dict[str, object],
        latency_ms: int,
        provider_request_id: str | None,
        error_code: str | None,
        error_message: str | None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        clean_metadata = sanitize_context(metadata or {})
        if not isinstance(clean_metadata, dict):
            clean_metadata = {}
        async with self.session_factory() as session:
            async with session.begin():
                session.add(
                    AIInvocationAttemptRecord(
                        invocation_id=invocation_id,
                        attempt_no=attempt_no,
                        retry_index=retry_index,
                        fallback_index=fallback_index,
                        provider_key=provider_key,
                        model_name=model_name,
                        status=status,
                        input_tokens=usage.input_tokens if usage else None,
                        output_tokens=usage.output_tokens if usage else None,
                        total_tokens=usage.total_tokens if usage else None,
                        estimated_cost=estimated_cost,
                        pricing_snapshot=pricing_snapshot,
                        latency_ms=latency_ms,
                        provider_request_id=provider_request_id,
                        error_code=error_code,
                        error_message=error_message,
                        started_at=started_at,
                        finished_at=finished_at,
                        metadata_json=clean_metadata,
                    )
                )

    async def finish_success(
        self,
        *,
        invocation_id: UUID,
        provider_key: str,
        model_name: str,
        usage: AIUsage,
        estimated_cost: Decimal | None,
        pricing_snapshot: dict[str, object],
        latency_ms: int,
        retry_count: int,
        fallback_index: int,
        provider_request_id: str | None,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                invocation = await session.get(AIInvocationRecord, invocation_id)
                if invocation is None:
                    raise RuntimeError("AI invocation 不存在")
                invocation.provider_key = provider_key
                invocation.model_name = model_name
                invocation.status = "succeeded"
                invocation.input_tokens = usage.input_tokens
                invocation.output_tokens = usage.output_tokens
                invocation.total_tokens = usage.total_tokens
                invocation.estimated_cost = estimated_cost
                invocation.pricing_snapshot = pricing_snapshot
                invocation.latency_ms = latency_ms
                invocation.retry_count = retry_count
                invocation.fallback_index = fallback_index
                invocation.provider_request_id = provider_request_id
                invocation.finished_at = datetime.now(UTC)
                invocation.error_code = None

    async def finish_failure(
        self,
        *,
        invocation_id: UUID,
        error_code: str,
        provider_key: str | None,
        model_name: str | None,
        latency_ms: int,
        retry_count: int,
        fallback_index: int,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                invocation = await session.get(AIInvocationRecord, invocation_id)
                if invocation is None:
                    raise RuntimeError("AI invocation 不存在")
                invocation.provider_key = provider_key
                invocation.model_name = model_name
                invocation.status = "failed"
                invocation.latency_ms = latency_ms
                invocation.retry_count = retry_count
                invocation.fallback_index = fallback_index
                invocation.finished_at = datetime.now(UTC)
                invocation.error_code = error_code
