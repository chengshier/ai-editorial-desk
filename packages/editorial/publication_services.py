from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialDraftRecord,
    EditorialScoreRecord,
    EventCardRecord,
    EventRecord,
)
from packages.database.models.publication import (
    PerformanceHorizon,
    PerformanceSourceType,
    PublicationMode,
    PublicationPerformanceSnapshotRecord,
    PublicationRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import normalize_text
from packages.editorial.publication_domain import (
    PUBLICATION_RECORD_VERSION,
    PERFORMANCE_SNAPSHOT_VERSION,
    EditorialAdoptionRequiredError,
    PerformanceMetrics,
    PerformanceValidationError,
    PublicationAlreadyRecordedError,
    PublicationEventMergedError,
    PublicationValidationError,
    normalize_optional_text,
    normalize_public_url,
    normalize_required_text,
    performance_snapshot_hash,
    publication_content_hash,
    require_aware_utc,
    safe_score_snapshot,
)

_PLATFORM_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


@dataclass(frozen=True, slots=True)
class PublicationCreateOutcome:
    publication: PublicationRecord
    reused: bool


@dataclass(frozen=True, slots=True)
class PerformanceSnapshotOutcome:
    snapshot: PublicationPerformanceSnapshotRecord
    reused: bool


class PublicationService:
    """Record real publications without publishing to any platform or calling AI."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def create(
        self,
        *,
        event_id: UUID,
        publication_mode: PublicationMode,
        platform_key: str,
        public_url: str,
        published_at: datetime,
        actor: str,
        draft_id: UUID | None = None,
        account_label: str | None = None,
        external_post_id: str | None = None,
        title_snapshot: str | None = None,
        cover_text_snapshot: str | None = None,
        body_snapshot: str | None = None,
        backfill_reason: str | None = None,
    ) -> PublicationCreateOutcome:
        normalized_actor = normalize_required_text(actor, "actor", max_length=255)
        normalized_platform = _normalize_platform_key(platform_key)
        normalized_url = normalize_public_url(public_url)
        normalized_published = require_aware_utc(published_at, "published_at")
        normalized_account = normalize_optional_text(account_label, max_length=255)
        normalized_external = normalize_optional_text(external_post_id, max_length=255)
        normalized_backfill = normalize_optional_text(backfill_reason, max_length=5000)
        if publication_mode is PublicationMode.MANUAL_BACKFILL and not normalized_backfill:
            raise PublicationValidationError("manual_backfill 必须提供 backfill_reason")
        if publication_mode is PublicationMode.WORKFLOW and draft_id is None:
            raise PublicationValidationError("workflow Publication 必须绑定 exact draft_id")

        async with self.session_factory() as session:
            async with session.begin():
                event = await _lock_event(session, event_id)
                if event.merged_into_event_id is not None:
                    raise PublicationEventMergedError(event.merged_into_event_id)

                draft: EditorialDraftRecord | None = None
                card: EventCardRecord | None = None
                if draft_id is not None:
                    draft = await session.get(EditorialDraftRecord, draft_id)
                    if draft is None or draft.event_id != event_id:
                        raise ResourceNotFoundError("Draft 不存在或不属于目标 Event")
                    card = await session.get(EventCardRecord, draft.event_card_id)

                current_decision: EditorialDecisionRecord | None = None
                candidate: DailyCandidateRecord | None = None
                candidate_run: DailyCandidateRunRecord | None = None
                score: EditorialScoreRecord | None = None
                if publication_mode is PublicationMode.WORKFLOW:
                    current_decision = await _latest_decision(session, event_id)
                    if (
                        current_decision is None
                        or current_decision.decision is not EditorialDecisionType.ADOPT
                    ):
                        raise EditorialAdoptionRequiredError(
                            "workflow Publication 要求 current Editorial Decision = adopt",
                            details={
                                "event_id": str(event_id),
                                "current_decision": (
                                    current_decision.decision.value
                                    if current_decision is not None
                                    else None
                                ),
                            },
                        )
                    if current_decision.candidate_id is not None:
                        candidate = await session.get(
                            DailyCandidateRecord, current_decision.candidate_id
                        )
                        if candidate is not None:
                            candidate_run = await session.get(
                                DailyCandidateRunRecord, candidate.run_id
                            )
                            score = await session.get(
                                EditorialScoreRecord, candidate.base_editorial_score_id
                            )
                if score is None and card is not None:
                    score = await session.get(EditorialScoreRecord, card.editorial_score_id)

                final_title = _content_value(
                    title_snapshot,
                    draft.title if draft is not None else None,
                    max_length=500,
                )
                draft_cover = _first_nonempty(
                    draft.cover_text_candidates if draft is not None else []
                )
                final_cover = _content_value(
                    cover_text_snapshot,
                    draft_cover,
                    max_length=5000,
                )
                final_body = _content_value(
                    body_snapshot,
                    draft.body if draft is not None else None,
                    max_length=200000,
                )

                score_snapshot = safe_score_snapshot(score)
                if score_snapshot is not None and candidate is not None:
                    score_snapshot = {
                        **score_snapshot,
                        "effective_assessment_hash": candidate.effective_assessment_hash,
                        "effective_traffic_total": candidate.effective_traffic_total,
                        "effective_risk_level": candidate.effective_risk_level.value,
                        "recommended_format": candidate.recommended_format.value,
                    }

                traffic_snapshot = None
                risk_snapshot = None
                format_snapshot = None
                if candidate is not None:
                    traffic_snapshot = candidate.effective_traffic_total
                    risk_snapshot = candidate.effective_risk_level
                    format_snapshot = candidate.recommended_format
                elif current_decision is not None:
                    traffic_snapshot = current_decision.effective_traffic_total_snapshot
                    risk_snapshot = current_decision.risk_level_snapshot
                    format_snapshot = card.recommended_format if card is not None else None
                elif card is not None:
                    effective = card.effective_assessment or {}
                    traffic = effective.get("traffic_total")
                    traffic_snapshot = float(traffic) if isinstance(traffic, (int, float)) else None
                    risk_snapshot = card.risk_level
                    format_snapshot = card.recommended_format

                record = PublicationRecord(
                    event_id=event_id,
                    draft_id=draft.id if draft is not None else None,
                    publication_mode=publication_mode,
                    platform_key=normalized_platform,
                    account_label=normalized_account,
                    external_post_id=normalized_external,
                    public_url=normalized_url,
                    published_at=normalized_published,
                    title_snapshot=final_title,
                    cover_text_snapshot=final_cover,
                    body_snapshot=final_body,
                    publication_content_hash=publication_content_hash(
                        title=final_title,
                        cover_text=final_cover,
                        body=final_body,
                    ),
                    candidate_run_id=candidate_run.id if candidate_run is not None else None,
                    candidate_id=candidate.id if candidate is not None else None,
                    candidate_rank_snapshot=candidate.rank if candidate is not None else None,
                    editorial_decision_id=(
                        current_decision.id if current_decision is not None else None
                    ),
                    editorial_decision_snapshot=(
                        current_decision.decision if current_decision is not None else None
                    ),
                    base_editorial_score_id=score.id if score is not None else None,
                    editorial_score_snapshot=score_snapshot,
                    effective_traffic_total_snapshot=traffic_snapshot,
                    risk_snapshot=risk_snapshot,
                    recommended_format_snapshot=format_snapshot,
                    draft_chain_id=draft.draft_chain_id if draft is not None else None,
                    draft_version_snapshot=draft.draft_version if draft is not None else None,
                    draft_source_type_snapshot=draft.source_type if draft is not None else None,
                    draft_format_snapshot=draft.format_key if draft is not None else None,
                    draft_duration_seconds_snapshot=(
                        draft.duration_target_seconds if draft is not None else None
                    ),
                    actor=normalized_actor,
                    backfill_reason=normalized_backfill,
                    record_version=PUBLICATION_RECORD_VERSION,
                )
                try:
                    async with session.begin_nested():
                        session.add(record)
                        await session.flush()
                except IntegrityError:
                    existing = await _find_identity_duplicate(
                        session,
                        platform_key=normalized_platform,
                        external_post_id=normalized_external,
                        public_url=normalized_url,
                    )
                    if existing is not None and _same_publication_retry(existing, record):
                        return PublicationCreateOutcome(publication=existing, reused=True)
                    raise PublicationAlreadyRecordedError(
                        "同一平台帖子已经存在 Publication 记录",
                        details={
                            "platform_key": normalized_platform,
                            "external_post_id": normalized_external,
                            "public_url": normalized_url,
                            "existing_publication_id": (
                                str(existing.id) if existing is not None else None
                            ),
                        },
                    ) from None

                AuditLogRepository(session).add(
                    entity_type="publication",
                    entity_id=record.id,
                    action="record",
                    actor=normalized_actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "draft_id": str(record.draft_id) if record.draft_id else None,
                        "publication_mode": publication_mode.value,
                        "platform_key": normalized_platform,
                        "external_post_id": normalized_external,
                        "public_url": normalized_url,
                        "published_at": normalized_published.isoformat(),
                        "candidate_id": str(record.candidate_id) if record.candidate_id else None,
                        "candidate_rank_snapshot": record.candidate_rank_snapshot,
                        "editorial_decision_id": (
                            str(record.editorial_decision_id)
                            if record.editorial_decision_id
                            else None
                        ),
                        "editorial_decision_snapshot": (
                            record.editorial_decision_snapshot.value
                            if record.editorial_decision_snapshot
                            else None
                        ),
                    },
                )
                return PublicationCreateOutcome(publication=record, reused=False)

    async def correct(
        self,
        *,
        publication_id: UUID,
        actor: str,
        reason: str,
        changes: dict[str, Any],
    ) -> PublicationRecord:
        normalized_actor = normalize_required_text(actor, "actor", max_length=255)
        normalized_reason = normalize_required_text(reason, "reason", max_length=5000)
        allowed = {
            "account_label",
            "external_post_id",
            "public_url",
            "published_at",
            "title_snapshot",
            "cover_text_snapshot",
            "body_snapshot",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise PublicationValidationError(
                "Publication provenance 建立后不可重绑",
                details={"immutable_fields": sorted(unexpected)},
            )
        if not changes:
            raise PublicationValidationError("至少需要一个修正字段")

        async with self.session_factory() as session:
            async with session.begin():
                publication = await _lock_publication(session, publication_id)
                before = _correction_snapshot(publication)
                normalized = dict(changes)
                if "public_url" in normalized:
                    normalized["public_url"] = normalize_public_url(str(normalized["public_url"]))
                if "published_at" in normalized:
                    value = normalized["published_at"]
                    if not isinstance(value, datetime):
                        raise PublicationValidationError("published_at 类型无效")
                    normalized["published_at"] = require_aware_utc(value, "published_at")
                    latest_observed = await session.scalar(
                        select(PublicationPerformanceSnapshotRecord.observed_at)
                        .where(
                            PublicationPerformanceSnapshotRecord.publication_id
                            == publication_id
                        )
                        .order_by(PublicationPerformanceSnapshotRecord.observed_at.asc())
                        .limit(1)
                    )
                    if (
                        latest_observed is not None
                        and normalized["published_at"] > latest_observed
                    ):
                        raise PublicationValidationError(
                            "published_at 不能晚于已有 Performance observed_at"
                        )
                for field, max_length in (
                    ("account_label", 255),
                    ("external_post_id", 255),
                    ("title_snapshot", 500),
                    ("cover_text_snapshot", 5000),
                    ("body_snapshot", 200000),
                ):
                    if field in normalized:
                        value = normalized[field]
                        normalized[field] = normalize_optional_text(
                            None if value is None else str(value), max_length=max_length
                        )
                try:
                    async with session.begin_nested():
                        for field, value in normalized.items():
                            setattr(publication, field, value)
                        if {
                            "title_snapshot",
                            "cover_text_snapshot",
                            "body_snapshot",
                        } & set(normalized):
                            publication.publication_content_hash = publication_content_hash(
                                title=publication.title_snapshot,
                                cover_text=publication.cover_text_snapshot,
                                body=publication.body_snapshot,
                            )
                        await session.flush()
                except IntegrityError as exc:
                    raise PublicationAlreadyRecordedError(
                        "修正后的 external_post_id 或 public_url 与已有 Publication 冲突"
                    ) from exc
                AuditLogRepository(session).add(
                    entity_type="publication",
                    entity_id=publication.id,
                    action="correct",
                    actor=normalized_actor,
                    before_data=before,
                    after_data={
                        **_correction_snapshot(publication),
                        "reason": normalized_reason,
                    },
                )
                return publication


class PublicationPerformanceService:
    """Append-only manual/canonical performance observations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def add_manual_snapshot(
        self,
        *,
        publication_id: UUID,
        observed_at: datetime,
        horizon: PerformanceHorizon,
        metrics: PerformanceMetrics,
        actor: str,
        supersedes_snapshot_id: UUID | None = None,
        correction_reason: str | None = None,
    ) -> PerformanceSnapshotOutcome:
        normalized_actor = normalize_required_text(actor, "actor", max_length=255)
        normalized_observed = require_aware_utc(observed_at, "observed_at")
        validated_metrics = metrics.validate()
        normalized_reason = normalize_optional_text(correction_reason, max_length=5000)
        if supersedes_snapshot_id is not None and not normalized_reason:
            raise PerformanceValidationError("修正 Snapshot 必须提供 correction_reason")

        async with self.session_factory() as session:
            async with session.begin():
                publication = await _lock_publication(session, publication_id)
                if normalized_observed < publication.published_at:
                    raise PerformanceValidationError(
                        "observed_at 不能早于 Publication published_at"
                    )
                snapshot_hash = performance_snapshot_hash(
                    publication_id=publication_id,
                    observed_at=normalized_observed,
                    horizon=horizon,
                    metrics=validated_metrics,
                    source=PerformanceSourceType.MANUAL,
                )
                existing = (
                    await session.scalars(
                        select(PublicationPerformanceSnapshotRecord).where(
                            PublicationPerformanceSnapshotRecord.snapshot_hash == snapshot_hash
                        )
                    )
                ).first()
                if existing is not None:
                    return PerformanceSnapshotOutcome(snapshot=existing, reused=True)

                if supersedes_snapshot_id is not None:
                    target = await session.get(
                        PublicationPerformanceSnapshotRecord, supersedes_snapshot_id
                    )
                    if target is None or target.publication_id != publication_id:
                        raise ResourceNotFoundError("被修正的 Performance Snapshot 不存在")
                    already_superseded = await session.scalar(
                        select(PublicationPerformanceSnapshotRecord.id).where(
                            PublicationPerformanceSnapshotRecord.supersedes_snapshot_id
                            == supersedes_snapshot_id
                        )
                    )
                    if already_superseded is not None:
                        raise PerformanceValidationError(
                            "只能 supersede 当前有效 Snapshot；请基于最新修正继续修正"
                        )

                record = PublicationPerformanceSnapshotRecord(
                    publication_id=publication_id,
                    observed_at=normalized_observed,
                    horizon=horizon,
                    source=PerformanceSourceType.MANUAL,
                    **validated_metrics.as_dict(),
                    snapshot_hash=snapshot_hash,
                    supersedes_snapshot_id=supersedes_snapshot_id,
                    correction_reason=normalized_reason,
                    actor=normalized_actor,
                    import_run_id=None,
                    snapshot_version=PERFORMANCE_SNAPSHOT_VERSION,
                )
                try:
                    async with session.begin_nested():
                        session.add(record)
                        await session.flush()
                except IntegrityError:
                    existing = (
                        await session.scalars(
                            select(PublicationPerformanceSnapshotRecord).where(
                                PublicationPerformanceSnapshotRecord.snapshot_hash
                                == snapshot_hash
                            )
                        )
                    ).first()
                    if existing is not None:
                        return PerformanceSnapshotOutcome(snapshot=existing, reused=True)
                    raise
                AuditLogRepository(session).add(
                    entity_type="publication_performance_snapshot",
                    entity_id=record.id,
                    action="correct" if supersedes_snapshot_id else "append",
                    actor=normalized_actor,
                    before_data={
                        "supersedes_snapshot_id": (
                            str(supersedes_snapshot_id) if supersedes_snapshot_id else None
                        )
                    },
                    after_data={
                        "publication_id": str(publication_id),
                        "observed_at": normalized_observed.isoformat(),
                        "horizon": horizon.value,
                        "metrics": validated_metrics.as_dict(),
                        "correction_reason": normalized_reason,
                    },
                )
                return PerformanceSnapshotOutcome(snapshot=record, reused=False)


async def _lock_event(session: AsyncSession, event_id: UUID) -> EventRecord:
    event = (
        await session.scalars(
            select(EventRecord).where(EventRecord.id == event_id).with_for_update()
        )
    ).first()
    if event is None:
        raise ResourceNotFoundError("事件不存在")
    return event


async def _lock_publication(
    session: AsyncSession, publication_id: UUID
) -> PublicationRecord:
    publication = (
        await session.scalars(
            select(PublicationRecord)
            .where(PublicationRecord.id == publication_id)
            .with_for_update()
        )
    ).first()
    if publication is None:
        raise ResourceNotFoundError("Publication 不存在")
    return publication


async def _latest_decision(
    session: AsyncSession, event_id: UUID
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


async def _find_identity_duplicate(
    session: AsyncSession,
    *,
    platform_key: str,
    external_post_id: str | None,
    public_url: str,
) -> PublicationRecord | None:
    predicates = [PublicationRecord.public_url == public_url]
    if external_post_id is not None:
        predicates.append(PublicationRecord.external_post_id == external_post_id)
    return (
        await session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.platform_key == platform_key,
                or_(*predicates),
            )
        )
    ).first()


def _same_publication_retry(existing: PublicationRecord, requested: PublicationRecord) -> bool:
    return bool(
        existing.event_id == requested.event_id
        and existing.draft_id == requested.draft_id
        and existing.publication_mode is requested.publication_mode
        and existing.platform_key == requested.platform_key
        and existing.external_post_id == requested.external_post_id
        and existing.public_url == requested.public_url
        and existing.published_at == requested.published_at
        and existing.title_snapshot == requested.title_snapshot
        and existing.cover_text_snapshot == requested.cover_text_snapshot
        and existing.body_snapshot == requested.body_snapshot
    )


def _normalize_platform_key(value: str) -> str:
    normalized = normalize_text(value).casefold()
    if not _PLATFORM_KEY.fullmatch(normalized):
        raise PublicationValidationError(
            "platform_key 只能包含小写字母、数字、点、下划线和连字符"
        )
    return normalized


def _content_value(provided: str | None, fallback: str | None, *, max_length: int) -> str | None:
    if provided is not None:
        return normalize_optional_text(provided, max_length=max_length)
    return normalize_optional_text(fallback, max_length=max_length)


def _first_nonempty(values: list[str]) -> str | None:
    for value in values:
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _correction_snapshot(publication: PublicationRecord) -> dict[str, Any]:
    return {
        "account_label": publication.account_label,
        "external_post_id": publication.external_post_id,
        "public_url": publication.public_url,
        "published_at": publication.published_at.isoformat(),
        "title_snapshot": publication.title_snapshot,
        "cover_text_snapshot": publication.cover_text_snapshot,
        "body_snapshot": publication.body_snapshot,
        "publication_content_hash": publication.publication_content_hash,
    }
