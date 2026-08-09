from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Float, Integer, String, case, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorRun,
    ConnectorRunStatus,
    EditorialDraftRecord,
    EditorialPackRecord,
    EditorialRiskLevel,
    EditorialScoreOverrideRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventCardRecord,
    EventRecord,
    EventSignalRecord,
    EventStatus,
    EventTrendSnapshotRecord,
    EventUnknownRecord,
    EventUnknownStatus,
    EvidenceClaimRecord,
    PlatformAccount,
    PlatformRiskEvent,
    RawSignalRecord,
    Source,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import DIMENSION_NAMES, GENERAL_V1_WEIGHTS
from packages.risk_guard.models import AccountStatus

WorkbenchSort = Literal["last_updated_at", "first_seen_at", "traffic_total"]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class WorkbenchEventPage:
    items: tuple[dict[str, Any], ...]
    page: int
    page_size: int
    total: int
    has_next: bool


@dataclass(frozen=True, slots=True)
class WorkbenchSignalPage:
    items: tuple[dict[str, Any], ...]
    page: int
    page_size: int
    total: int
    has_next: bool


class EditorialWorkbenchQueryService:
    """Read-only M5-A projection over existing M1-M4 artifacts.

    This service never calls an AI provider and never mutates business state.
    List enrichment uses a fixed number of batched queries for the selected page.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def overview(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        since = now - timedelta(hours=24)
        async with self.session_factory() as session:
            lifecycle_rows = (
                await session.execute(
                    select(EventRecord.status, func.count(EventRecord.id))
                    .where(EventRecord.merged_into_event_id.is_(None))
                    .group_by(EventRecord.status)
                )
            ).all()
            lifecycle_counts = {status.value: int(count) for status, count in lifecycle_rows}
            for status in EventStatus:
                lifecycle_counts.setdefault(status.value, 0)

            active_count = int(
                await session.scalar(
                    select(func.count(EventRecord.id)).where(
                        EventRecord.merged_into_event_id.is_(None),
                        EventRecord.status != EventStatus.RESOLVED,
                    )
                )
                or 0
            )
            recent_new = int(
                await session.scalar(
                    select(func.count(EventRecord.id)).where(EventRecord.created_at >= since)
                )
                or 0
            )
            recent_updated = int(
                await session.scalar(
                    select(func.count(EventRecord.id)).where(EventRecord.last_updated_at >= since)
                )
                or 0
            )
            evidence_events = int(
                await session.scalar(
                    select(func.count(func.distinct(EvidenceClaimRecord.event_id)))
                )
                or 0
            )
            open_unknowns = int(
                await session.scalar(
                    select(func.count(EventUnknownRecord.id)).where(
                        EventUnknownRecord.status == EventUnknownStatus.OPEN
                    )
                )
                or 0
            )
            artifact_counts = {
                "trend_snapshots": int(
                    await session.scalar(select(func.count(EventTrendSnapshotRecord.id))) or 0
                ),
                "editorial_scores": int(
                    await session.scalar(select(func.count(EditorialScoreRecord.id))) or 0
                ),
                "event_cards": int(
                    await session.scalar(select(func.count(EventCardRecord.id))) or 0
                ),
                "editorial_packs": int(
                    await session.scalar(select(func.count(EditorialPackRecord.id))) or 0
                ),
                "drafts": int(
                    await session.scalar(select(func.count(EditorialDraftRecord.id))) or 0
                ),
            }
            high_risk = int(
                await session.scalar(
                    select(func.count(EventRecord.id)).where(
                        EventRecord.merged_into_event_id.is_(None),
                        cast(_effective_risk_expression(), String).in_(["R3", "R4"]),
                    )
                )
                or 0
            )
            health = {
                "failed_runs_24h": int(
                    await session.scalar(
                        select(func.count(ConnectorRun.id)).where(
                            ConnectorRun.status == ConnectorRunStatus.FAILED,
                            ConnectorRun.created_at >= since,
                        )
                    )
                    or 0
                ),
                "paused_risk_runs_24h": int(
                    await session.scalar(
                        select(func.count(ConnectorRun.id)).where(
                            ConnectorRun.status == ConnectorRunStatus.PAUSED_RISK,
                            ConnectorRun.created_at >= since,
                        )
                    )
                    or 0
                ),
                "open_risk_events": int(
                    await session.scalar(
                        select(func.count(PlatformRiskEvent.id)).where(
                            PlatformRiskEvent.resolved_at.is_(None)
                        )
                    )
                    or 0
                ),
                "paused_accounts": int(
                    await session.scalar(
                        select(func.count(PlatformAccount.id)).where(
                            PlatformAccount.status.in_(
                                [
                                    AccountStatus.COOLDOWN,
                                    AccountStatus.REVIEW_REQUIRED,
                                    AccountStatus.RESTRICTED,
                                    AccountStatus.DISABLED,
                                ]
                            )
                        )
                    )
                    or 0
                ),
                "checkpoint_count": int(
                    await session.scalar(select(func.count(ConnectorCheckpoint.id))) or 0
                ),
            }
        return {
            "generated_at": now,
            "active_event_count": active_count,
            "lifecycle_counts": lifecycle_counts,
            "recent_new_event_count_24h": recent_new,
            "recent_updated_event_count_24h": recent_updated,
            "events_with_evidence_count": evidence_events,
            "open_unknown_count": open_unknowns,
            "high_risk_event_count": high_risk,
            "artifact_counts": artifact_counts,
            "collection_health": health,
            "production_ai_provider_validation": "NOT_TESTED",
        }

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
                await session.scalar(
                    select(func.count(EventRecord.id)).where(*filters)
                )
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

        return WorkbenchEventPage(
            items=tuple(items),
            page=page,
            page_size=page_size,
            total=total,
            has_next=page * page_size < total,
        )

    async def event_detail(self, event_id: UUID) -> dict[str, Any]:
        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            enriched = await self._enrich_event_page(session, [event])
            summary = enriched[0]

            relation_rows = (
                await session.execute(
                    select(EventSignalRecord.relation, func.count(EventSignalRecord.id))
                    .where(EventSignalRecord.event_id == event_id)
                    .group_by(EventSignalRecord.relation)
                )
            ).all()
            by_relation = {
                relation.value: int(count) for relation, count in relation_rows
            }
            summary["signal_summary"] = {
                "total": sum(by_relation.values()),
                "by_relation": by_relation,
            }
            latest_pack = (
                await session.scalars(
                    select(EditorialPackRecord)
                    .where(EditorialPackRecord.event_id == event_id)
                    .order_by(EditorialPackRecord.created_at.desc(), EditorialPackRecord.id.desc())
                    .limit(1)
                )
            ).first()
            summary["latest_pack"] = latest_pack
            chain_count = int(
                await session.scalar(
                    select(func.count(func.distinct(EditorialDraftRecord.draft_chain_id))).where(
                        EditorialDraftRecord.event_id == event_id
                    )
                )
                or 0
            )
            summary["draft_summary"] = {
                "draft_count": summary["draft_count"],
                "chain_count": chain_count,
                "latest_draft_id": summary["latest_draft_id"],
            }
            return summary

    async def list_event_signals(
        self,
        event_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> WorkbenchSignalPage:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            total = int(
                await session.scalar(
                    select(func.count(EventSignalRecord.id)).where(
                        EventSignalRecord.event_id == event_id
                    )
                )
                or 0
            )
            effective_time = func.coalesce(
                RawSignalRecord.published_at, RawSignalRecord.collected_at
            )
            rows = (
                await session.execute(
                    select(EventSignalRecord, RawSignalRecord, Source)
                    .join(
                        RawSignalRecord,
                        RawSignalRecord.id == EventSignalRecord.signal_id,
                    )
                    .join(Source, Source.id == RawSignalRecord.source_id)
                    .where(EventSignalRecord.event_id == event_id)
                    .order_by(
                        effective_time.desc(),
                        EventSignalRecord.created_at.desc(),
                        EventSignalRecord.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            items = tuple(
                {
                    "event_signal_id": link.id,
                    "signal_id": signal.id,
                    "relation": link.relation,
                    "confidence": link.confidence,
                    "attached_by": link.attached_by,
                    "platform": signal.platform,
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_type": source.source_type,
                    "author_name": signal.author_name,
                    "published_at": signal.published_at,
                    "collected_at": signal.collected_at,
                    "effective_at": signal.published_at or signal.collected_at,
                    "title": signal.title,
                    "original_url": signal.original_url,
                    "canonical_url": signal.canonical_url,
                }
                for link, signal, source in rows
            )
        return WorkbenchSignalPage(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            has_next=page * page_size < total,
        )

    async def _enrich_event_page(
        self,
        session: AsyncSession,
        events: list[EventRecord],
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        event_ids = [event.id for event in events]

        trends = list(
            (
                await session.scalars(
                    select(EventTrendSnapshotRecord)
                    .where(EventTrendSnapshotRecord.event_id.in_(event_ids))
                    .distinct(EventTrendSnapshotRecord.event_id)
                    .order_by(
                        EventTrendSnapshotRecord.event_id,
                        EventTrendSnapshotRecord.window_end_at.desc(),
                        EventTrendSnapshotRecord.created_at.desc(),
                        EventTrendSnapshotRecord.id.desc(),
                    )
                )
            ).all()
        )
        trend_by_event = {item.event_id: item for item in trends}

        scores = list(
            (
                await session.scalars(
                    select(EditorialScoreRecord)
                    .where(EditorialScoreRecord.event_id.in_(event_ids))
                    .distinct(
                        EditorialScoreRecord.event_id,
                        EditorialScoreRecord.source_type,
                    )
                    .order_by(
                        EditorialScoreRecord.event_id,
                        EditorialScoreRecord.source_type,
                        EditorialScoreRecord.created_at.desc(),
                        EditorialScoreRecord.id.desc(),
                    )
                )
            ).all()
        )
        score_by_key = {(item.event_id, item.source_type): item for item in scores}

        overrides = list(
            (
                await session.scalars(
                    select(EditorialScoreOverrideRecord)
                    .join(
                        EditorialScoreRecord,
                        EditorialScoreRecord.id
                        == EditorialScoreOverrideRecord.editorial_score_id,
                    )
                    .where(EditorialScoreRecord.event_id.in_(event_ids))
                    .order_by(
                        EditorialScoreRecord.event_id,
                        EditorialScoreOverrideRecord.created_at.asc(),
                        EditorialScoreOverrideRecord.id.asc(),
                    )
                )
            ).all()
        )
        score_event_rows = (
            await session.execute(
                select(EditorialScoreRecord.id, EditorialScoreRecord.event_id).where(
                    EditorialScoreRecord.event_id.in_(event_ids)
                )
            )
        ).all()
        score_event_by_id = {score_id: event_id for score_id, event_id in score_event_rows}
        overrides_by_event: dict[UUID, list[EditorialScoreOverrideRecord]] = {
            event_id: [] for event_id in event_ids
        }
        for item in overrides:
            event_id = score_event_by_id[item.editorial_score_id]
            overrides_by_event[event_id].append(item)

        evidence_rows = (
            await session.execute(
                select(
                    EvidenceClaimRecord.event_id,
                    EvidenceClaimRecord.verification_state,
                    func.count(EvidenceClaimRecord.id),
                )
                .where(EvidenceClaimRecord.event_id.in_(event_ids))
                .group_by(
                    EvidenceClaimRecord.event_id,
                    EvidenceClaimRecord.verification_state,
                )
            )
        ).all()
        evidence_by_event: dict[UUID, dict[str, int]] = {
            event_id: {
                "confirmed": 0,
                "investigating": 0,
                "single_source": 0,
                "disputed": 0,
                "false": 0,
            }
            for event_id in event_ids
        }
        for event_id, state, count in evidence_rows:
            evidence_by_event[event_id][state.value] = int(count)

        unknown_rows = (
            await session.execute(
                select(EventUnknownRecord.event_id, func.count(EventUnknownRecord.id))
                .where(
                    EventUnknownRecord.event_id.in_(event_ids),
                    EventUnknownRecord.status == EventUnknownStatus.OPEN,
                )
                .group_by(EventUnknownRecord.event_id)
            )
        ).all()
        open_unknown_by_event = {event_id: int(count) for event_id, count in unknown_rows}

        card_rows = (
            await session.execute(
                select(
                    EventCardRecord.event_id,
                    func.count(EventCardRecord.id),
                    func.max(EventCardRecord.created_at),
                )
                .where(EventCardRecord.event_id.in_(event_ids))
                .group_by(EventCardRecord.event_id)
            )
        ).all()
        card_counts = {event_id: int(count) for event_id, count, _created in card_rows}
        latest_cards = list(
            (
                await session.scalars(
                    select(EventCardRecord)
                    .where(EventCardRecord.event_id.in_(event_ids))
                    .distinct(EventCardRecord.event_id)
                    .order_by(
                        EventCardRecord.event_id,
                        EventCardRecord.created_at.desc(),
                        EventCardRecord.id.desc(),
                    )
                )
            ).all()
        )
        latest_card_by_event = {item.event_id: item for item in latest_cards}

        draft_rows = (
            await session.execute(
                select(
                    EditorialDraftRecord.event_id,
                    func.count(EditorialDraftRecord.id),
                    func.max(EditorialDraftRecord.created_at),
                )
                .where(EditorialDraftRecord.event_id.in_(event_ids))
                .group_by(EditorialDraftRecord.event_id)
            )
        ).all()
        draft_counts = {event_id: int(count) for event_id, count, _created in draft_rows}
        latest_drafts = list(
            (
                await session.scalars(
                    select(EditorialDraftRecord)
                    .where(EditorialDraftRecord.event_id.in_(event_ids))
                    .distinct(EditorialDraftRecord.event_id)
                    .order_by(
                        EditorialDraftRecord.event_id,
                        EditorialDraftRecord.created_at.desc(),
                        EditorialDraftRecord.id.desc(),
                    )
                )
            ).all()
        )
        latest_draft_by_event = {item.event_id: item for item in latest_drafts}

        pack_rows = list(
            (
                await session.scalars(
                    select(EditorialPackRecord)
                    .where(EditorialPackRecord.event_id.in_(event_ids))
                    .distinct(EditorialPackRecord.event_id)
                    .order_by(
                        EditorialPackRecord.event_id,
                        EditorialPackRecord.created_at.desc(),
                        EditorialPackRecord.id.desc(),
                    )
                )
            ).all()
        )
        latest_pack_by_event = {item.event_id: item for item in pack_rows}

        result: list[dict[str, Any]] = []
        for event in events:
            latest_ai = score_by_key.get((event.id, EditorialScoreSourceType.AI))
            latest_human = score_by_key.get((event.id, EditorialScoreSourceType.HUMAN))
            event_overrides = overrides_by_event[event.id]
            effective = _effective_values(latest_ai, latest_human, event_overrides)
            evidence_counts = evidence_by_event[event.id]
            evidence_total = sum(evidence_counts.values())
            latest_card = latest_card_by_event.get(event.id)
            latest_draft = latest_draft_by_event.get(event.id)
            result.append(
                {
                    "event": event,
                    "latest_trend": trend_by_event.get(event.id),
                    "latest_ai_score": latest_ai,
                    "latest_human_score": latest_human,
                    "effective_editorial": effective,
                    "human_override_applied": bool(event_overrides),
                    "applied_override_count": len(event_overrides),
                    "evidence_counts": evidence_counts,
                    "evidence_total": evidence_total,
                    "open_unknown_count": open_unknown_by_event.get(event.id, 0),
                    "card_count": card_counts.get(event.id, 0),
                    "latest_card": latest_card,
                    "latest_card_id": latest_card.id if latest_card else None,
                    "latest_pack": latest_pack_by_event.get(event.id),
                    "draft_count": draft_counts.get(event.id, 0),
                    "latest_draft_id": latest_draft.id if latest_draft else None,
                }
            )
        return result


def _base_score_scalar(field: str) -> Any:
    column = getattr(EditorialScoreRecord, field)
    return (
        select(column)
        .where(EditorialScoreRecord.event_id == EventRecord.id)
        .order_by(
            case(
                (EditorialScoreRecord.source_type == EditorialScoreSourceType.HUMAN, 0),
                else_=1,
            ),
            EditorialScoreRecord.created_at.desc(),
            EditorialScoreRecord.id.desc(),
        )
        .limit(1)
        .correlate(EventRecord)
        .scalar_subquery()
    )


def _latest_override_scalar(field: str, sql_type: Any) -> Any:
    value = cast(EditorialScoreOverrideRecord.overridden_fields[field].astext, sql_type)
    return (
        select(value)
        .join(
            EditorialScoreRecord,
            EditorialScoreRecord.id == EditorialScoreOverrideRecord.editorial_score_id,
        )
        .where(
            EditorialScoreRecord.event_id == EventRecord.id,
            EditorialScoreOverrideRecord.overridden_fields.op("?")(field),
        )
        .order_by(
            EditorialScoreOverrideRecord.created_at.desc(),
            EditorialScoreOverrideRecord.id.desc(),
        )
        .limit(1)
        .correlate(EventRecord)
        .scalar_subquery()
    )


def _effective_dimension_expression(field: str) -> Any:
    return func.coalesce(
        _latest_override_scalar(field, Integer),
        cast(_base_score_scalar(field), Integer),
    )


def _effective_risk_expression() -> Any:
    return func.coalesce(
        _latest_override_scalar("risk_level", String),
        cast(_base_score_scalar("risk_level"), String),
    )


def _effective_traffic_expression() -> Any:
    weighted: Any = None
    for name in DIMENSION_NAMES:
        part = cast(_effective_dimension_expression(name), Float) * GENERAL_V1_WEIGHTS[name]
        weighted = part if weighted is None else weighted + part
    return weighted / 100.0


def _effective_values(
    latest_ai: EditorialScoreRecord | None,
    latest_human: EditorialScoreRecord | None,
    overrides: list[EditorialScoreOverrideRecord],
) -> dict[str, Any] | None:
    base = latest_human or latest_ai
    if base is None:
        return None
    values: dict[str, Any] = {
        name: getattr(base, name)
        for name in DIMENSION_NAMES
    }
    values.update(
        {
            "risk_level": base.risk_level.value,
            "recommended_format": base.recommended_format.value,
            "model_reason": base.model_reason,
            "base_score_id": str(base.id),
            "base_source_type": base.source_type.value,
        }
    )
    for override in overrides:
        values.update(override.overridden_fields)
    values["traffic_total"] = round(
        sum(int(values[name]) * GENERAL_V1_WEIGHTS[name] for name in DIMENSION_NAMES) / 100,
        2,
    )
    return values
