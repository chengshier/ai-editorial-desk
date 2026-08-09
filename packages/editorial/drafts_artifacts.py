from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    EditorialPackRecord,
    EditorialRecommendedFormat,
    EventCardRecord,
    EventRecord,
    EventTrendSnapshotRecord,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import stable_hash
from packages.editorial.drafts_context import EditorialContext, load_editorial_context
from packages.editorial.drafts_domain import (
    EDITORIAL_PACK_VERSION,
    EVENT_CARD_VERSION,
    MAX_CARD_TIMELINE_ITEMS,
    MAX_MEDIA_ITEMS_PER_SIGNAL,
    MAX_PACK_MATERIAL_ITEMS,
    MAX_PACK_SOURCE_ITEMS,
    MAX_SUGGESTED_ANGLES,
    SAFE_MEDIA_METADATA_KEYS,
)
from packages.editorial.drafts_repositories import EditorialPackRepository, EventCardRepository
from packages.editorial.errors import StaleEditorialContextError


class EventCardService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def create(
        self,
        *,
        event_id: UUID,
        trend_snapshot_id: UUID | None = None,
    ) -> tuple[EventCardRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(session, event_id, for_update=True)
                trend = await _select_trend(session, event_id, trend_snapshot_id)
                groups = _claim_groups(context)
                timeline = _timeline(context)[:MAX_CARD_TIMELINE_ITEMS]
                effective = {
                    "score_id": str(context.effective.base_score.id),
                    "context_hash": context.effective.context_hash,
                    "override_ids": [str(item.id) for item in context.effective.overrides],
                    "values": context.effective.values,
                }
                input_hash = stable_hash(
                    {
                        "card_version": EVENT_CARD_VERSION,
                        "event": {
                            "id": str(context.event.id),
                            "status": context.event.status.value,
                            "last_updated_at": context.event.last_updated_at,
                            "title": context.event.title,
                            "category": context.event.category,
                        },
                        "editorial_context_hash": context.context_hash,
                        "evidence_snapshot_hash": context.evidence.snapshot_hash,
                        "trend_snapshot_id": str(trend.id) if trend else None,
                        "trend_input_hash": trend.input_hash if trend else None,
                        "effective_context_hash": context.effective.context_hash,
                    }
                )
                return await EventCardRepository(session).insert_if_absent(
                    {
                        "event_id": event_id,
                        "card_version": EVENT_CARD_VERSION,
                        "evidence_snapshot_hash": context.evidence.snapshot_hash,
                        "trend_snapshot_id": trend.id if trend else None,
                        "editorial_score_id": context.effective.base_score.id,
                        "title": context.event.title,
                        "concise_summary": _concise_summary(context),
                        "timeline": timeline,
                        "confirmed_claim_ids": groups["confirmed"],
                        "investigating_claim_ids": groups["investigating"],
                        "single_source_claim_ids": groups["single_source"],
                        "disputed_claim_ids": groups["disputed"],
                        "false_claim_ids": groups["false"],
                        "unknown_ids": [
                            str(item.id)
                            for item in context.evidence.unknowns
                            if item.status.value == "open"
                        ],
                        "source_summary": {
                            "signal_count": len(context.memberships),
                            "source_count": context.event.source_count,
                            "platform_count": context.event.platform_count,
                            "timeline_item_count": len(timeline),
                            "timeline_truncated": len(context.memberships) > len(timeline),
                        },
                        "effective_assessment": effective,
                        "risk_level": context.effective.risk_level,
                        "recommended_format": context.effective.recommended_format,
                        "generated_by": "deterministic",
                        "ai_invocation_id": None,
                        "input_hash": input_hash,
                    }
                )

    async def list(self, event_id: UUID) -> tuple[EventCardRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EventCardRepository(session).list_for_event(event_id))


class EditorialPackService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def create(
        self,
        *,
        event_id: UUID,
        event_card_id: UUID,
    ) -> tuple[EditorialPackRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(session, event_id, for_update=True)
                card = await session.get(EventCardRecord, event_card_id)
                if card is None or card.event_id != event_id:
                    raise ResourceNotFoundError("Event Card不存在")
                assert_card_current(card, context)

                source_items = _timeline(context)[:MAX_PACK_SOURCE_ITEMS]
                material_items, media_warnings = _material_items(context)
                material_items = material_items[:MAX_PACK_MATERIAL_ITEMS]
                unknown_items = [
                    {
                        "unknown_id": str(item.id),
                        "text": item.unknown_text,
                        "status": item.status.value,
                    }
                    for item in context.evidence.unknowns
                    if item.status.value == "open"
                ]
                claim_references = _claim_reference_items(context)
                warnings = _pack_warnings(context) + media_warnings
                angles = _suggested_angles(context)[:MAX_SUGGESTED_ANGLES]
                input_hash = stable_hash(
                    {
                        "event_id": str(event_id),
                        "event_card_id": str(card.id),
                        "card_input_hash": card.input_hash,
                        "pack_version": EDITORIAL_PACK_VERSION,
                        "recommended_format": card.recommended_format.value,
                        "source_items": source_items,
                        "material_items": material_items,
                        "warnings": warnings,
                        "unknown_items": unknown_items,
                        "claim_references": claim_references,
                        "suggested_angles": angles,
                    }
                )
                return await EditorialPackRepository(session).insert_if_absent(
                    {
                        "event_id": event_id,
                        "event_card_id": card.id,
                        "pack_version": EDITORIAL_PACK_VERSION,
                        "recommended_format": card.recommended_format,
                        "suggested_angles": angles,
                        "source_items": source_items,
                        "timeline_items": card.timeline,
                        "material_items": material_items,
                        "warnings": warnings,
                        "unknown_items": unknown_items,
                        "claim_references": claim_references,
                        "input_hash": input_hash,
                        "ai_invocation_id": None,
                    }
                )

    async def list(self, event_id: UUID) -> tuple[EditorialPackRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EditorialPackRepository(session).list_for_event(event_id))


async def _select_trend(
    session: AsyncSession,
    event_id: UUID,
    trend_snapshot_id: UUID | None,
) -> EventTrendSnapshotRecord | None:
    if trend_snapshot_id is not None:
        trend = await session.get(EventTrendSnapshotRecord, trend_snapshot_id)
        if trend is None or trend.event_id != event_id:
            raise ResourceNotFoundError("Trend Snapshot不存在")
        return trend
    statement = (
        select(EventTrendSnapshotRecord)
        .where(EventTrendSnapshotRecord.event_id == event_id)
        .order_by(
            EventTrendSnapshotRecord.window_end_at.desc(),
            EventTrendSnapshotRecord.created_at.desc(),
            EventTrendSnapshotRecord.id.desc(),
        )
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


def assert_card_current(card: EventCardRecord, context: EditorialContext) -> None:
    if card.evidence_snapshot_hash != context.evidence.snapshot_hash:
        raise StaleEditorialContextError("Event Card的Evidence已变化，请生成新Card")
    if card.editorial_score_id != context.effective.base_score.id:
        raise StaleEditorialContextError("Event Card绑定的Effective Score已变化")
    if card.effective_assessment.get("context_hash") != context.effective.context_hash:
        raise StaleEditorialContextError("Event Card绑定的Human Override已变化")


def _claim_groups(context: EditorialContext) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {state.value: [] for state in EvidenceVerificationState}
    for claim in context.evidence.claims:
        groups[claim.verification_state.value].append(str(claim.id))
    return groups


def _concise_summary(context: EditorialContext) -> str:
    by_state: dict[EvidenceVerificationState, list[str]] = {
        state: [] for state in EvidenceVerificationState
    }
    for claim in context.evidence.claims:
        by_state[claim.verification_state].append(claim.claim_text)
    pieces: list[str] = []
    labels = (
        (EvidenceVerificationState.CONFIRMED, "已确认"),
        (EvidenceVerificationState.INVESTIGATING, "调查中"),
        (EvidenceVerificationState.SINGLE_SOURCE, "单一来源"),
        (EvidenceVerificationState.DISPUTED, "存在争议"),
        (EvidenceVerificationState.FALSE, "已证伪说法"),
    )
    for state, label in labels:
        if by_state[state]:
            pieces.append(f"{label}：{by_state[state][0]}")
        if len(pieces) >= 3:
            break
    return "；".join(pieces) if pieces else "当前尚无可用于资料卡的Evidence Claim。"


def _timeline(context: EditorialContext) -> list[dict[str, Any]]:
    items = [
        {
            "signal_id": str(signal.id),
            "relation": link.relation.value,
            "title": signal.title,
            "platform": signal.platform,
            "author_name": signal.author_name,
            "published_at": signal.published_at.isoformat() if signal.published_at else None,
            "collected_at": signal.collected_at.isoformat(),
            "original_url": signal.original_url,
            "canonical_url": signal.canonical_url,
        }
        for link, signal in context.memberships
    ]
    items.sort(
        key=lambda item: (
            str(item["published_at"] or item["collected_at"]),
            str(item["signal_id"]),
        )
    )
    return items


def _material_items(
    context: EditorialContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claim_ids_by_signal: dict[UUID, list[str]] = {}
    claims_by_id = {item.id: item for item in context.evidence.claims}
    for link in context.evidence.source_links:
        claim_ids_by_signal.setdefault(link.signal_id, []).append(str(link.claim_id))

    materials: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for _event_link, signal in context.memberships:
        media_items = signal.media[:MAX_MEDIA_ITEMS_PER_SIGNAL]
        if not media_items:
            warnings.append(
                {
                    "code": "MEDIA_METADATA_UNAVAILABLE",
                    "signal_id": str(signal.id),
                    "message": "该Signal没有统一可验证的media metadata，请人工检查原链接。",
                }
            )
            continue
        attached_claims = [
            claims_by_id[UUID(raw_id)]
            for raw_id in claim_ids_by_signal.get(signal.id, [])
            if UUID(raw_id) in claims_by_id
        ]
        risky = any(
            claim.verification_state
            in (EvidenceVerificationState.DISPUTED, EvidenceVerificationState.FALSE)
            for claim in attached_claims
        )
        for media in media_items:
            metadata = {
                key: value
                for key, value in media.items()
                if key in SAFE_MEDIA_METADATA_KEYS
                and isinstance(value, (str, int, float, bool))
            }
            media_type = str(
                metadata.get("media_type") or metadata.get("type") or "unclassified"
            )[:50]
            materials.append(
                {
                    "signal_id": str(signal.id),
                    "media_type": media_type,
                    "source_url": signal.original_url,
                    "title": signal.title,
                    "available_metadata": metadata,
                    "usage_note": (
                        "metadata_only_no_download; review copyright/context before use"
                    ),
                    "claim_ids": claim_ids_by_signal.get(signal.id, []),
                    "risk_note": (
                        "verify_disputed_or_false_context"
                        if risky
                        else "manual_rights_review_required"
                    ),
                }
            )
    return materials, warnings


def _claim_reference_items(context: EditorialContext) -> list[dict[str, Any]]:
    source_counts: dict[UUID, int] = {}
    for link in context.evidence.source_links:
        source_counts[link.claim_id] = source_counts.get(link.claim_id, 0) + 1
    return [
        {
            "claim_id": str(claim.id),
            "text": claim.claim_text,
            "claim_type": claim.claim_type.value,
            "verification_state": claim.verification_state.value,
            "source_count": source_counts.get(claim.id, 0),
        }
        for claim in context.evidence.claims
    ]


def _pack_warnings(context: EditorialContext) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for claim in context.evidence.claims:
        if claim.verification_state in (
            EvidenceVerificationState.SINGLE_SOURCE,
            EvidenceVerificationState.DISPUTED,
            EvidenceVerificationState.FALSE,
        ):
            warnings.append(
                {
                    "code": f"CLAIM_{claim.verification_state.value.upper()}",
                    "claim_id": str(claim.id),
                    "message": "表达时必须保留Evidence verification语义。",
                }
            )
    for unknown in context.evidence.unknowns:
        if unknown.status.value == "open":
            warnings.append(
                {
                    "code": "OPEN_UNKNOWN",
                    "unknown_id": str(unknown.id),
                    "message": unknown.unknown_text,
                }
            )
    return warnings


def _suggested_angles(context: EditorialContext) -> list[dict[str, Any]]:
    by_state: dict[EvidenceVerificationState, list[str]] = {
        state: [] for state in EvidenceVerificationState
    }
    for claim in context.evidence.claims:
        by_state[claim.verification_state].append(str(claim.id))
    candidates: list[dict[str, Any]] = []
    confirmed = by_state[EvidenceVerificationState.CONFIRMED]
    if confirmed:
        candidates.append(
            {
                "key": "fact_timeline",
                "text": "围绕已确认事实做时间线还原",
                "claim_ids": confirmed[:5],
            }
        )
    fact_check_ids = (
        by_state[EvidenceVerificationState.FALSE]
        + by_state[EvidenceVerificationState.DISPUTED]
    )
    if fact_check_ids:
        candidates.append(
            {
                "key": "fact_check",
                "text": "围绕争议或已证伪说法做真假拆解",
                "claim_ids": fact_check_ids[:5],
            }
        )
    attributed = (
        by_state[EvidenceVerificationState.INVESTIGATING]
        + by_state[EvidenceVerificationState.SINGLE_SOURCE]
    )
    if attributed:
        candidates.append(
            {
                "key": "what_we_know",
                "text": "区分目前已知与仍待确认的信息",
                "claim_ids": attributed[:5],
            }
        )
    return candidates[:MAX_SUGGESTED_ANGLES]
