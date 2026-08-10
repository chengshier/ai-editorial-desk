from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.config import get_settings
from packages.database.models import (
    CandidateRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialDraftRecord,
    EditorialRiskLevel,
    EditorialScoreRecord,
    EventRecord,
    EventStatus,
    EvidenceClaimRecord,
)
from packages.editorial.workflow_queries import EditorialWorkflowQueryService
from packages.workbench.services import (
    EditorialWorkbenchQueryService,
    SortDirection,
    WorkbenchEventPage,
    WorkbenchSort,
    _effective_risk_expression,
    _effective_traffic_expression,
)


class M5BEditorialWorkbenchQueryService(EditorialWorkbenchQueryService):
    """Read-only M5-B overlay for the frozen M5-A Workbench projection."""

    async def overview(self) -> dict[str, Any]:
        payload = await super().overview()
        timezone = get_settings().business_timezone
        business_date = payload["generated_at"].astimezone(ZoneInfo(timezone)).date()
        workflow = EditorialWorkflowQueryService(self.session_factory)
        latest_run = await workflow.latest_successful_run(
            business_date=business_date,
            timezone=timezone,
        )
        payload["candidate_workflow"] = {
            "business_date": business_date,
            "timezone": timezone,
            "run_exists": latest_run is not None,
            "latest_run": latest_run,
            "current_decision_counts": await workflow.current_decision_counts(),
        }
        return payload

    async def list_events(
        self,
        *,
        page: int,
        page_size: int,
        status: EventStatus | None = None,
        category: str | None = None,
        include_merged: bool = False,
        risk: EditorialRiskLevel | None = None,
        has_evidence: bool | None = None,
        has_score: bool | None = None,
        has_draft: bool | None = None,
        decision: EditorialDecisionType | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        q: str | None = None,
        sort_by: WorkbenchSort = "last_updated_at",
        sort_direction: SortDirection = "desc",
    ) -> WorkbenchEventPage:
        filters: list[Any] = []
        if not include_merged:
            filters.append(EventRecord.merged_into_event_id.is_(None))
        if status is not None:
            filters.append(EventRecord.status == status)
        if category:
            filters.append(EventRecord.category == category.strip())
        if risk is not None:
            filters.append(cast(_effective_risk_expression(), String) == risk.value)
        if has_evidence is not None:
            predicate = exists(
                select(EvidenceClaimRecord.id).where(
                    EvidenceClaimRecord.event_id == EventRecord.id
                )
            )
            filters.append(predicate if has_evidence else ~predicate)
        if has_score is not None:
            predicate = exists(
                select(EditorialScoreRecord.id).where(
                    EditorialScoreRecord.event_id == EventRecord.id
                )
            )
            filters.append(predicate if has_score else ~predicate)
        if has_draft is not None:
            predicate = exists(
                select(EditorialDraftRecord.id).where(
                    EditorialDraftRecord.event_id == EventRecord.id
                )
            )
            filters.append(predicate if has_draft else ~predicate)
        if decision is not None:
            filters.append(_latest_decision_scalar() == decision.value)
        if updated_from is not None:
            filters.append(EventRecord.last_updated_at >= updated_from)
        if updated_to is not None:
            filters.append(EventRecord.last_updated_at <= updated_to)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            filters.append(
                or_(
                    EventRecord.title.ilike(pattern),
                    EventRecord.summary.ilike(pattern),
                )
            )

        if sort_by == "traffic_total":
            sort_expression = _effective_traffic_expression()
        elif sort_by == "first_seen_at":
            sort_expression = EventRecord.first_seen_at
        else:
            sort_expression = EventRecord.last_updated_at
        ordering = (
            sort_expression.asc().nullslast()
            if sort_direction == "asc"
            else sort_expression.desc().nullslast()
        )

        async with self.session_factory() as session:
            total = int(
                await session.scalar(select(func.count(EventRecord.id)).where(*filters))
                or 0
            )
            events = list(
                (
                    await session.scalars(
                        select(EventRecord)
                        .where(*filters)
                        .order_by(ordering, EventRecord.id.desc())
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                ).all()
            )
            items = await self._enrich_event_page(session, events)
            await _overlay_workflow(session, items, events)

        return WorkbenchEventPage(
            items=tuple(items),
            page=page,
            page_size=page_size,
            total=total,
            has_next=page * page_size < total,
        )

    async def event_detail(self, event_id: UUID) -> dict[str, Any]:
        payload = await super().event_detail(event_id)
        summary = await EditorialWorkflowQueryService(
            self.session_factory
        ).event_workflow_summary(event_id)
        payload.update(summary)
        return payload


def _latest_decision_scalar() -> Any:
    return (
        select(EditorialDecisionRecord.decision)
        .where(EditorialDecisionRecord.event_id == EventRecord.id)
        .order_by(
            EditorialDecisionRecord.created_at.desc(),
            EditorialDecisionRecord.id.desc(),
        )
        .limit(1)
        .correlate(EventRecord)
        .scalar_subquery()
    )


async def _overlay_workflow(
    session: AsyncSession,
    items: list[dict[str, Any]],
    events: list[EventRecord],
) -> None:
    if not events:
        return
    event_ids = [event.id for event in events]
    decisions = list(
        (
            await session.scalars(
                select(EditorialDecisionRecord)
                .where(EditorialDecisionRecord.event_id.in_(event_ids))
                .distinct(EditorialDecisionRecord.event_id)
                .order_by(
                    EditorialDecisionRecord.event_id,
                    EditorialDecisionRecord.created_at.desc(),
                    EditorialDecisionRecord.id.desc(),
                )
            )
        ).all()
    )
    decision_by_event = {item.event_id: item for item in decisions}
    candidate_rows = (
        await session.execute(
            select(DailyCandidateRecord, DailyCandidateRunRecord)
            .join(
                DailyCandidateRunRecord,
                DailyCandidateRunRecord.id == DailyCandidateRecord.run_id,
            )
            .where(
                DailyCandidateRecord.event_id.in_(event_ids),
                DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED,
            )
            .distinct(DailyCandidateRecord.event_id)
            .order_by(
                DailyCandidateRecord.event_id,
                DailyCandidateRunRecord.business_date.desc(),
                DailyCandidateRunRecord.as_of_at.desc(),
                DailyCandidateRunRecord.created_at.desc(),
                DailyCandidateRunRecord.id.desc(),
            )
        )
    ).all()
    candidate_by_event = {
        candidate.event_id: (candidate, run) for candidate, run in candidate_rows
    }
    for item in items:
        event_id = item["event"].id
        pair = candidate_by_event.get(event_id)
        item["current_editorial_decision"] = decision_by_event.get(event_id)
        item["latest_candidate"] = pair[0] if pair else None
        item["latest_candidate_run"] = pair[1] if pair else None
