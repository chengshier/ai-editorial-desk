from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    InvalidStateTransitionError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import ConnectorRunRepository, Page
from packages.connector_management.validation import validate_no_sensitive_fields
from packages.database.models import (
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunTriggerType,
)
from packages.database.types import sanitize_context

TERMINAL_RUN_STATUSES = frozenset(
    {
        ConnectorRunStatus.SUCCEEDED,
        ConnectorRunStatus.FAILED,
        ConnectorRunStatus.PARTIAL,
        ConnectorRunStatus.PAUSED_RISK,
        ConnectorRunStatus.CANCELLED,
    }
)
RUN_TRANSITIONS: dict[ConnectorRunStatus, frozenset[ConnectorRunStatus]] = {
    ConnectorRunStatus.PENDING: frozenset(
        {ConnectorRunStatus.RUNNING, ConnectorRunStatus.CANCELLED}
    ),
    ConnectorRunStatus.RUNNING: TERMINAL_RUN_STATUSES,
    ConnectorRunStatus.SUCCEEDED: frozenset(),
    ConnectorRunStatus.FAILED: frozenset(),
    ConnectorRunStatus.PARTIAL: frozenset(),
    ConnectorRunStatus.PAUSED_RISK: frozenset(),
    ConnectorRunStatus.CANCELLED: frozenset(),
}


class ConnectorRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConnectorRunRepository(session)

    async def create_pending(
        self,
        *,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        mode: str,
        requested_limit: int,
        source_id: UUID | None = None,
        checkpoint_before: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        trigger_type: ConnectorRunTriggerType = ConnectorRunTriggerType.MANUAL,
        parent_run_id: UUID | None = None,
        retry_count: int = 0,
    ) -> ConnectorRun:
        if requested_limit < 0 or retry_count < 0:
            raise BusinessValidationError("requested_limit 和 retry_count 不能为负数")
        validate_no_sensitive_fields(checkpoint_before or {}, field_name="checkpoint_before")
        async with self.session.begin():
            run = ConnectorRun(
                connector_instance_id=connector_instance_id,
                source_id=source_id,
                platform_account_id=platform_account_id,
                parent_run_id=parent_run_id,
                trigger_type=trigger_type,
                mode=mode,
                status=ConnectorRunStatus.PENDING,
                requested_limit=requested_limit,
                retry_count=retry_count,
                checkpoint_before=checkpoint_before,
                run_metadata=sanitize_context(metadata or {}),
            )
            self.repository.add(run)
            await self.session.flush()
        return run

    async def get(self, run_id: UUID) -> ConnectorRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise ResourceNotFoundError("连接器运行记录不存在")
        return run

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None,
        platform_account_id: UUID | None,
        status: ConnectorRunStatus | None,
        started_from: datetime | None,
        started_to: datetime | None,
        source_id: UUID | None = None,
    ) -> Page[ConnectorRun]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            connector_instance_id=connector_instance_id,
            platform_account_id=platform_account_id,
            source_id=source_id,
            status=status,
            started_from=started_from,
            started_to=started_to,
        )

    async def claim(self, *, run_id: UUID) -> ConnectorRun:
        now = datetime.now(UTC)
        async with self.session.begin():
            run = await self.repository.atomic_transition(
                run_id=run_id,
                expected_statuses=frozenset({ConnectorRunStatus.PENDING}),
                target_status=ConnectorRunStatus.RUNNING,
                values={"started_at": now, "progress_updated_at": now},
            )
            if run is not None:
                return run
            await self._raise_transition_error(run_id, ConnectorRunStatus.RUNNING)
        raise AssertionError("unreachable")

    async def finalize(
        self,
        *,
        run_id: UUID,
        target_status: ConnectorRunStatus,
        collected_count: int | None = None,
        inserted_count: int | None = None,
        duplicate_count: int | None = None,
        failed_count: int | None = None,
        retry_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        checkpoint_after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> ConnectorRun:
        if target_status not in TERMINAL_RUN_STATUSES:
            raise BusinessValidationError("finalize 只能写入终态")
        validate_no_sensitive_fields(checkpoint_after or {}, field_name="checkpoint_after")
        effective_finished = finished_at or datetime.now(UTC)
        if effective_finished.tzinfo is None or effective_finished.utcoffset() is None:
            raise BusinessValidationError("finished_at 必须包含时区")
        expected_statuses = (
            frozenset({ConnectorRunStatus.PENDING, ConnectorRunStatus.RUNNING})
            if target_status is ConnectorRunStatus.CANCELLED
            else frozenset({ConnectorRunStatus.RUNNING})
        )
        async with self.session.begin():
            existing = await self.repository.get(run_id)
            if existing is None:
                raise ResourceNotFoundError("连接器运行记录不存在")
            if existing.started_at is not None and effective_finished < existing.started_at:
                raise BusinessValidationError("完成时间不能早于开始时间")
            counts = [
                existing.collected_count if collected_count is None else collected_count,
                existing.inserted_count if inserted_count is None else inserted_count,
                existing.duplicate_count if duplicate_count is None else duplicate_count,
                existing.failed_count if failed_count is None else failed_count,
                existing.retry_count if retry_count is None else retry_count,
            ]
            if any(value < 0 for value in counts):
                raise BusinessValidationError("Run 计数不能为负数")
            run = await self.repository.atomic_transition(
                run_id=run_id,
                expected_statuses=expected_statuses,
                target_status=target_status,
                values={
                    "finished_at": effective_finished,
                    "progress_updated_at": effective_finished,
                    "collected_count": counts[0],
                    "inserted_count": counts[1],
                    "duplicate_count": counts[2],
                    "failed_count": counts[3],
                    "retry_count": counts[4],
                    "error_code": error_code,
                    "error_message": error_message,
                    "checkpoint_after": checkpoint_after,
                    "run_metadata": sanitize_context(metadata or existing.run_metadata),
                },
            )
            if run is not None:
                return run
            await self._raise_transition_error(run_id, target_status)
        raise AssertionError("unreachable")

    async def transition(
        self,
        *,
        run_id: UUID,
        target_status: ConnectorRunStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        checkpoint_after: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> ConnectorRun:
        if target_status is ConnectorRunStatus.RUNNING:
            return await self.claim(run_id=run_id)
        return await self.finalize(
            run_id=run_id,
            target_status=target_status,
            error_code=error_code,
            error_message=error_message,
            checkpoint_after=checkpoint_after,
            finished_at=finished_at,
        )

    async def update_progress(
        self,
        *,
        run_id: UUID,
        collected_count: int,
        inserted_count: int,
        duplicate_count: int,
        retry_count: int,
        failed_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorRun:
        counts = [collected_count, inserted_count, duplicate_count, failed_count, retry_count]
        if any(value < 0 for value in counts):
            raise BusinessValidationError("Run 计数不能为负数")
        values: dict[str, Any] = {
            "collected_count": collected_count,
            "inserted_count": inserted_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "retry_count": retry_count,
            "progress_updated_at": datetime.now(UTC),
        }
        if metadata is not None:
            values["run_metadata"] = sanitize_context(metadata)
        async with self.session.begin():
            run = await self.repository.atomic_progress(run_id=run_id, values=values)
            if run is not None:
                return run
            existing = await self.repository.get(run_id)
            if existing is None:
                raise ResourceNotFoundError("连接器运行记录不存在")
            raise InvalidStateTransitionError("只有 RUNNING Run 可以更新进度")

    async def _raise_transition_error(
        self, run_id: UUID, target_status: ConnectorRunStatus
    ) -> None:
        existing = await self.repository.get(run_id)
        if existing is None:
            raise ResourceNotFoundError("连接器运行记录不存在")
        raise InvalidStateTransitionError(
            f"Run 不能从 {existing.status.value} 变为 {target_status.value}"
        )
