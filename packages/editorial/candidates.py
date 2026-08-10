from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.common.config import get_settings
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    CandidateGroup,
    CandidateRunMode,
    CandidateRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialDraftRecord,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EventCardRecord,
    EventRecord,
    EventStatus,
    EventTrendSnapshotRecord,
    EventUnknownRecord,
    EventUnknownStatus,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.editorial.domain import normalize_text, stable_hash
from packages.editorial.services import EditorialScoringService
from packages.editorial.workflow_errors import CandidateValidationError

CANDIDATE_RANKING_VERSION = "candidate-ranking-v1"
DEFAULT_LOOKBACK_HOURS = 24
MIN_LOOKBACK_HOURS = 1
MAX_LOOKBACK_HOURS = 168
DEFAULT_CANDIDATE_LIMIT = 20
MAX_CANDIDATE_LIMIT = 100

SKIP_NO_EDITORIAL_ASSESSMENT = "NO_EDITORIAL_ASSESSMENT"
SKIP_MERGED_EVENT = "MERGED_EVENT"
SKIP_RESOLVED_EVENT = "RESOLVED_EVENT"
SKIP_EDITORIALLY_ARCHIVED = "EDITORIALLY_ARCHIVED"
SKIP_OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
SKIP_CODES = (
    SKIP_NO_EDITORIAL_ASSESSMENT,
    SKIP_MERGED_EVENT,
    SKIP_RESOLVED_EVENT,
    SKIP_EDITORIALLY_ARCHIVED,
    SKIP_OUTSIDE_WINDOW,
)


@dataclass(frozen=True, slots=True)
class CandidateGenerationRequest:
    business_date: date | None = None
    timezone: str | None = None
    as_of_at: datetime | None = None
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    requested_limit: int = DEFAULT_CANDIDATE_LIMIT
    include_resolved: bool = False
    include_archived: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedCandidateGenerationRequest:
    business_date: date
    timezone: str
    as_of_at: datetime
    lookback_hours: int
    requested_limit: int
    include_resolved: bool
    include_archived: bool
    window_start_at: datetime
    window_end_at: datetime


@dataclass(frozen=True, slots=True)
class CandidatePreviewItem:
    event_id: UUID
    rank: int
    candidate_group: CandidateGroup
    event_title_snapshot: str
    category_snapshot: str | None
    event_status_snapshot: EventStatus
    event_last_updated_at_snapshot: datetime
    source_count_snapshot: int
    platform_count_snapshot: int
    trend_snapshot_id: UUID | None
    base_editorial_score_id: UUID
    effective_assessment_hash: str
    effective_traffic_total: float
    effective_risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    open_unknown_count: int
    evidence_summary: dict[str, int]
    ranking_components: dict[str, Any]
    card_exists_snapshot: bool
    draft_exists_snapshot: bool
    candidate_context_hash: str


@dataclass(frozen=True, slots=True)
class CandidatePoolPreview:
    business_date: date
    timezone: str
    as_of_at: datetime
    window_start_at: datetime
    window_end_at: datetime
    ranking_version: str
    requested_limit: int
    input_hash: str
    scanned_event_count: int
    eligible_event_count: int
    candidate_count: int
    skipped_event_count: int
    skip_summary: dict[str, int]
    candidates: tuple[CandidatePreviewItem, ...]


@dataclass(frozen=True, slots=True)
class CandidateApplyOutcome:
    run: DailyCandidateRunRecord
    candidates: tuple[DailyCandidateRecord, ...]
    reused: bool


@dataclass(frozen=True, slots=True)
class CurrentEventContext:
    event: EventRecord
    trend: EventTrendSnapshotRecord | None
    base_editorial_score_id: UUID
    effective_values: dict[str, Any]
    applied_override_ids: tuple[UUID, ...]
    evidence_summary: dict[str, int]
    open_unknown_count: int
    evidence_context_hash: str
    effective_assessment_hash: str
    candidate_context_hash: str


class DailyCandidateService:
    """Deterministic M5-B daily ranking. This service never calls an AI provider."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.editorial = EditorialScoringService(session_factory=self.session_factory)

    async def preview(self, request: CandidateGenerationRequest) -> CandidatePoolPreview:
        resolved = resolve_generation_request(request)
        async with self.session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(EventRecord)
                        .where(
                            EventRecord.last_updated_at >= resolved.window_start_at,
                            EventRecord.last_updated_at <= resolved.window_end_at,
                        )
                        .order_by(EventRecord.id.asc())
                    )
                ).all()
            )
            event_ids = [event.id for event in events]
            decision_by_event = await latest_decisions(session, event_ids)
            evidence = await evidence_summaries(session, event_ids)
            unknowns = await open_unknown_counts(session, event_ids)
            evidence_hashes = await evidence_context_hashes(session, event_ids)
            trends = await latest_trends(session, event_ids, resolved.as_of_at)
            card_events = await artifact_event_ids(
                session,
                EventCardRecord,
                event_ids,
            )
            draft_events = await artifact_event_ids(
                session,
                EditorialDraftRecord,
                event_ids,
            )

        skip_summary = {code: 0 for code in SKIP_CODES}
        eligible: list[CandidatePreviewItem] = []
        for event in events:
            if event.merged_into_event_id is not None:
                skip_summary[SKIP_MERGED_EVENT] += 1
                continue
            if event.status is EventStatus.RESOLVED and not resolved.include_resolved:
                skip_summary[SKIP_RESOLVED_EVENT] += 1
                continue
            latest_decision = decision_by_event.get(event.id)
            if (
                latest_decision is not None
                and latest_decision.decision is EditorialDecisionType.ARCHIVE
                and not resolved.include_archived
            ):
                skip_summary[SKIP_EDITORIALLY_ARCHIVED] += 1
                continue

            # Reuse the formal M4-C Effective Editorial Assessment semantics.
            # A missing assessment is skipped; candidate generation never invokes AI.
            effective = await self.editorial.effective(event.id)
            if (
                effective.effective_base_score_id is None
                or effective.effective_values is None
            ):
                skip_summary[SKIP_NO_EDITORIAL_ASSESSMENT] += 1
                continue
            values = effective.effective_values
            risk = EditorialRiskLevel(str(values["risk_level"]))
            traffic = float(values["traffic_total"])
            recommended_format = EditorialRecommendedFormat(
                str(values["recommended_format"])
            )
            trend = trends.get(event.id)
            evidence_summary = evidence.get(event.id, empty_evidence_summary())
            open_unknown_count = unknowns.get(event.id, 0)
            evidence_context_hash = evidence_hashes.get(
                event.id,
                empty_evidence_context_hash(event.id),
            )
            override_ids = tuple(item.id for item in effective.applied_overrides)
            assessment_hash = effective_assessment_hash(
                event_id=event.id,
                base_score_id=effective.effective_base_score_id,
                override_ids=override_ids,
                effective_values=values,
            )
            context_hash = candidate_context_hash(
                event=event,
                trend=trend,
                base_score_id=effective.effective_base_score_id,
                override_ids=override_ids,
                effective_values=values,
                evidence_summary=evidence_summary,
                open_unknown_count=open_unknown_count,
                evidence_context_hash=evidence_context_hash,
                ranking_version=CANDIDATE_RANKING_VERSION,
            )
            group = (
                CandidateGroup.REVIEW_REQUIRED
                if risk in (EditorialRiskLevel.R3, EditorialRiskLevel.R4)
                else CandidateGroup.NORMAL
            )
            components = ranking_components(
                group=group,
                traffic_total=traffic,
                trend=trend,
                event=event,
            )
            eligible.append(
                CandidatePreviewItem(
                    event_id=event.id,
                    rank=0,
                    candidate_group=group,
                    event_title_snapshot=event.title,
                    category_snapshot=event.category,
                    event_status_snapshot=event.status,
                    event_last_updated_at_snapshot=event.last_updated_at,
                    source_count_snapshot=event.source_count,
                    platform_count_snapshot=event.platform_count,
                    trend_snapshot_id=trend.id if trend is not None else None,
                    base_editorial_score_id=effective.effective_base_score_id,
                    effective_assessment_hash=assessment_hash,
                    effective_traffic_total=traffic,
                    effective_risk_level=risk,
                    recommended_format=recommended_format,
                    open_unknown_count=open_unknown_count,
                    evidence_summary=evidence_summary,
                    ranking_components=components,
                    card_exists_snapshot=event.id in card_events,
                    draft_exists_snapshot=event.id in draft_events,
                    candidate_context_hash=context_hash,
                )
            )

        ranked = sorted(eligible, key=ranking_key)
        top = tuple(
            with_rank(item, rank)
            for rank, item in enumerate(
                ranked[: resolved.requested_limit],
                1,
            )
        )
        input_hash = stable_hash(
            {
                "business_date": resolved.business_date.isoformat(),
                "timezone": resolved.timezone,
                "as_of_at": resolved.as_of_at,
                "window_start_at": resolved.window_start_at,
                "window_end_at": resolved.window_end_at,
                "ranking_version": CANDIDATE_RANKING_VERSION,
                "requested_limit": resolved.requested_limit,
                "include_resolved": resolved.include_resolved,
                "include_archived": resolved.include_archived,
                "event_context_hashes": sorted(
                    (str(item.event_id), item.candidate_context_hash)
                    for item in ranked
                ),
                "skip_summary": skip_summary,
                "scanned_event_count": len(events),
            }
        )
        skipped = sum(skip_summary.values())
        return CandidatePoolPreview(
            business_date=resolved.business_date,
            timezone=resolved.timezone,
            as_of_at=resolved.as_of_at,
            window_start_at=resolved.window_start_at,
            window_end_at=resolved.window_end_at,
            ranking_version=CANDIDATE_RANKING_VERSION,
            requested_limit=resolved.requested_limit,
            input_hash=input_hash,
            scanned_event_count=len(events),
            eligible_event_count=len(ranked),
            candidate_count=len(top),
            skipped_event_count=skipped,
            skip_summary=skip_summary,
            candidates=top,
        )

    async def apply(
        self,
        request: CandidateGenerationRequest,
        *,
        actor: str,
        confirmed: bool,
    ) -> CandidateApplyOutcome:
        normalized_actor = normalize_text(actor)
        if not normalized_actor:
            raise CandidateValidationError("Candidate Apply 必须提供 Actor")
        if not confirmed:
            raise CandidateValidationError("Candidate Apply 必须显式确认")
        resolved = resolve_generation_request(request)
        lock_key = (
            f"m5b:{resolved.business_date.isoformat()}:{resolved.timezone}:"
            f"{resolved.as_of_at.isoformat()}:{resolved.lookback_hours}:"
            f"{resolved.requested_limit}:{resolved.include_resolved}:"
            f"{resolved.include_archived}:{CANDIDATE_RANKING_VERSION}"
        )
        async with self.session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
                    {"key": lock_key},
                )
                preview = await self.preview(request)
                existing = (
                    await session.scalars(
                        select(DailyCandidateRunRecord).where(
                            DailyCandidateRunRecord.input_hash == preview.input_hash,
                            DailyCandidateRunRecord.status
                            == CandidateRunStatus.SUCCEEDED,
                        )
                    )
                ).first()
                if existing is not None:
                    rows = tuple(
                        (
                            await session.scalars(
                                select(DailyCandidateRecord)
                                .where(DailyCandidateRecord.run_id == existing.id)
                                .order_by(DailyCandidateRecord.rank.asc())
                            )
                        ).all()
                    )
                    return CandidateApplyOutcome(
                        run=existing,
                        candidates=rows,
                        reused=True,
                    )

                run = DailyCandidateRunRecord(
                    business_date=preview.business_date,
                    timezone=preview.timezone,
                    as_of_at=preview.as_of_at,
                    window_start_at=preview.window_start_at,
                    window_end_at=preview.window_end_at,
                    ranking_version=preview.ranking_version,
                    requested_limit=preview.requested_limit,
                    status=CandidateRunStatus.SUCCEEDED,
                    input_hash=preview.input_hash,
                    scanned_event_count=preview.scanned_event_count,
                    eligible_event_count=preview.eligible_event_count,
                    candidate_count=preview.candidate_count,
                    skipped_event_count=preview.skipped_event_count,
                    skip_summary=preview.skip_summary,
                    mode=CandidateRunMode.APPLY,
                    actor=normalized_actor,
                    error_code=None,
                    finished_at=utc_now(),
                )
                session.add(run)
                await session.flush()
                rows = tuple(
                    candidate_record(run.id, item) for item in preview.candidates
                )
                session.add_all(rows)
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="daily_candidate_run",
                    entity_id=run.id,
                    action="apply",
                    actor=normalized_actor,
                    before_data={},
                    after_data={
                        "business_date": preview.business_date.isoformat(),
                        "timezone": preview.timezone,
                        "ranking_version": preview.ranking_version,
                        "candidate_count": preview.candidate_count,
                        "input_hash": preview.input_hash,
                    },
                )
                return CandidateApplyOutcome(
                    run=run,
                    candidates=rows,
                    reused=False,
                )

    async def current_context(
        self,
        event_id: UUID,
        *,
        ranking_version: str = CANDIDATE_RANKING_VERSION,
        for_update: bool = False,
        session: AsyncSession | None = None,
    ) -> CurrentEventContext:
        if session is None:
            async with self.session_factory() as owned:
                return await self._current_context(
                    owned,
                    event_id,
                    ranking_version=ranking_version,
                    for_update=for_update,
                )
        return await self._current_context(
            session,
            event_id,
            ranking_version=ranking_version,
            for_update=for_update,
        )

    async def _current_context(
        self,
        session: AsyncSession,
        event_id: UUID,
        *,
        ranking_version: str,
        for_update: bool,
    ) -> CurrentEventContext:
        statement = select(EventRecord).where(EventRecord.id == event_id)
        if for_update:
            statement = statement.with_for_update()
        event = (await session.execute(statement)).scalar_one_or_none()
        if event is None:
            raise ResourceNotFoundError("事件不存在")
        trend = (
            await session.scalars(
                select(EventTrendSnapshotRecord)
                .where(EventTrendSnapshotRecord.event_id == event_id)
                .order_by(
                    EventTrendSnapshotRecord.window_end_at.desc(),
                    EventTrendSnapshotRecord.created_at.desc(),
                    EventTrendSnapshotRecord.id.desc(),
                )
                .limit(1)
            )
        ).first()
        evidence = (await evidence_summaries(session, [event_id])).get(
            event_id,
            empty_evidence_summary(),
        )
        unknowns = await open_unknown_counts(session, [event_id])
        evidence_hash = (await evidence_context_hashes(session, [event_id])).get(
            event_id,
            empty_evidence_context_hash(event_id),
        )
        effective = await self.editorial.effective(event_id)
        if (
            effective.effective_base_score_id is None
            or effective.effective_values is None
        ):
            raise CandidateValidationError(
                "当前 Event 不存在可用 Effective Editorial Assessment",
                details={"reason": SKIP_NO_EDITORIAL_ASSESSMENT},
            )
        override_ids = tuple(item.id for item in effective.applied_overrides)
        assessment_hash = effective_assessment_hash(
            event_id=event.id,
            base_score_id=effective.effective_base_score_id,
            override_ids=override_ids,
            effective_values=effective.effective_values,
        )
        context_hash = candidate_context_hash(
            event=event,
            trend=trend,
            base_score_id=effective.effective_base_score_id,
            override_ids=override_ids,
            effective_values=effective.effective_values,
            evidence_summary=evidence,
            open_unknown_count=unknowns.get(event_id, 0),
            evidence_context_hash=evidence_hash,
            ranking_version=ranking_version,
        )
        return CurrentEventContext(
            event=event,
            trend=trend,
            base_editorial_score_id=effective.effective_base_score_id,
            effective_values=effective.effective_values,
            applied_override_ids=override_ids,
            evidence_summary=evidence,
            open_unknown_count=unknowns.get(event_id, 0),
            evidence_context_hash=evidence_hash,
            effective_assessment_hash=assessment_hash,
            candidate_context_hash=context_hash,
        )


def resolve_generation_request(
    request: CandidateGenerationRequest,
) -> ResolvedCandidateGenerationRequest:
    if not MIN_LOOKBACK_HOURS <= request.lookback_hours <= MAX_LOOKBACK_HOURS:
        raise CandidateValidationError(
            f"lookback_hours 必须在 {MIN_LOOKBACK_HOURS}..{MAX_LOOKBACK_HOURS}"
        )
    if not 1 <= request.requested_limit <= MAX_CANDIDATE_LIMIT:
        raise CandidateValidationError(
            f"requested_limit 必须在 1..{MAX_CANDIDATE_LIMIT}"
        )
    timezone_name = (request.timezone or get_settings().business_timezone).strip()
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise CandidateValidationError("timezone 必须是有效 IANA timezone") from exc
    as_of = request.as_of_at or utc_now()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise CandidateValidationError("as_of_at 必须是带时区时间")
    as_of_utc = as_of.astimezone(UTC)
    local_date = as_of_utc.astimezone(zone).date()
    business_date = request.business_date or local_date
    if business_date != local_date:
        raise CandidateValidationError(
            "business_date 必须与 as_of_at 在业务 timezone 下的日期一致"
        )
    return ResolvedCandidateGenerationRequest(
        business_date=business_date,
        timezone=timezone_name,
        as_of_at=as_of_utc,
        lookback_hours=request.lookback_hours,
        requested_limit=request.requested_limit,
        include_resolved=request.include_resolved,
        include_archived=request.include_archived,
        window_start_at=as_of_utc - timedelta(hours=request.lookback_hours),
        window_end_at=as_of_utc,
    )


def candidate_record(
    run_id: UUID,
    item: CandidatePreviewItem,
) -> DailyCandidateRecord:
    return DailyCandidateRecord(
        run_id=run_id,
        event_id=item.event_id,
        rank=item.rank,
        candidate_group=item.candidate_group,
        event_title_snapshot=item.event_title_snapshot,
        category_snapshot=item.category_snapshot,
        event_status_snapshot=item.event_status_snapshot,
        event_last_updated_at_snapshot=item.event_last_updated_at_snapshot,
        source_count_snapshot=item.source_count_snapshot,
        platform_count_snapshot=item.platform_count_snapshot,
        trend_snapshot_id=item.trend_snapshot_id,
        base_editorial_score_id=item.base_editorial_score_id,
        effective_assessment_hash=item.effective_assessment_hash,
        effective_traffic_total=item.effective_traffic_total,
        effective_risk_level=item.effective_risk_level,
        recommended_format=item.recommended_format,
        open_unknown_count=item.open_unknown_count,
        evidence_summary=item.evidence_summary,
        ranking_components=item.ranking_components,
        card_exists_snapshot=item.card_exists_snapshot,
        draft_exists_snapshot=item.draft_exists_snapshot,
        candidate_context_hash=item.candidate_context_hash,
    )


def with_rank(item: CandidatePreviewItem, rank: int) -> CandidatePreviewItem:
    return CandidatePreviewItem(
        event_id=item.event_id,
        rank=rank,
        candidate_group=item.candidate_group,
        event_title_snapshot=item.event_title_snapshot,
        category_snapshot=item.category_snapshot,
        event_status_snapshot=item.event_status_snapshot,
        event_last_updated_at_snapshot=item.event_last_updated_at_snapshot,
        source_count_snapshot=item.source_count_snapshot,
        platform_count_snapshot=item.platform_count_snapshot,
        trend_snapshot_id=item.trend_snapshot_id,
        base_editorial_score_id=item.base_editorial_score_id,
        effective_assessment_hash=item.effective_assessment_hash,
        effective_traffic_total=item.effective_traffic_total,
        effective_risk_level=item.effective_risk_level,
        recommended_format=item.recommended_format,
        open_unknown_count=item.open_unknown_count,
        evidence_summary=item.evidence_summary,
        ranking_components=item.ranking_components,
        card_exists_snapshot=item.card_exists_snapshot,
        draft_exists_snapshot=item.draft_exists_snapshot,
        candidate_context_hash=item.candidate_context_hash,
    )


def ranking_key(item: CandidatePreviewItem) -> tuple[Any, ...]:
    update = item.ranking_components.get("update_value")
    velocity = item.ranking_components.get("signal_velocity")
    last_updated = item.event_last_updated_at_snapshot.astimezone(UTC).timestamp()
    return (
        0 if item.candidate_group is CandidateGroup.NORMAL else 1,
        -item.effective_traffic_total,
        update is None,
        -(float(update) if update is not None else 0.0),
        velocity is None,
        -(float(velocity) if velocity is not None else 0.0),
        -last_updated,
        str(item.event_id),
    )


def ranking_components(
    *,
    group: CandidateGroup,
    traffic_total: float,
    trend: EventTrendSnapshotRecord | None,
    event: EventRecord,
) -> dict[str, Any]:
    return {
        "group": group.value,
        "traffic_total": traffic_total,
        "update_value": trend.update_value if trend is not None else None,
        "signal_velocity": trend.signal_velocity if trend is not None else None,
        "last_updated_at": event.last_updated_at.astimezone(UTC).isoformat(),
        "tie_break_event_id": str(event.id),
    }


def effective_assessment_hash(
    *,
    event_id: UUID,
    base_score_id: UUID,
    override_ids: tuple[UUID, ...],
    effective_values: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "event_id": str(event_id),
            "base_score_id": str(base_score_id),
            "applied_override_ids": [str(item) for item in override_ids],
            "effective_values": effective_values,
        }
    )


def candidate_context_hash(
    *,
    event: EventRecord,
    trend: EventTrendSnapshotRecord | None,
    base_score_id: UUID,
    override_ids: tuple[UUID, ...],
    effective_values: dict[str, Any],
    evidence_summary: dict[str, int],
    open_unknown_count: int,
    evidence_context_hash: str,
    ranking_version: str,
) -> str:
    return stable_hash(
        {
            "event_id": str(event.id),
            "event_last_updated_at": event.last_updated_at,
            "trend_snapshot_id": str(trend.id) if trend is not None else None,
            "base_score_id": str(base_score_id),
            "applied_override_ids": [str(item) for item in override_ids],
            "effective_traffic_total": float(effective_values["traffic_total"]),
            "effective_risk_level": str(effective_values["risk_level"]),
            "recommended_format": str(effective_values["recommended_format"]),
            "evidence_summary": evidence_summary,
            "open_unknown_count": open_unknown_count,
            "evidence_context_hash": evidence_context_hash,
            "ranking_version": ranking_version,
        }
    )


def empty_evidence_context_hash(event_id: UUID) -> str:
    return stable_hash(
        {
            "event_id": str(event_id),
            "claims": [],
            "sources": [],
            "unknowns": [],
        }
    )


async def latest_decisions(
    session: AsyncSession,
    event_ids: list[UUID],
) -> dict[UUID, EditorialDecisionRecord]:
    if not event_ids:
        return {}
    rows = list(
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
    return {item.event_id: item for item in rows}


async def latest_trends(
    session: AsyncSession,
    event_ids: list[UUID],
    as_of_at: datetime,
) -> dict[UUID, EventTrendSnapshotRecord]:
    if not event_ids:
        return {}
    rows = list(
        (
            await session.scalars(
                select(EventTrendSnapshotRecord)
                .where(
                    EventTrendSnapshotRecord.event_id.in_(event_ids),
                    EventTrendSnapshotRecord.window_end_at <= as_of_at,
                    EventTrendSnapshotRecord.created_at <= as_of_at,
                )
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
    return {item.event_id: item for item in rows}


async def evidence_summaries(
    session: AsyncSession,
    event_ids: list[UUID],
) -> dict[UUID, dict[str, int]]:
    if not event_ids:
        return {}
    result = {event_id: empty_evidence_summary() for event_id in event_ids}
    rows = (
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
    for event_id, state, count in rows:
        result[event_id][state.value] = int(count)
    for summary in result.values():
        summary["total"] = sum(
            summary[state.value] for state in EvidenceVerificationState
        )
    return result


def empty_evidence_summary() -> dict[str, int]:
    values = {state.value: 0 for state in EvidenceVerificationState}
    values["total"] = 0
    return values


async def open_unknown_counts(
    session: AsyncSession,
    event_ids: list[UUID],
) -> dict[UUID, int]:
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            select(EventUnknownRecord.event_id, func.count(EventUnknownRecord.id))
            .where(
                EventUnknownRecord.event_id.in_(event_ids),
                EventUnknownRecord.status == EventUnknownStatus.OPEN,
            )
            .group_by(EventUnknownRecord.event_id)
        )
    ).all()
    return {event_id: int(count) for event_id, count in rows}


async def evidence_context_hashes(
    session: AsyncSession,
    event_ids: list[UUID],
) -> dict[UUID, str]:
    if not event_ids:
        return {}
    claim_rows = (
        await session.execute(
            select(
                EvidenceClaimRecord.event_id,
                EvidenceClaimRecord.id,
                EvidenceClaimRecord.claim_fingerprint,
                EvidenceClaimRecord.verification_state,
                EvidenceClaimRecord.updated_at,
            )
            .where(EvidenceClaimRecord.event_id.in_(event_ids))
            .order_by(EvidenceClaimRecord.event_id, EvidenceClaimRecord.id)
        )
    ).all()
    source_rows = (
        await session.execute(
            select(
                EvidenceClaimRecord.event_id,
                EvidenceClaimSourceRecord.claim_id,
                EvidenceClaimSourceRecord.signal_id,
                EvidenceClaimSourceRecord.role,
            )
            .join(
                EvidenceClaimRecord,
                EvidenceClaimRecord.id == EvidenceClaimSourceRecord.claim_id,
            )
            .where(EvidenceClaimRecord.event_id.in_(event_ids))
            .order_by(
                EvidenceClaimRecord.event_id,
                EvidenceClaimSourceRecord.claim_id,
                EvidenceClaimSourceRecord.signal_id,
            )
        )
    ).all()
    unknown_rows = (
        await session.execute(
            select(
                EventUnknownRecord.event_id,
                EventUnknownRecord.id,
                EventUnknownRecord.unknown_fingerprint,
                EventUnknownRecord.status,
                EventUnknownRecord.updated_at,
            )
            .where(EventUnknownRecord.event_id.in_(event_ids))
            .order_by(EventUnknownRecord.event_id, EventUnknownRecord.id)
        )
    ).all()
    payloads: dict[UUID, dict[str, Any]] = {
        event_id: {
            "event_id": str(event_id),
            "claims": [],
            "sources": [],
            "unknowns": [],
        }
        for event_id in event_ids
    }
    for event_id, claim_id, fingerprint, state, updated_at in claim_rows:
        payloads[event_id]["claims"].append(
            {
                "claim_id": str(claim_id),
                "fingerprint": fingerprint,
                "state": state.value,
                "updated_at": updated_at,
            }
        )
    for event_id, claim_id, signal_id, role in source_rows:
        payloads[event_id]["sources"].append(
            {
                "claim_id": str(claim_id),
                "signal_id": str(signal_id),
                "role": role.value,
            }
        )
    for event_id, unknown_id, fingerprint, status, updated_at in unknown_rows:
        payloads[event_id]["unknowns"].append(
            {
                "unknown_id": str(unknown_id),
                "fingerprint": fingerprint,
                "status": status.value,
                "updated_at": updated_at,
            }
        )
    return {
        event_id: stable_hash(payload)
        for event_id, payload in payloads.items()
    }


async def artifact_event_ids(
    session: AsyncSession,
    model: type[EventCardRecord] | type[EditorialDraftRecord],
    event_ids: list[UUID],
) -> set[UUID]:
    if not event_ids:
        return set()
    return set(
        (
            await session.scalars(
                select(model.event_id)
                .where(model.event_id.in_(event_ids))
                .distinct()
            )
        ).all()
    )
