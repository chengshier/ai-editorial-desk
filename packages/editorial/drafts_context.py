from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.domain import AIMessage
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    DraftType,
    EditorialPackRecord,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EditorialScoreOverrideRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventCardRecord,
    EventRecord,
    EventSignalRecord,
    EventUnknownRecord,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    EvidenceVerificationState,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import calculate_traffic_total, stable_hash, validate_dimensions
from packages.editorial.drafts_domain import (
    DRAFT_PROMPT_VERSION,
    DRAFT_SCHEMA_VERSION,
    DRAFT_SERVICE_VERSION,
    DRAFT_SYSTEM_PROMPT,
    draft_duration_seconds,
)
from packages.editorial.errors import (
    DraftEventMergedError,
    DraftValidationError,
    StaleEditorialContextError,
)


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    claims: tuple[EvidenceClaimRecord, ...]
    source_links: tuple[EvidenceClaimSourceRecord, ...]
    unknowns: tuple[EventUnknownRecord, ...]
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class EffectiveContext:
    base_score: EditorialScoreRecord
    values: dict[str, Any]
    overrides: tuple[EditorialScoreOverrideRecord, ...]
    context_hash: str

    @property
    def risk_level(self) -> EditorialRiskLevel:
        return EditorialRiskLevel(str(self.values["risk_level"]))

    @property
    def recommended_format(self) -> EditorialRecommendedFormat:
        return EditorialRecommendedFormat(str(self.values["recommended_format"]))


@dataclass(frozen=True, slots=True)
class EditorialContext:
    event: EventRecord
    evidence: EvidenceContext
    effective: EffectiveContext
    memberships: tuple[tuple[EventSignalRecord, RawSignalRecord], ...]
    context_hash: str


@dataclass(frozen=True, slots=True)
class DraftGenerationSnapshot:
    event_id: UUID
    event_card_id: UUID
    editorial_pack_id: UUID
    draft_type: DraftType
    format_key: EditorialRecommendedFormat
    risk_level: EditorialRiskLevel
    duration_target_seconds: int
    context_hash: str
    input_hash: str
    payload: dict[str, Any]
    claim_states: dict[UUID, EvidenceVerificationState]
    open_unknown_ids: frozenset[UUID]

    def messages(self) -> tuple[AIMessage, ...]:
        content = json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            AIMessage(role="system", content=DRAFT_SYSTEM_PROMPT),
            AIMessage(
                role="user",
                content=(
                    "BEGIN UNTRUSTED EDITORIAL DATA\n"
                    f"{content}\n"
                    "END UNTRUSTED EDITORIAL DATA\n"
                    "Generate only the requested structured draft under the system rules."
                ),
            ),
        )


class EditorialContextBuilder:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def current(
        self,
        event_id: UUID,
        *,
        for_update: bool = False,
    ) -> EditorialContext:
        async with self.session_factory() as session:
            async with session.begin():
                return await load_editorial_context(session, event_id, for_update=for_update)

    async def assert_hash(self, event_id: UUID, expected_hash: str) -> EditorialContext:
        current = await self.current(event_id, for_update=True)
        if current.context_hash != expected_hash:
            raise StaleEditorialContextError(
                "Draft生成期间Evidence、Event或Effective Editorial Assessment已变化"
            )
        return current


class DraftGenerationInputBuilder:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def build(
        self,
        *,
        event_id: UUID,
        event_card_id: UUID,
        editorial_pack_id: UUID,
        draft_type: DraftType,
    ) -> DraftGenerationSnapshot:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(session, event_id, for_update=False)
                card = await session.get(EventCardRecord, event_card_id)
                if card is None or card.event_id != event_id:
                    raise ResourceNotFoundError("Event Card不存在")
                pack = await session.get(EditorialPackRecord, editorial_pack_id)
                if (
                    pack is None
                    or pack.event_id != event_id
                    or pack.event_card_id != event_card_id
                ):
                    raise ResourceNotFoundError("Editorial Pack不存在或不属于该Card")
                _require_current_card(card, context)

                claims_payload = [
                    {
                        "id": str(claim.id),
                        "text": claim.claim_text[:1500],
                        "type": claim.claim_type.value,
                        "verification_state": claim.verification_state.value,
                    }
                    for claim in context.evidence.claims
                ]
                unknowns_payload = [
                    {
                        "id": str(item.id),
                        "text": item.unknown_text[:1000],
                        "status": item.status.value,
                    }
                    for item in context.evidence.unknowns
                    if item.status.value == "open"
                ]
                payload: dict[str, Any] = {
                    "contract": {
                        "service_version": DRAFT_SERVICE_VERSION,
                        "prompt_version": DRAFT_PROMPT_VERSION,
                        "schema_version": DRAFT_SCHEMA_VERSION,
                    },
                    "event": {
                        "id": str(event_id),
                        "title": context.event.title,
                        "category": context.event.category,
                        "status": context.event.status.value,
                    },
                    "card": {
                        "id": str(card.id),
                        "version": card.card_version,
                        "input_hash": card.input_hash,
                        "concise_summary": card.concise_summary,
                    },
                    "pack": {
                        "id": str(pack.id),
                        "version": pack.pack_version,
                        "input_hash": pack.input_hash,
                        "suggested_angles": pack.suggested_angles[:3],
                        "warnings": pack.warnings[:30],
                    },
                    "effective_editorial_assessment": {
                        "score_id": str(context.effective.base_score.id),
                        "risk_level": context.effective.risk_level.value,
                        "recommended_format": context.effective.recommended_format.value,
                        "traffic_total": context.effective.values["traffic_total"],
                        "override_ids": [str(item.id) for item in context.effective.overrides],
                    },
                    "draft_request": {
                        "draft_type": draft_type.value,
                        "duration_target_seconds": draft_duration_seconds(draft_type),
                        "format_key": context.effective.recommended_format.value,
                        "language": context.event.primary_language or "zh-CN",
                    },
                    "claims": claims_payload,
                    "unknowns": unknowns_payload,
                }
                input_hash = stable_hash(
                    {
                        "context_hash": context.context_hash,
                        "event_card_id": str(card.id),
                        "card_input_hash": card.input_hash,
                        "editorial_pack_id": str(pack.id),
                        "pack_input_hash": pack.input_hash,
                        "draft_type": draft_type.value,
                        "duration_target_seconds": draft_duration_seconds(draft_type),
                        "prompt_version": DRAFT_PROMPT_VERSION,
                        "schema_version": DRAFT_SCHEMA_VERSION,
                        "service_version": DRAFT_SERVICE_VERSION,
                    }
                )
                return DraftGenerationSnapshot(
                    event_id=event_id,
                    event_card_id=card.id,
                    editorial_pack_id=pack.id,
                    draft_type=draft_type,
                    format_key=context.effective.recommended_format,
                    risk_level=context.effective.risk_level,
                    duration_target_seconds=draft_duration_seconds(draft_type),
                    context_hash=context.context_hash,
                    input_hash=input_hash,
                    payload=payload,
                    claim_states={
                        claim.id: claim.verification_state for claim in context.evidence.claims
                    },
                    open_unknown_ids=frozenset(
                        item.id
                        for item in context.evidence.unknowns
                        if item.status.value == "open"
                    ),
                )


async def load_editorial_context(
    session: AsyncSession,
    event_id: UUID,
    *,
    for_update: bool,
) -> EditorialContext:
    event_statement = select(EventRecord).where(EventRecord.id == event_id)
    if for_update:
        event_statement = event_statement.with_for_update()
    event = (await session.execute(event_statement)).scalar_one_or_none()
    if event is None:
        raise ResourceNotFoundError("事件不存在")
    if event.merged_into_event_id is not None:
        raise DraftEventMergedError(event.merged_into_event_id)

    claims = tuple(
        (
            await session.scalars(
                select(EvidenceClaimRecord)
                .where(EvidenceClaimRecord.event_id == event_id)
                .order_by(EvidenceClaimRecord.created_at.asc(), EvidenceClaimRecord.id.asc())
            )
        ).all()
    )
    claim_ids = [item.id for item in claims]
    source_links: tuple[EvidenceClaimSourceRecord, ...] = ()
    if claim_ids:
        source_links = tuple(
            (
                await session.scalars(
                    select(EvidenceClaimSourceRecord)
                    .where(EvidenceClaimSourceRecord.claim_id.in_(claim_ids))
                    .order_by(
                        EvidenceClaimSourceRecord.claim_id.asc(),
                        EvidenceClaimSourceRecord.signal_id.asc(),
                    )
                )
            ).all()
        )
    unknowns = tuple(
        (
            await session.scalars(
                select(EventUnknownRecord)
                .where(EventUnknownRecord.event_id == event_id)
                .order_by(EventUnknownRecord.created_at.asc(), EventUnknownRecord.id.asc())
            )
        ).all()
    )
    evidence_payload = {
        "claims": [
            {
                "id": str(item.id),
                "type": item.claim_type.value,
                "verification_state": item.verification_state.value,
                "updated_at": item.updated_at,
            }
            for item in claims
        ],
        "source_links": [
            {
                "claim_id": str(item.claim_id),
                "signal_id": str(item.signal_id),
                "role": item.role.value,
            }
            for item in source_links
        ],
        "unknowns": [
            {
                "id": str(item.id),
                "status": item.status.value,
                "updated_at": item.updated_at,
                "resolved_by_claim_id": (
                    str(item.resolved_by_claim_id) if item.resolved_by_claim_id else None
                ),
            }
            for item in unknowns
        ],
    }
    evidence = EvidenceContext(
        claims=claims,
        source_links=source_links,
        unknowns=unknowns,
        snapshot_hash=stable_hash(evidence_payload),
    )

    scores = tuple(
        (
            await session.scalars(
                select(EditorialScoreRecord)
                .where(EditorialScoreRecord.event_id == event_id)
                .order_by(EditorialScoreRecord.created_at.desc(), EditorialScoreRecord.id.desc())
            )
        ).all()
    )
    latest_human = next(
        (item for item in scores if item.source_type is EditorialScoreSourceType.HUMAN),
        None,
    )
    latest_ai = next(
        (item for item in scores if item.source_type is EditorialScoreSourceType.AI),
        None,
    )
    base = latest_human or latest_ai
    if base is None:
        raise DraftValidationError("创建Event Card前必须存在Effective Editorial Assessment")
    overrides = tuple(
        (
            await session.scalars(
                select(EditorialScoreOverrideRecord)
                .join(
                    EditorialScoreRecord,
                    EditorialScoreRecord.id == EditorialScoreOverrideRecord.editorial_score_id,
                )
                .where(EditorialScoreRecord.event_id == event_id)
                .order_by(
                    EditorialScoreOverrideRecord.created_at.asc(),
                    EditorialScoreOverrideRecord.id.asc(),
                )
            )
        ).all()
    )
    values = _score_values(base)
    for override in overrides:
        values.update(override.overridden_fields)
    dimensions = validate_dimensions(values)
    values["traffic_total"] = calculate_traffic_total(dimensions)
    effective_hash = stable_hash(
        {
            "base_score_id": str(base.id),
            "base_score_input_hash": base.input_hash,
            "override_ids": [str(item.id) for item in overrides],
            "effective_values": values,
        }
    )
    effective = EffectiveContext(
        base_score=base,
        values=values,
        overrides=overrides,
        context_hash=effective_hash,
    )

    membership_rows = (
        await session.execute(
            select(EventSignalRecord, RawSignalRecord)
            .join(RawSignalRecord, RawSignalRecord.id == EventSignalRecord.signal_id)
            .where(EventSignalRecord.event_id == event_id)
            .order_by(EventSignalRecord.signal_id.asc())
        )
    ).all()
    memberships = tuple((row[0], row[1]) for row in membership_rows)
    context_hash = stable_hash(
        {
            "event": {
                "id": str(event.id),
                "status": event.status.value,
                "last_updated_at": event.last_updated_at,
                "source_count": event.source_count,
                "platform_count": event.platform_count,
            },
            "membership_ids": [str(signal.id) for _link, signal in memberships],
            "evidence_snapshot_hash": evidence.snapshot_hash,
            "effective_hash": effective.context_hash,
        }
    )
    return EditorialContext(
        event=event,
        evidence=evidence,
        effective=effective,
        memberships=memberships,
        context_hash=context_hash,
    )


def _score_values(score: EditorialScoreRecord) -> dict[str, Any]:
    return {
        "emotion": score.emotion,
        "information_gap": score.information_gap,
        "visual_value": score.visual_value,
        "user_relevance": score.user_relevance,
        "discussion": score.discussion,
        "novelty": score.novelty,
        "extendability": score.extendability,
        "traffic_total": score.traffic_total,
        "risk_level": score.risk_level.value,
        "recommended_format": score.recommended_format.value,
    }


def _require_current_card(card: EventCardRecord, context: EditorialContext) -> None:
    if card.evidence_snapshot_hash != context.evidence.snapshot_hash:
        raise StaleEditorialContextError("Event Card的Evidence快照已过期，请先生成新Card")
    stored_hash = card.effective_assessment.get("context_hash")
    if stored_hash != context.effective.context_hash:
        raise StaleEditorialContextError("Event Card的Effective Editorial Assessment已过期")
    if card.editorial_score_id != context.effective.base_score.id:
        raise StaleEditorialContextError("Event Card绑定的Effective Score已不是当前版本")
