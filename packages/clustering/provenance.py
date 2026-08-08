from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    ClusteringProcessingMode,
    ClusteringProcessingRunRecord,
    ClusteringProcessingStatus,
    ConfigurationChangeLog,
    EventAssignmentAction,
    EventAssignmentRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
)
from packages.database.types import utc_now


@dataclass(frozen=True, slots=True)
class AssignmentProvenance:
    signal_id: UUID
    event_id: UUID
    attached_by: EventSignalAttachedBy
    assigned_at: datetime
    source: str
    action: str
    algorithm_version: str | None
    match_decision_id: UUID | None
    processing_run_id: UUID | None
    audit_log_id: UUID | None
    evidence: dict[str, object]


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


class AssignmentProvenanceService:
    """Resolve current membership provenance without guessing from unrelated audit rows."""

    AUTO_AUDIT_ACTIONS = ("cluster_attach_signal", "cluster_create_event")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assignments = EventAssignmentRepository(session)

    async def current(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
    ) -> AssignmentProvenance | None:
        membership = await self.session.scalar(
            select(EventSignalRecord).where(
                EventSignalRecord.event_id == event_id,
                EventSignalRecord.signal_id == signal_id,
            )
        )
        if membership is None:
            return None
        assignment = await self._latest_assignment(event_id=event_id, signal_id=signal_id)
        if assignment is not None:
            return AssignmentProvenance(
                signal_id=signal_id,
                event_id=event_id,
                attached_by=assignment.attached_by,
                assigned_at=assignment.created_at,
                source="event_assignment_record",
                action=assignment.action.value,
                algorithm_version=assignment.algorithm_version,
                match_decision_id=assignment.match_decision_id,
                processing_run_id=assignment.processing_run_id,
                audit_log_id=None,
                evidence={
                    "previous_event_id": (
                        str(assignment.previous_event_id)
                        if assignment.previous_event_id is not None
                        else None
                    )
                },
            )
        if membership.attached_by is EventSignalAttachedBy.HUMAN:
            return AssignmentProvenance(
                signal_id=signal_id,
                event_id=event_id,
                attached_by=membership.attached_by,
                assigned_at=membership.created_at,
                source="human_membership",
                action="human_attach",
                algorithm_version=None,
                match_decision_id=None,
                processing_run_id=None,
                audit_log_id=None,
                evidence={
                    "relation": membership.relation.value,
                    "confidence": membership.confidence,
                },
            )
        audit = await self._automatic_assignment_audit(
            event_id=event_id,
            signal_id=signal_id,
        )
        if audit is None:
            return None
        after_data = audit.after_data
        algorithm_version = after_data.get("algorithm_version")
        return AssignmentProvenance(
            signal_id=signal_id,
            event_id=event_id,
            attached_by=membership.attached_by,
            assigned_at=audit.created_at,
            source="configuration_change_log",
            action=audit.action,
            algorithm_version=(
                str(algorithm_version) if algorithm_version is not None else None
            ),
            match_decision_id=None,
            processing_run_id=None,
            audit_log_id=audit.id,
            evidence={
                key: value
                for key, value in after_data.items()
                if key
                in {
                    "relation",
                    "match_decision",
                    "match_score",
                    "attached_by",
                    "algorithm_version",
                }
            },
        )

    async def _latest_assignment(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
    ) -> EventAssignmentRecord | None:
        statement = (
            select(EventAssignmentRecord)
            .where(
                EventAssignmentRecord.signal_id == signal_id,
                EventAssignmentRecord.event_id == event_id,
            )
            .order_by(EventAssignmentRecord.created_at.desc(), EventAssignmentRecord.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(statement)).first()

    async def _automatic_assignment_audit(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
    ) -> ConfigurationChangeLog | None:
        signal_text = func.jsonb_extract_path_text(
            ConfigurationChangeLog.after_data,
            "signal_id",
        )
        statement = (
            select(ConfigurationChangeLog)
            .where(
                ConfigurationChangeLog.entity_type == "event",
                ConfigurationChangeLog.entity_id == event_id,
                ConfigurationChangeLog.action.in_(self.AUTO_AUDIT_ACTIONS),
                signal_text == str(signal_id),
            )
            .order_by(
                ConfigurationChangeLog.created_at.desc(),
                ConfigurationChangeLog.id.desc(),
            )
            .limit(1)
        )
        return (await self.session.scalars(statement)).first()
