from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.collector_runtime import CollectionTask, TriggerType
from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ResourceNotFoundError,
    VersionConflictError,
)
from packages.connector_management.repositories import (
    AuditLogRepository,
    ConnectorCheckpointRepository,
    Page,
)
from packages.connector_management.services import ConnectorRunService
from packages.database.models import (
    CollectionSchedule,
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorValidationRecord,
    ConnectorValidationStatus,
    PlatformAccount,
    SchedulerInstance,
    ScheduleType,
    Source,
)
from packages.database.types import sanitize_context
from packages.scheduling.calculations import calculate_next_run, validate_schedule_spec

STALE_RUN_DEFAULT_SECONDS = 1800
RETRYABLE_STATUSES = frozenset(
    {
        ConnectorRunStatus.FAILED,
        ConnectorRunStatus.PARTIAL,
        ConnectorRunStatus.CANCELLED,
    }
)


def _schedule_snapshot(schedule: CollectionSchedule) -> dict[str, Any]:
    return {
        "connector_instance_id": str(schedule.connector_instance_id),
        "source_id": str(schedule.source_id),
        "platform_account_id": (
            str(schedule.platform_account_id) if schedule.platform_account_id else None
        ),
        "name": schedule.name,
        "enabled": schedule.enabled,
        "schedule_type": schedule.schedule_type.value,
        "interval_seconds": schedule.interval_seconds,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "requested_limit": schedule.requested_limit,
        "next_run_at": schedule.next_run_at.isoformat(),
        "paused_reason": schedule.paused_reason,
    }


class ScheduleAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditLogRepository(session)

    async def get(self, schedule_id: UUID) -> CollectionSchedule:
        schedule = await self.session.get(CollectionSchedule, schedule_id)
        if schedule is None:
            raise ResourceNotFoundError("调度不存在")
        return schedule

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        enabled: bool | None = None,
        source_id: UUID | None = None,
    ) -> Page[CollectionSchedule]:
        filters = []
        if enabled is not None:
            filters.append(CollectionSchedule.enabled == enabled)
        if source_id is not None:
            filters.append(CollectionSchedule.source_id == source_id)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(CollectionSchedule).where(*filters)
            )
            or 0
        )
        statement = (
            select(CollectionSchedule)
            .where(*filters)
            .order_by(CollectionSchedule.created_at.desc(), CollectionSchedule.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def create(
        self,
        *,
        connector_instance_id: UUID,
        source_id: UUID,
        platform_account_id: UUID | None,
        name: str,
        schedule_type: ScheduleType,
        interval_seconds: int | None,
        cron_expression: str | None,
        timezone: str,
        requested_limit: int,
        actor: str,
    ) -> CollectionSchedule:
        normalized_name = name.strip()
        if not normalized_name:
            raise BusinessValidationError("调度名称不能为空")
        if requested_limit < 1:
            raise BusinessValidationError("requested_limit 必须大于 0")
        validate_schedule_spec(
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            timezone_name=timezone,
        )
        now = datetime.now(UTC)
        async with self.session.begin():
            await self._validate_links(
                connector_instance_id=connector_instance_id,
                source_id=source_id,
                platform_account_id=platform_account_id,
            )
            duplicate = await self.session.scalar(
                select(CollectionSchedule).where(
                    CollectionSchedule.source_id == source_id,
                    CollectionSchedule.name == normalized_name,
                )
            )
            if duplicate is not None:
                raise ConflictError("同一 Source 下调度名称已存在")
            schedule = CollectionSchedule(
                connector_instance_id=connector_instance_id,
                source_id=source_id,
                platform_account_id=platform_account_id,
                name=normalized_name,
                enabled=True,
                schedule_type=schedule_type,
                interval_seconds=interval_seconds,
                cron_expression=cron_expression,
                timezone=timezone,
                requested_limit=requested_limit,
                next_run_at=calculate_next_run(
                    schedule_type=schedule_type,
                    interval_seconds=interval_seconds,
                    cron_expression=cron_expression,
                    timezone_name=timezone,
                    reference=now,
                ),
                consecutive_failures=0,
                updated_by=actor,
            )
            self.session.add(schedule)
            await self.session.flush()
            self.audit.add(
                entity_type="collection_schedule",
                entity_id=schedule.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_schedule_snapshot(schedule),
            )
        return schedule

    async def update(
        self, *, schedule_id: UUID, changes: dict[str, Any], actor: str
    ) -> CollectionSchedule:
        async with self.session.begin():
            schedule = await self.session.get(CollectionSchedule, schedule_id)
            if schedule is None:
                raise ResourceNotFoundError("调度不存在")
            before = _schedule_snapshot(schedule)
            name = str(changes.get("name", schedule.name)).strip()
            schedule_type = ScheduleType(changes.get("schedule_type", schedule.schedule_type))
            interval_seconds = changes.get("interval_seconds", schedule.interval_seconds)
            cron_expression = changes.get("cron_expression", schedule.cron_expression)
            timezone = str(changes.get("timezone", schedule.timezone))
            requested_limit = int(changes.get("requested_limit", schedule.requested_limit))
            validate_schedule_spec(
                schedule_type=schedule_type,
                interval_seconds=interval_seconds,
                cron_expression=cron_expression,
                timezone_name=timezone,
            )
            if requested_limit < 1:
                raise BusinessValidationError("requested_limit 必须大于 0")
            if name != schedule.name:
                duplicate = await self.session.scalar(
                    select(CollectionSchedule).where(
                        CollectionSchedule.source_id == schedule.source_id,
                        CollectionSchedule.name == name,
                        CollectionSchedule.id != schedule.id,
                    )
                )
                if duplicate is not None:
                    raise ConflictError("同一 Source 下调度名称已存在")
            schedule.name = name
            schedule.schedule_type = schedule_type
            schedule.interval_seconds = interval_seconds
            schedule.cron_expression = cron_expression
            schedule.timezone = timezone
            schedule.requested_limit = requested_limit
            if "enabled" in changes:
                schedule.enabled = bool(changes["enabled"])
            if any(
                key in changes
                for key in ("schedule_type", "interval_seconds", "cron_expression", "timezone")
            ):
                schedule.next_run_at = calculate_next_run(
                    schedule_type=schedule_type,
                    interval_seconds=interval_seconds,
                    cron_expression=cron_expression,
                    timezone_name=timezone,
                    reference=datetime.now(UTC),
                )
            schedule.updated_by = actor
            self.audit.add(
                entity_type="collection_schedule",
                entity_id=schedule.id,
                action="update",
                actor=actor,
                before_data=before,
                after_data=_schedule_snapshot(schedule),
            )
        return schedule

    async def pause(self, *, schedule_id: UUID, actor: str, reason: str) -> CollectionSchedule:
        return await self._lifecycle(
            schedule_id=schedule_id, actor=actor, enabled=False, reason=reason, action="pause"
        )

    async def resume(self, *, schedule_id: UUID, actor: str) -> CollectionSchedule:
        async with self.session.begin():
            schedule = await self.session.get(CollectionSchedule, schedule_id)
            if schedule is None:
                raise ResourceNotFoundError("调度不存在")
            before = _schedule_snapshot(schedule)
            schedule.enabled = True
            schedule.paused_reason = None
            schedule.lease_owner = None
            schedule.lease_expires_at = None
            schedule.next_run_at = calculate_next_run(
                schedule_type=schedule.schedule_type,
                interval_seconds=schedule.interval_seconds,
                cron_expression=schedule.cron_expression,
                timezone_name=schedule.timezone,
                reference=datetime.now(UTC),
            )
            schedule.updated_by = actor
            self.audit.add(
                entity_type="collection_schedule",
                entity_id=schedule.id,
                action="resume",
                actor=actor,
                before_data=before,
                after_data=_schedule_snapshot(schedule),
            )
        return schedule

    async def _lifecycle(
        self,
        *,
        schedule_id: UUID,
        actor: str,
        enabled: bool,
        reason: str | None,
        action: str,
    ) -> CollectionSchedule:
        async with self.session.begin():
            schedule = await self.session.get(CollectionSchedule, schedule_id)
            if schedule is None:
                raise ResourceNotFoundError("调度不存在")
            before = _schedule_snapshot(schedule)
            schedule.enabled = enabled
            schedule.paused_reason = reason
            schedule.lease_owner = None
            schedule.lease_expires_at = None
            schedule.updated_by = actor
            self.audit.add(
                entity_type="collection_schedule",
                entity_id=schedule.id,
                action=action,
                actor=actor,
                before_data=before,
                after_data=_schedule_snapshot(schedule),
            )
        return schedule

    async def _validate_links(
        self,
        *,
        connector_instance_id: UUID,
        source_id: UUID,
        platform_account_id: UUID | None,
    ) -> None:
        instance = await self.session.get(ConnectorInstance, connector_instance_id)
        source = await self.session.get(Source, source_id)
        if instance is None:
            raise ResourceNotFoundError("连接器实例不存在")
        if source is None or source.connector_instance_id != connector_instance_id:
            raise ConflictError("Source 不存在或不属于该实例")
        if platform_account_id is not None:
            account = await self.session.get(PlatformAccount, platform_account_id)
            if account is None or account.connector_instance_id != connector_instance_id:
                raise ConflictError("平台账号不存在或不属于该实例")


class RunRecoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_stale(
        self, *, page: int, page_size: int, stale_seconds: int = STALE_RUN_DEFAULT_SECONDS
    ) -> Page[ConnectorRun]:
        if stale_seconds < 300:
            raise BusinessValidationError("stale_seconds 不得低于 300")
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        freshness = func.coalesce(ConnectorRun.progress_updated_at, ConnectorRun.started_at)
        filters = [ConnectorRun.status == ConnectorRunStatus.RUNNING, freshness <= cutoff]
        count_query = select(func.count()).select_from(ConnectorRun).where(*filters)
        total = int(await self.session.scalar(count_query) or 0)
        items = list(
            (
                await self.session.scalars(
                    select(ConnectorRun)
                    .where(*filters)
                    .order_by(freshness.asc(), ConnectorRun.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def build_retry_task(self, *, run_id: UUID, actor: str) -> CollectionTask:
        run = await ConnectorRunService(self.session).get(run_id)
        if run.status not in RETRYABLE_STATUSES:
            raise ConflictError("只有 failed/partial/cancelled Run 可以人工重试")
        if run.source_id is None:
            raise ConflictError("历史 Run 缺少 Source，无法安全重试")
        source = await self.session.get(Source, run.source_id)
        if source is None:
            raise ResourceNotFoundError("Run 对应 Source 不存在")
        return CollectionTask(
            task_id=uuid4(),
            connector_instance_id=run.connector_instance_id,
            source_id=run.source_id,
            platform_account_id=run.platform_account_id,
            mode=source.mode,
            requested_limit=max(run.requested_limit, 1),
            checkpoint_version=None,
            trigger_type=TriggerType.RETRY,
            triggered_by=actor,
            created_at=datetime.now(UTC),
            parent_run_id=run.id,
            retry_count=run.retry_count + 1,
        )

    async def mark_failed(self, *, run_id: UUID, reason: str) -> ConnectorRun:
        run = await ConnectorRunService(self.session).get(run_id)
        if run.status is not ConnectorRunStatus.RUNNING:
            raise ConflictError("只有 RUNNING Run 可以人工标记 stale failure")
        await self.session.rollback()
        return await ConnectorRunService(self.session).finalize(
            run_id=run_id,
            target_status=ConnectorRunStatus.FAILED,
            failed_count=max(run.failed_count, 1),
            error_code="stale_run_marked_failed",
            error_message=reason,
        )


class CheckpointDebugService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditLogRepository(session)
        self.repository = ConnectorCheckpointRepository(session)

    async def get(self, checkpoint_id: UUID) -> ConnectorCheckpoint:
        checkpoint = await self.session.get(ConnectorCheckpoint, checkpoint_id)
        if checkpoint is None:
            raise ResourceNotFoundError("Checkpoint 不存在")
        return checkpoint

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None,
        source_id: UUID | None,
        platform_account_id: UUID | None,
        mode: str | None,
        scope_key: str | None,
    ) -> Page[ConnectorCheckpoint]:
        filters = []
        if connector_instance_id is not None:
            filters.append(ConnectorCheckpoint.connector_instance_id == connector_instance_id)
        if source_id is not None:
            filters.append(ConnectorCheckpoint.source_id == source_id)
        if platform_account_id is not None:
            filters.append(ConnectorCheckpoint.platform_account_id == platform_account_id)
        if mode is not None:
            filters.append(ConnectorCheckpoint.mode == mode)
        if scope_key is not None:
            filters.append(ConnectorCheckpoint.scope_key == scope_key)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ConnectorCheckpoint).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(ConnectorCheckpoint)
                    .where(*filters)
                    .order_by(ConnectorCheckpoint.updated_at.desc(), ConnectorCheckpoint.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def reset(
        self, *, checkpoint_id: UUID, expected_version: int, reason: str, actor: str
    ) -> ConnectorCheckpoint:
        if not reason.strip():
            raise BusinessValidationError("Checkpoint reset 必须填写 reason")
        async with self.session.begin():
            before_checkpoint = await self.repository.get(checkpoint_id)
            if before_checkpoint is None:
                raise ResourceNotFoundError("Checkpoint 不存在")
            before = self._snapshot(before_checkpoint)
            updated = await self.repository.optimistic_update(
                checkpoint_id=checkpoint_id,
                expected_version=expected_version,
                cursor=None,
                watermark=None,
                last_external_id=None,
                last_published_at=None,
                checkpoint_data={},
            )
            if updated is None:
                current = await self.repository.get(checkpoint_id)
                if current is None:
                    raise ResourceNotFoundError("Checkpoint 不存在")
                raise VersionConflictError(
                    "Checkpoint 版本冲突",
                    details={
                        "expected_version": expected_version,
                        "current_version": current.version,
                    },
                )
            self.audit.add(
                entity_type="connector_checkpoint",
                entity_id=updated.id,
                action="reset",
                actor=actor,
                before_data=before,
                after_data={**self._snapshot(updated), "reason": reason.strip()},
            )
        return updated

    @staticmethod
    def _snapshot(checkpoint: ConnectorCheckpoint) -> dict[str, Any]:
        return sanitize_context(
            {
                "source_id": str(checkpoint.source_id) if checkpoint.source_id else None,
                "mode": checkpoint.mode,
                "scope_key": checkpoint.scope_key,
                "cursor": checkpoint.cursor,
                "watermark": checkpoint.watermark,
                "last_external_id": checkpoint.last_external_id,
                "last_published_at": (
                    checkpoint.last_published_at.isoformat()
                    if checkpoint.last_published_at
                    else None
                ),
                "checkpoint_data": checkpoint.checkpoint_data,
                "version": checkpoint.version,
            }
        )


class ConnectorValidationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        connector_type: str,
        platform: str,
        implementation_version: str,
        environment: str,
        status: ConnectorValidationStatus,
        actor: str,
        notes: str | None,
        safe_evidence: dict[str, Any],
        real_smoke_test: bool,
    ) -> ConnectorValidationRecord:
        now = datetime.now(UTC)
        async with self.session.begin():
            definition = await self.session.scalar(
                select(ConnectorDefinition).where(
                    ConnectorDefinition.connector_type == connector_type,
                    ConnectorDefinition.platform == platform,
                )
            )
            if definition is None:
                raise ResourceNotFoundError("Connector Definition 不存在")
            if implementation_version != definition.implementation_version:
                raise ConflictError("validation 必须针对当前 implementation_version")
            if status is ConnectorValidationStatus.PASSED and not real_smoke_test:
                raise BusinessValidationError("CI/Mock 结果不能写入真实 PASSED validation")
            record = ConnectorValidationRecord(
                connector_type=connector_type,
                platform=platform,
                implementation_version=implementation_version,
                environment=environment,
                status=status,
                validated_at=(
                    now
                    if status
                    in {ConnectorValidationStatus.PASSED, ConnectorValidationStatus.FAILED}
                    else None
                ),
                validated_by=actor,
                notes=notes,
                safe_evidence=sanitize_context(safe_evidence),
                created_at=now,
            )
            self.session.add(record)
            await self.session.flush()
        return record

    async def effective_status(self, definition: ConnectorDefinition) -> ConnectorValidationStatus:
        record = await self.session.scalar(
            select(ConnectorValidationRecord)
            .where(
                ConnectorValidationRecord.connector_type == definition.connector_type,
                ConnectorValidationRecord.platform == definition.platform,
            )
            .order_by(
                ConnectorValidationRecord.created_at.desc(),
                ConnectorValidationRecord.id.desc(),
            )
            .limit(1)
        )
        if record is None:
            return ConnectorValidationStatus.NOT_TESTED
        if record.implementation_version != definition.implementation_version:
            return ConnectorValidationStatus.EXPIRED
        return record.status

    async def list(
        self, *, page: int, page_size: int, connector_type: str | None, platform: str | None
    ) -> Page[ConnectorValidationRecord]:
        filters = []
        if connector_type is not None:
            filters.append(ConnectorValidationRecord.connector_type == connector_type)
        if platform is not None:
            filters.append(ConnectorValidationRecord.platform == platform)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ConnectorValidationRecord).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(ConnectorValidationRecord)
                    .where(*filters)
                    .order_by(
                        ConnectorValidationRecord.created_at.desc(),
                        ConnectorValidationRecord.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)


class SchedulerStatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        latest = await self.session.scalar(
            select(SchedulerInstance)
            .order_by(SchedulerInstance.last_heartbeat.desc())
            .limit(1)
        )
        due = int(
            await self.session.scalar(
                select(func.count())
                .select_from(CollectionSchedule)
                .where(CollectionSchedule.enabled.is_(True), CollectionSchedule.next_run_at <= now)
            )
            or 0
        )
        active = int(
            await self.session.scalar(
                select(func.count())
                .select_from(CollectionSchedule)
                .where(CollectionSchedule.lease_expires_at > now)
            )
            or 0
        )
        return {
            "scheduler_instance": latest.instance_key if latest else None,
            "started_at": latest.started_at if latest else None,
            "last_heartbeat": latest.last_heartbeat if latest else None,
            "active_leases": active,
            "due_schedule_count": due,
            "recent_trigger_failures": latest.recent_trigger_failures if latest else 0,
        }
