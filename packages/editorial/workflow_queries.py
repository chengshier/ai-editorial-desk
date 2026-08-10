from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.common.config import get_settings
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    CandidateGroup,
    CandidateRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialRiskLevel,
    EventRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.candidates import latest_decisions


@dataclass(frozen=True, slots=True)
class CandidateListResult:
    run: DailyCandidateRunRecord
    items: tuple[dict[str, object], ...]
    total: int
    top_n: int


class EditorialWorkflowQueryService:
    """Read-only M5-B workflow projection with batched decision overlays."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def list_runs(
        self,
        *,
        business_date: date | None = None,
        timezone: str | None = None,
        limit: int = 50,
    ) -> tuple[DailyCandidateRunRecord, ...]:
        statement = select(DailyCandidateRunRecord)
        if business_date is not None:
            statement = statement.where(DailyCandidateRunRecord.business_date == business_date)
        if timezone is not None:
            statement = statement.where(DailyCandidateRunRecord.timezone == timezone)
        statement = statement.order_by(
            DailyCandidateRunRecord.business_date.desc(),
            DailyCandidateRunRecord.as_of_at.desc(),
            DailyCandidateRunRecord.created_at.desc(),
            DailyCandidateRunRecord.id.desc(),
        ).limit(max(1, min(limit, 100)))
        async with self.session_factory() as session:
            return tuple((await session.scalars(statement)).all())

    async def get_run(self, run_id: UUID) -> DailyCandidateRunRecord:
        async with self.session_factory() as session:
            run = await session.get(DailyCandidateRunRecord, run_id)
            if run is None:
                raise ResourceNotFoundError("Daily Candidate Run 不存在")
            return run

    async def latest_successful_run(
        self,
        *,
        business_date: date | None = None,
        timezone: str | None = None,
    ) -> DailyCandidateRunRecord | None:
        timezone_name = timezone or get_settings().business_timezone
        statement = select(DailyCandidateRunRecord).where(
            DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
            DailyCandidateRunRecord.timezone == timezone_name,
        )
        if business_date is not None:
            statement = statement.where(DailyCandidateRunRecord.business_date == business_date)
        statement = statement.order_by(
            DailyCandidateRunRecord.business_date.desc(),
            DailyCandidateRunRecord.as_of_at.desc(),
            DailyCandidateRunRecord.created_at.desc(),
            DailyCandidateRunRecord.id.desc(),
        ).limit(1)
        async with self.session_factory() as session:
            return (await session.scalars(statement)).first()

    async def list_candidates(
        self,
        *,
        run_id: UUID | None = None,
        business_date: date | None = None,
        timezone: str | None = None,
        top_n: int = 20,
        candidate_group: CandidateGroup | None = None,
        decision: EditorialDecisionType | None = None,
        risk: EditorialRiskLevel | None = None,
        category: str | None = None,
    ) -> CandidateListResult:
        top_n = max(1, min(top_n, 100))
        async with self.session_factory() as session:
            run = await _resolve_run(
                session,
                run_id=run_id,
                business_date=business_date,
                timezone=timezone,
            )
            statement = select(DailyCandidateRecord).where(
                DailyCandidateRecord.run_id == run.id,
                DailyCandidateRecord.rank <= top_n,
            )
            if candidate_group is not None:
                statement = statement.where(
                    DailyCandidateRecord.candidate_group == candidate_group
                )
            if risk is not None:
                statement = statement.where(DailyCandidateRecord.effective_risk_level == risk)
            if category is not None and category.strip():
                statement = statement.where(
                    DailyCandidateRecord.category_snapshot == category.strip()
                )
            candidates = list(
                (
                    await session.scalars(
                        statement.order_by(DailyCandidateRecord.rank.asc())
                    )
                ).all()
            )
            event_ids = [item.event_id for item in candidates]
            events = {
                item.id: item
                for item in (
                    (
                        await session.scalars(
                            select(EventRecord).where(EventRecord.id.in_(event_ids))
                        )
                    ).all()
                    if event_ids
                    else []
                )
            }
            decisions = await latest_decisions(session, event_ids)
            items: list[dict[str, object]] = []
            for candidate in candidates:
                current = decisions.get(candidate.event_id)
                if decision is not None and (
                    current is None or current.decision is not decision
                ):
                    continue
                event = events.get(candidate.event_id)
                shallow_stale = bool(
                    event is not None
                    and (
                        event.merged_into_event_id is not None
                        or event.last_updated_at != candidate.event_last_updated_at_snapshot
                    )
                )
                items.append(
                    {
                        "candidate": candidate,
                        "current_event_status": event.status if event is not None else None,
                        "merged_into_event_id": (
                            event.merged_into_event_id if event is not None else None
                        ),
                        "current_editorial_decision": current,
                        "stale_indicator": True if shallow_stale else None,
                    }
                )
            return CandidateListResult(
                run=run,
                items=tuple(items),
                total=len(items),
                top_n=top_n,
            )

    async def latest_candidate_for_event(
        self,
        event_id: UUID,
    ) -> tuple[DailyCandidateRecord, DailyCandidateRunRecord] | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(DailyCandidateRecord, DailyCandidateRunRecord)
                    .join(
                        DailyCandidateRunRecord,
                        DailyCandidateRunRecord.id == DailyCandidateRecord.run_id,
                    )
                    .where(
                        DailyCandidateRecord.event_id == event_id,
                        DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
                    )
                    .order_by(
                        DailyCandidateRunRecord.business_date.desc(),
                        DailyCandidateRunRecord.as_of_at.desc(),
                        DailyCandidateRunRecord.created_at.desc(),
                        DailyCandidateRecord.rank.asc(),
                    )
                    .limit(1)
                )
            ).first()
            return (row[0], row[1]) if row is not None else None

    async def decision_history(
        self,
        event_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            rows = (
                await session.execute(
                    select(
                        EditorialDecisionRecord,
                        DailyCandidateRecord,
                        DailyCandidateRunRecord,
                    )
                    .outerjoin(
                        DailyCandidateRecord,
                        DailyCandidateRecord.id == EditorialDecisionRecord.candidate_id,
                    )
                    .outerjoin(
                        DailyCandidateRunRecord,
                        DailyCandidateRunRecord.id == DailyCandidateRecord.run_id,
                    )
                    .where(EditorialDecisionRecord.event_id == event_id)
                    .order_by(
                        EditorialDecisionRecord.created_at.desc(),
                        EditorialDecisionRecord.id.desc(),
                    )
                )
            ).all()
            return tuple(
                {
                    "decision": record,
                    "candidate_rank": candidate.rank if candidate is not None else None,
                    "candidate_run_id": run.id if run is not None else None,
                    "candidate_business_date": run.business_date if run is not None else None,
                    "candidate_as_of_at": run.as_of_at if run is not None else None,
                }
                for record, candidate, run in rows
            )

    async def event_workflow_summary(self, event_id: UUID) -> dict[str, object]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            current = (
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
            candidate_row = (
                await session.execute(
                    select(DailyCandidateRecord, DailyCandidateRunRecord)
                    .join(
                        DailyCandidateRunRecord,
                        DailyCandidateRunRecord.id == DailyCandidateRecord.run_id,
                    )
                    .where(
                        DailyCandidateRecord.event_id == event_id,
                        DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
                    )
                    .order_by(
                        DailyCandidateRunRecord.business_date.desc(),
                        DailyCandidateRunRecord.as_of_at.desc(),
                        DailyCandidateRunRecord.created_at.desc(),
                    )
                    .limit(1)
                )
            ).first()
            return {
                "current_editorial_decision": current,
                "latest_candidate": candidate_row[0] if candidate_row else None,
                "latest_candidate_run": candidate_row[1] if candidate_row else None,
            }

    async def current_decision_counts(self) -> dict[str, int]:
        async with self.session_factory() as session:
            latest = (
                select(
                    EditorialDecisionRecord.event_id.label("event_id"),
                    EditorialDecisionRecord.decision.label("decision"),
                    func.row_number()
                    .over(
                        partition_by=EditorialDecisionRecord.event_id,
                        order_by=(
                            EditorialDecisionRecord.created_at.desc(),
                            EditorialDecisionRecord.id.desc(),
                        ),
                    )
                    .label("rn"),
                )
            ).subquery()
            rows = (
                await session.execute(
                    select(latest.c.decision, func.count())
                    .where(latest.c.rn == 1)
                    .group_by(latest.c.decision)
                )
            ).all()
            result = {item.value: 0 for item in EditorialDecisionType}
            for decision, count in rows:
                value = decision.value if hasattr(decision, "value") else str(decision)
                result[value] = int(count)
            return result


async def _resolve_run(
    session: AsyncSession,
    *,
    run_id: UUID | None,
    business_date: date | None,
    timezone: str | None,
) -> DailyCandidateRunRecord:
    if run_id is not None:
        run = await session.get(DailyCandidateRunRecord, run_id)
        if run is None:
            raise ResourceNotFoundError("Daily Candidate Run 不存在")
        return run
    timezone_name = timezone or get_settings().business_timezone
    statement = select(DailyCandidateRunRecord).where(
        DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
        DailyCandidateRunRecord.timezone == timezone_name,
    )
    if business_date is not None:
        statement = statement.where(DailyCandidateRunRecord.business_date == business_date)
    run = (
        await session.scalars(
            statement.order_by(
                DailyCandidateRunRecord.business_date.desc(),
                DailyCandidateRunRecord.as_of_at.desc(),
                DailyCandidateRunRecord.created_at.desc(),
                DailyCandidateRunRecord.id.desc(),
            ).limit(1)
        )
    ).first()
    if run is None:
        raise ResourceNotFoundError("Daily Candidate Run 不存在")
    return run
