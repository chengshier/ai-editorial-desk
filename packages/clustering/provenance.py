from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    ClusteringProcessingMode,
    ClusteringProcessingRunRecord,
    ClusteringProcessingStatus,
    EventAssignmentAction,
    EventAssignmentRecord,
    EventSignalAttachedBy,
)
from packages.database.types import utc_now


class ClusteringProcessingRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        mode: ClusteringProcessingMode,
        algorithm_version: str,
        dataset_version: str | None,
        actor: str | None,
        requested_count: int,
        config_snapshot: dict[str, object],
    ) -> ClusteringProcessingRunRecord:
        record = ClusteringProcessingRunRecord(
            mode=mode,
            status=ClusteringProcessingStatus.RUNNING,
            algorithm_version=algorithm_version,
            dataset_version=dataset_version,
            actor=actor,
            started_at=utc_now(),
            requested_count=requested_count,
            processed_count=0,
            counters={},
            config_snapshot=config_snapshot,
            error_summary=None,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def finish(
        self,
        record: ClusteringProcessingRunRecord,
        *,
        status: ClusteringProcessingStatus,
        processed_count: int,
        counters: dict[str, object],
        error_summary: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        record.status = status
        record.processed_count = processed_count
        record.counters = counters
        record.error_summary = error_summary
        record.finished_at = finished_at or utc_now()
        await self.session.flush()


class EventAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        signal_id: UUID,
        event_id: UUID,
        action: EventAssignmentAction,
        attached_by: EventSignalAttachedBy,
        algorithm_version: str,
        match_decision_id: UUID | None = None,
        processing_run_id: UUID | None = None,
        previous_event_id: UUID | None = None,
    ) -> EventAssignmentRecord:
        record = EventAssignmentRecord(
            signal_id=signal_id,
            event_id=event_id,
            action=action,
            attached_by=attached_by,
            algorithm_version=algorithm_version,
            match_decision_id=match_decision_id,
            processing_run_id=processing_run_id,
            previous_event_id=previous_event_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def latest_for_signal(self, signal_id: UUID) -> EventAssignmentRecord | None:
        statement = (
            select(EventAssignmentRecord)
            .where(EventAssignmentRecord.signal_id == signal_id)
            .order_by(EventAssignmentRecord.created_at.desc(), EventAssignmentRecord.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(statement)).first()

    async def list_for_signal(self, signal_id: UUID) -> list[EventAssignmentRecord]:
        statement = (
            select(EventAssignmentRecord)
            .where(EventAssignmentRecord.signal_id == signal_id)
            .order_by(EventAssignmentRecord.created_at.asc(), EventAssignmentRecord.id.asc())
        )
        return list((await self.session.scalars(statement)).all())
