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
from packages.database.models import ConnectorRun, ConnectorRunStatus
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
        checkpoint_before: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorRun:
        if requested_limit < 0:
            raise BusinessValidationError("requested_limit 不能为负数")
        async with self.session.begin():
            run = ConnectorRun(
                connector_instance_id=connector_instance_id,
                platform_account_id=platform_account_id,
                mode=mode,
                status=ConnectorRunStatus.PENDING,
                requested_limit=requested_limit,
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
    ) -> Page[ConnectorRun]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            connector_instance_id=connector_instance_id,
            platform_account_id=platform_account_id,
            status=status,
            started_from=started_from,
            started_to=started_to,
        )

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
        async with self.session.begin():
            run = await self.repository.get(run_id)
            if run is None:
                raise ResourceNotFoundError("连接器运行记录不存在")
            if target_status not in RUN_TRANSITIONS[run.status]:
                raise InvalidStateTransitionError(
                    f"Run 不能从 {run.status.value} 变为 {target_status.value}"
                )
            now = datetime.now(UTC)
            if target_status is ConnectorRunStatus.RUNNING:
                run.started_at = now
            if target_status in TERMINAL_RUN_STATUSES:
                effective_finished = finished_at or now
                if effective_finished.tzinfo is None or effective_finished.utcoffset() is None:
                    raise BusinessValidationError("finished_at 必须包含时区")
                if run.started_at is not None and effective_finished < run.started_at:
                    raise BusinessValidationError("完成时间不能早于开始时间")
                run.finished_at = effective_finished
            run.status = target_status
            run.error_code = error_code
            run.error_message = error_message
            run.checkpoint_after = checkpoint_after
        return run

    async def update_progress(
        self,
        *,
        run_id: UUID,
        collected_count: int,
        inserted_count: int,
        duplicate_count: int,
        retry_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorRun:
        counts = [collected_count, inserted_count, duplicate_count, retry_count]
        if any(value < 0 for value in counts):
            raise BusinessValidationError("Run 计数不能为负数")
        async with self.session.begin():
            run = await self.repository.get(run_id)
            if run is None:
                raise ResourceNotFoundError("连接器运行记录不存在")
            if run.status in TERMINAL_RUN_STATUSES:
                raise InvalidStateTransitionError("终态 Run 不允许继续修改")
            run.collected_count = collected_count
            run.inserted_count = inserted_count
            run.duplicate_count = duplicate_count
            run.retry_count = retry_count
            if metadata is not None:
                run.run_metadata = sanitize_context(metadata)
        return run
