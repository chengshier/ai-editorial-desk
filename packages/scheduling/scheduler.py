from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.database.models import (
    CollectionSchedule,
    ConnectorRunStatus,
    ScheduleTriggerStatus,
    Source,
)
from packages.scheduling.calculations import calculate_next_run
from packages.scheduling.repository import ScheduleRepository

logger = logging.getLogger(__name__)
SCHEDULE_CLAIM_SECONDS = 120
RUN_LEASE_SECONDS = 3600


class PersistentScheduler:
    """Small asyncio scheduler whose durable state and leases live in PostgreSQL."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        runtime: CollectorRuntime,
        instance_key: str,
        poll_seconds: float = 5.0,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.instance_key = instance_key
        self.poll_seconds = poll_seconds
        self.started_at = datetime.now(UTC)
        self.recent_trigger_failures = 0

    async def heartbeat(self) -> None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                await ScheduleRepository(session).heartbeat(
                    instance_key=self.instance_key,
                    started_at=self.started_at,
                    now=now,
                    recent_trigger_failures=self.recent_trigger_failures,
                )

    async def tick(self, *, limit: int = 20) -> int:
        await self.heartbeat()
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            due_ids = await ScheduleRepository(session).due_ids(now=now, limit=limit)
        triggered = 0
        for schedule_id in due_ids:
            if await self._dispatch(schedule_id):
                triggered += 1
        return triggered

    async def _dispatch(self, schedule_id: UUID) -> bool:
        now = datetime.now(UTC)
        claim_until = now + timedelta(seconds=SCHEDULE_CLAIM_SECONDS)
        async with self.session_factory() as session:
            async with session.begin():
                repository = ScheduleRepository(session)
                schedule = await repository.claim_schedule(
                    schedule_id=schedule_id,
                    owner=self.instance_key,
                    now=now,
                    lease_expires_at=claim_until,
                )
                if schedule is None:
                    return False
                trigger = await repository.claim_slot(
                    schedule=schedule,
                    owner=self.instance_key,
                    now=now,
                    lease_expires_at=claim_until,
                )
                if trigger is None:
                    await repository.release_schedule(
                        schedule_id=schedule.id, owner=self.instance_key
                    )
                    return False
                if trigger.status is ScheduleTriggerStatus.RUNNING:
                    if trigger.lease_expires_at is None or trigger.lease_expires_at < now:
                        await repository.pause_stale_running_slot(
                            schedule_id=schedule.id,
                            trigger_id=trigger.id,
                            owner=self.instance_key,
                            now=now,
                        )
                    else:
                        await repository.release_schedule(
                            schedule_id=schedule.id, owner=self.instance_key
                        )
                    return False
                if trigger.status is not ScheduleTriggerStatus.CLAIMED:
                    await repository.release_schedule(
                        schedule_id=schedule.id, owner=self.instance_key
                    )
                    return False
                running = await repository.mark_trigger_running(
                    trigger_id=trigger.id,
                    owner=self.instance_key,
                    lease_expires_at=now + timedelta(seconds=RUN_LEASE_SECONDS),
                )
                if running is None:
                    await repository.release_schedule(
                        schedule_id=schedule.id, owner=self.instance_key
                    )
                    return False
                source = await session.get(Source, schedule.source_id)
                if source is None:
                    await repository.pause_stale_running_slot(
                        schedule_id=schedule.id,
                        trigger_id=trigger.id,
                        owner=self.instance_key,
                        now=now,
                    )
                    return False
                source_mode = source.mode
                trigger_id = trigger.id

        task = CollectionTask(
            task_id=trigger_id,
            connector_instance_id=schedule.connector_instance_id,
            source_id=schedule.source_id,
            platform_account_id=schedule.platform_account_id,
            mode=source_mode,
            requested_limit=schedule.requested_limit,
            checkpoint_version=None,
            trigger_type=TriggerType.SCHEDULED,
            triggered_by=f"scheduler:{self.instance_key}",
            created_at=now,
        )
        run_id: UUID | None = None
        error_code: str | None = None
        error_message: str | None = None
        failed = False
        pause_reason: str | None = None
        trigger_status = ScheduleTriggerStatus.SUCCEEDED
        try:
            result = await self.runtime.execute(task)
            run_id = result.run_id
            failed = result.status not in {
                ConnectorRunStatus.SUCCEEDED,
                ConnectorRunStatus.PARTIAL,
            }
            if failed:
                trigger_status = ScheduleTriggerStatus.FAILED
                error_code = "scheduled_run_failed"
                error_message = "受控采集运行返回失败终态"
                self.recent_trigger_failures += 1
            else:
                self.recent_trigger_failures = 0
            if result.status is ConnectorRunStatus.PAUSED_RISK:
                pause_reason = "连接器触发平台风险，调度已暂停等待人工处理"
        except Exception as exc:
            failed = True
            trigger_status = ScheduleTriggerStatus.FAILED
            error_code = getattr(exc, "code", "scheduler_dispatch_failed")
            error_message = "调度触发失败，未进行自动快速重试"
            self.recent_trigger_failures += 1
            logger.warning(
                "scheduler_dispatch_failed",
                extra={"schedule_id": str(schedule.id), "error_code": error_code},
            )

        finished = datetime.now(UTC)
        reference = max(schedule.next_run_at, finished)
        next_run = calculate_next_run(
            schedule_type=schedule.schedule_type,
            interval_seconds=schedule.interval_seconds,
            cron_expression=schedule.cron_expression,
            timezone_name=schedule.timezone,
            reference=reference,
        )
        async with self.session_factory() as session:
            async with session.begin():
                await ScheduleRepository(session).complete_trigger(
                    trigger_id=trigger_id,
                    schedule_id=schedule.id,
                    owner=self.instance_key,
                    status=trigger_status,
                    next_run_at=next_run,
                    run_id=run_id,
                    error_code=error_code,
                    error_message=error_message,
                    pause_reason=pause_reason,
                    failed=failed,
                    now=finished,
                )
        return True

    async def run_forever(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self.poll_seconds)
