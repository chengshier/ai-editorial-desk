from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    CollectionSchedule,
    CollectionScheduleTrigger,
    ScheduleTriggerStatus,
    SchedulerInstance,
)
from packages.database.types import utc_now


class ScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, schedule_id: UUID) -> CollectionSchedule | None:
        return await self.session.get(CollectionSchedule, schedule_id)

    async def due_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        statement = (
            select(CollectionSchedule.id)
            .where(CollectionSchedule.enabled.is_(True), CollectionSchedule.next_run_at <= now)
            .order_by(CollectionSchedule.next_run_at.asc(), CollectionSchedule.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def claim_schedule(
        self,
        *,
        schedule_id: UUID,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> CollectionSchedule | None:
        statement = (
            update(CollectionSchedule)
            .where(
                CollectionSchedule.id == schedule_id,
                CollectionSchedule.enabled.is_(True),
                CollectionSchedule.next_run_at <= now,
                or_(
                    CollectionSchedule.lease_expires_at.is_(None),
                    CollectionSchedule.lease_expires_at < now,
                ),
            )
            .values(lease_owner=owner, lease_expires_at=lease_expires_at, updated_at=utc_now())
            .returning(CollectionSchedule)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def claim_slot(
        self,
        *,
        schedule: CollectionSchedule,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> CollectionScheduleTrigger | None:
        trigger_id = uuid4()
        await self.session.execute(
            insert(CollectionScheduleTrigger)
            .values(
                id=trigger_id,
                schedule_id=schedule.id,
                scheduled_for_at=schedule.next_run_at,
                status=ScheduleTriggerStatus.CLAIMED,
                lease_owner=owner,
                lease_expires_at=lease_expires_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_collection_schedule_triggers_slot")
        )
        trigger = await self.session.scalar(
            select(CollectionScheduleTrigger).where(
                CollectionScheduleTrigger.schedule_id == schedule.id,
                CollectionScheduleTrigger.scheduled_for_at == schedule.next_run_at,
            )
        )
        if trigger is None:
            return None
        if trigger.id == trigger_id:
            return trigger
        if (
            trigger.status is ScheduleTriggerStatus.CLAIMED
            and (trigger.lease_expires_at is None or trigger.lease_expires_at < now)
        ):
            statement = (
                update(CollectionScheduleTrigger)
                .where(
                    CollectionScheduleTrigger.id == trigger.id,
                    CollectionScheduleTrigger.status == ScheduleTriggerStatus.CLAIMED,
                    or_(
                        CollectionScheduleTrigger.lease_expires_at.is_(None),
                        CollectionScheduleTrigger.lease_expires_at < now,
                    ),
                )
                .values(
                    lease_owner=owner,
                    lease_expires_at=lease_expires_at,
                    updated_at=utc_now(),
                )
                .returning(CollectionScheduleTrigger)
            )
            return (await self.session.execute(statement)).scalar_one_or_none()
        return trigger

    async def mark_trigger_running(
        self,
        *,
        trigger_id: UUID,
        owner: str,
        lease_expires_at: datetime,
    ) -> CollectionScheduleTrigger | None:
        statement = (
            update(CollectionScheduleTrigger)
            .where(
                CollectionScheduleTrigger.id == trigger_id,
                CollectionScheduleTrigger.status == ScheduleTriggerStatus.CLAIMED,
                CollectionScheduleTrigger.lease_owner == owner,
            )
            .values(
                status=ScheduleTriggerStatus.RUNNING,
                lease_expires_at=lease_expires_at,
                updated_at=utc_now(),
            )
            .returning(CollectionScheduleTrigger)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def complete_trigger(
        self,
        *,
        trigger_id: UUID,
        schedule_id: UUID,
        owner: str,
        status: ScheduleTriggerStatus,
        next_run_at: datetime,
        run_id: UUID | None,
        error_code: str | None,
        error_message: str | None,
        pause_reason: str | None,
        failed: bool,
        now: datetime,
    ) -> None:
        await self.session.execute(
            update(CollectionScheduleTrigger)
            .where(
                CollectionScheduleTrigger.id == trigger_id,
                CollectionScheduleTrigger.lease_owner == owner,
            )
            .values(
                status=status,
                lease_owner=None,
                lease_expires_at=None,
                run_id=run_id,
                error_code=error_code,
                error_message=error_message,
                updated_at=now,
            )
        )
        values: dict[str, object] = {
            "next_run_at": next_run_at,
            "last_triggered_at": now,
            "last_run_id": run_id,
            "lease_owner": None,
            "lease_expires_at": None,
            "paused_reason": pause_reason,
            "updated_at": now,
        }
        if failed:
            values["consecutive_failures"] = CollectionSchedule.consecutive_failures + 1
        else:
            values["consecutive_failures"] = 0
        if pause_reason is not None:
            values["enabled"] = False
        await self.session.execute(
            update(CollectionSchedule)
            .where(CollectionSchedule.id == schedule_id, CollectionSchedule.lease_owner == owner)
            .values(**values)
        )

    async def pause_stale_running_slot(
        self,
        *,
        schedule_id: UUID,
        trigger_id: UUID,
        owner: str,
        now: datetime,
    ) -> None:
        reason = "上次调度执行租约已过期，需要人工检查 stale Run"
        await self.session.execute(
            update(CollectionScheduleTrigger)
            .where(CollectionScheduleTrigger.id == trigger_id)
            .values(
                status=ScheduleTriggerStatus.PAUSED_REVIEW,
                lease_owner=None,
                lease_expires_at=None,
                error_code="stale_scheduler_execution",
                error_message=reason,
                updated_at=now,
            )
        )
        await self.session.execute(
            update(CollectionSchedule)
            .where(CollectionSchedule.id == schedule_id, CollectionSchedule.lease_owner == owner)
            .values(
                enabled=False,
                lease_owner=None,
                lease_expires_at=None,
                paused_reason=reason,
                updated_at=now,
            )
        )

    async def release_schedule(self, *, schedule_id: UUID, owner: str) -> None:
        await self.session.execute(
            update(CollectionSchedule)
            .where(CollectionSchedule.id == schedule_id, CollectionSchedule.lease_owner == owner)
            .values(lease_owner=None, lease_expires_at=None, updated_at=utc_now())
        )

    async def heartbeat(
        self,
        *,
        instance_key: str,
        started_at: datetime,
        now: datetime,
        recent_trigger_failures: int,
    ) -> None:
        await self.session.execute(
            insert(SchedulerInstance)
            .values(
                id=uuid4(),
                instance_key=instance_key,
                started_at=started_at,
                last_heartbeat=now,
                recent_trigger_failures=recent_trigger_failures,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_scheduler_instances_instance_key",
                set_={
                    "last_heartbeat": now,
                    "recent_trigger_failures": recent_trigger_failures,
                    "updated_at": now,
                },
            )
        )

    async def due_count(self, *, now: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(CollectionSchedule)
                .where(CollectionSchedule.enabled.is_(True), CollectionSchedule.next_run_at <= now)
            )
            or 0
        )

    async def active_lease_count(self, *, now: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(CollectionSchedule)
                .where(CollectionSchedule.lease_expires_at > now)
            )
            or 0
        )
