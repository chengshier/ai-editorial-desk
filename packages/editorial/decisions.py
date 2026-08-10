from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    CandidateRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialRiskLevel,
    EventRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.candidates import (
    CANDIDATE_RANKING_VERSION,
    DailyCandidateService,
)
from packages.editorial.domain import normalize_text
from packages.editorial.workflow_errors import (
    CandidateRunStaleError,
    CandidateValidationError,
    EditorialDecisionConflictError,
    RiskAcknowledgementRequiredError,
    StaleCandidateContextError,
    WorkflowEventMergedError,
)


@dataclass(frozen=True, slots=True)
class EditorialDecisionOutcome:
    decision: EditorialDecisionRecord
    reused: bool


class EditorialDecisionService:
    """Append-only decisions serialized by the Event row in PostgreSQL."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.candidates = DailyCandidateService(self.session_factory)

    async def decide(
        self,
        *,
        event_id: UUID,
        decision: EditorialDecisionType,
        actor: str,
        reason: str,
        candidate_id: UUID | None = None,
        expected_previous_decision_id: UUID | None = None,
        risk_acknowledged: bool = False,
        confirmation: bool = False,
    ) -> EditorialDecisionOutcome:
        normalized_actor = normalize_text(actor)
        normalized_reason = normalize_text(reason)
        if not normalized_actor or not normalized_reason:
            raise CandidateValidationError(
                "Editorial Decision 必须包含 Actor 与 reason"
            )

        async with self.session_factory() as session:
            async with session.begin():
                event = await _lock_event(session, event_id)
                if event.merged_into_event_id is not None:
                    raise WorkflowEventMergedError(event.merged_into_event_id)

                current = await _latest_decision(session, event_id)
                candidate: DailyCandidateRecord | None = None
                run: DailyCandidateRunRecord | None = None
                if candidate_id is not None:
                    candidate = await session.get(DailyCandidateRecord, candidate_id)
                    if candidate is None or candidate.event_id != event_id:
                        raise ResourceNotFoundError("Daily Candidate 不存在")
                    run = await session.get(DailyCandidateRunRecord, candidate.run_id)
                    if (
                        run is None
                        or run.status is not CandidateRunStatus.SUCCEEDED
                    ):
                        raise ResourceNotFoundError("Daily Candidate Run 不存在")

                ranking_version = (
                    run.ranking_version
                    if run is not None
                    else CANDIDATE_RANKING_VERSION
                )
                context = await self.candidates.current_context(
                    event_id,
                    ranking_version=ranking_version,
                    session=session,
                )

                if (
                    candidate is not None
                    and candidate.candidate_context_hash
                    != context.candidate_context_hash
                ):
                    raise StaleCandidateContextError(
                        "Candidate 上下文已变化，请刷新或重新生成 Candidate Pool",
                        details={
                            "candidate_id": str(candidate.id),
                            "candidate_context_hash": candidate.candidate_context_hash,
                            "current_context_hash": context.candidate_context_hash,
                        },
                    )

                if candidate is not None and _same_candidate_retry(
                    current=current,
                    candidate=candidate,
                    requested_decision=decision,
                    actor=normalized_actor,
                    reason=normalized_reason,
                    risk_acknowledged=risk_acknowledged,
                    context_hash=context.candidate_context_hash,
                ):
                    assert current is not None
                    return EditorialDecisionOutcome(
                        decision=current,
                        reused=True,
                    )

                if candidate is None and _same_direct_retry(
                    current=current,
                    requested_decision=decision,
                    actor=normalized_actor,
                    reason=normalized_reason,
                    risk_acknowledged=risk_acknowledged,
                    context_hash=context.candidate_context_hash,
                ):
                    assert current is not None
                    return EditorialDecisionOutcome(
                        decision=current,
                        reused=True,
                    )

                if run is not None:
                    latest_run = await _latest_successful_run_for_day(
                        session,
                        business_date=run.business_date,
                        timezone=run.timezone,
                    )
                    if latest_run is None or latest_run.id != run.id:
                        raise CandidateRunStaleError(
                            "旧 Candidate Run 只读，不能直接创建新的 Editorial Decision",
                            details={
                                "candidate_run_id": str(run.id),
                                "latest_run_id": (
                                    str(latest_run.id) if latest_run else None
                                ),
                            },
                        )

                current_id = current.id if current is not None else None
                if expected_previous_decision_id != current_id:
                    raise EditorialDecisionConflictError(
                        "Editorial Decision 已被其他编辑更新，请刷新后重试",
                        details={
                            "expected_previous_decision_id": (
                                str(expected_previous_decision_id)
                                if expected_previous_decision_id is not None
                                else None
                            ),
                            "current_decision_id": (
                                str(current_id) if current_id else None
                            ),
                            "current_decision": (
                                current.decision.value if current else None
                            ),
                        },
                    )

                needs_confirmation = decision is EditorialDecisionType.ARCHIVE or (
                    current is not None
                    and current.decision is EditorialDecisionType.ARCHIVE
                )
                if needs_confirmation and not confirmation:
                    raise CandidateValidationError(
                        "Archive 或 Archive 恢复必须显式 confirmation"
                    )

                risk = EditorialRiskLevel(str(context.effective_values["risk_level"]))
                if (
                    decision is EditorialDecisionType.ADOPT
                    and risk in (EditorialRiskLevel.R3, EditorialRiskLevel.R4)
                    and not risk_acknowledged
                ):
                    raise RiskAcknowledgementRequiredError(
                        "R3/R4 Event Adopt 必须明确确认风险",
                        details={"risk_level": risk.value},
                    )

                record = EditorialDecisionRecord(
                    event_id=event_id,
                    candidate_id=candidate.id if candidate is not None else None,
                    decision=decision,
                    previous_decision_id=current.id if current is not None else None,
                    candidate_context_hash=context.candidate_context_hash,
                    risk_acknowledged=risk_acknowledged,
                    risk_level_snapshot=risk,
                    effective_traffic_total_snapshot=float(
                        context.effective_values["traffic_total"]
                    ),
                    reason=normalized_reason,
                    actor=normalized_actor,
                )
                session.add(record)
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="editorial_decision",
                    entity_id=record.id,
                    action="append",
                    actor=normalized_actor,
                    before_data={
                        "effective_decision_id": str(current.id) if current else None,
                        "effective_decision": (
                            current.decision.value if current else None
                        ),
                    },
                    after_data={
                        "event_id": str(event_id),
                        "candidate_id": str(candidate.id) if candidate else None,
                        "candidate_run_id": str(run.id) if run else None,
                        "candidate_rank": candidate.rank if candidate else None,
                        "decision": decision.value,
                        "reason": normalized_reason,
                        "risk_acknowledged": risk_acknowledged,
                        "risk_level": risk.value,
                        "candidate_context_hash": context.candidate_context_hash,
                    },
                )
                return EditorialDecisionOutcome(decision=record, reused=False)

    async def history(
        self,
        event_id: UUID,
    ) -> tuple[EditorialDecisionRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(
                (
                    await session.scalars(
                        select(EditorialDecisionRecord)
                        .where(EditorialDecisionRecord.event_id == event_id)
                        .order_by(
                            EditorialDecisionRecord.created_at.desc(),
                            EditorialDecisionRecord.id.desc(),
                        )
                    )
                ).all()
            )

    async def current(self, event_id: UUID) -> EditorialDecisionRecord | None:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return await _latest_decision(session, event_id)


async def _lock_event(session: AsyncSession, event_id: UUID) -> EventRecord:
    event = (
        await session.scalars(
            select(EventRecord).where(EventRecord.id == event_id).with_for_update()
        )
    ).first()
    if event is None:
        raise ResourceNotFoundError("事件不存在")
    return event


async def _latest_decision(
    session: AsyncSession,
    event_id: UUID,
) -> EditorialDecisionRecord | None:
    return (
        await session.scalars(
            select(EditorialDecisionRecord)
            .where(EditorialDecisionRecord.event_id == event_id)
            .order_by(
                EditorialDecisionRecord.created_at.desc(),
                EditorialDecisionRecord.id.desc(),
            )
            .limit(1)
        )
    ).first()


async def _latest_successful_run_for_day(
    session: AsyncSession,
    *,
    business_date: date,
    timezone: str,
) -> DailyCandidateRunRecord | None:
    return (
        await session.scalars(
            select(DailyCandidateRunRecord)
            .where(
                DailyCandidateRunRecord.business_date == business_date,
                DailyCandidateRunRecord.timezone == timezone,
                DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
            )
            .order_by(
                DailyCandidateRunRecord.as_of_at.desc(),
                DailyCandidateRunRecord.created_at.desc(),
                DailyCandidateRunRecord.id.desc(),
            )
            .limit(1)
        )
    ).first()


def _same_candidate_retry(
    *,
    current: EditorialDecisionRecord | None,
    candidate: DailyCandidateRecord,
    requested_decision: EditorialDecisionType,
    actor: str,
    reason: str,
    risk_acknowledged: bool,
    context_hash: str,
) -> bool:
    return bool(
        current is not None
        and current.candidate_id == candidate.id
        and current.candidate_context_hash == candidate.candidate_context_hash
        and current.candidate_context_hash == context_hash
        and current.decision is requested_decision
        and current.actor == actor
        and current.reason == reason
        and current.risk_acknowledged == risk_acknowledged
    )


def _same_direct_retry(
    *,
    current: EditorialDecisionRecord | None,
    requested_decision: EditorialDecisionType,
    actor: str,
    reason: str,
    risk_acknowledged: bool,
    context_hash: str,
) -> bool:
    return bool(
        current is not None
        and current.candidate_id is None
        and current.candidate_context_hash == context_hash
        and current.decision is requested_decision
        and current.actor == actor
        and current.reason == reason
        and current.risk_acknowledged == risk_acknowledged
    )
