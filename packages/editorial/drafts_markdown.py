from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    DraftClaimReferenceRecord,
    EditorialDraftRecord,
    EditorialPackRecord,
    EventCardRecord,
    EventTrendSnapshotRecord,
    EvidenceClaimRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_repositories import DraftClaimReferenceRepository


class EditorialMarkdownExporter:
    """Pure deterministic renderer. Export never calls AI or mutates artifacts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def render(
        self,
        *,
        event_id: UUID,
        editorial_pack_id: UUID,
        draft_id: UUID | None = None,
    ) -> str:
        async with self.session_factory() as session:
            pack = await session.get(EditorialPackRecord, editorial_pack_id)
            if pack is None or pack.event_id != event_id:
                raise ResourceNotFoundError("Editorial Pack不存在")
            card = await session.get(EventCardRecord, pack.event_card_id)
            if card is None:
                raise ResourceNotFoundError("Event Card不存在")
            trend = await _trend(session, card)
            claims = {
                claim.id: claim
                for claim in (
                    await session.scalars(
                        select(EvidenceClaimRecord).where(
                            EvidenceClaimRecord.event_id == event_id
                        )
                    )
                ).all()
            }
            draft: EditorialDraftRecord | None = None
            refs: Sequence[DraftClaimReferenceRecord] = ()
            if draft_id is not None:
                draft = await session.get(EditorialDraftRecord, draft_id)
                if draft is None or draft.event_id != event_id:
                    raise ResourceNotFoundError("Draft不存在")
                refs = await DraftClaimReferenceRepository(session).list_for_draft(draft.id)

        values = card.effective_assessment.get("values", {})
        lines = [
            f"# Event\n\n{card.title}",
            "## Summary",
            card.concise_summary,
            "## Trend",
            _trend_markdown(trend),
            "## Editorial Score",
            (
                f"- traffic_total: {values.get('traffic_total', 'N/A')}\n"
                f"- score_id: {card.editorial_score_id}"
            ),
            "## Risk",
            (
                f"- risk_level: {card.risk_level.value}\n"
                f"- recommended_format: {card.recommended_format.value}"
            ),
            "## Claims",
            _claims_markdown(card, claims),
            "## Unknowns",
            _list_mapping(pack.unknown_items, "text"),
            "## Timeline",
            _timeline_markdown(pack.timeline_items),
            "## Sources",
            _sources_markdown(pack.source_items),
            "## Suggested Angles",
            _list_mapping(pack.suggested_angles, "text"),
            "## Material Checklist",
            _materials_markdown(pack.material_items, pack.warnings),
            "## Draft",
            _draft_markdown(draft, refs),
        ]
        return "\n\n".join(lines).strip() + "\n"


async def _trend(
    session: AsyncSession,
    card: EventCardRecord,
) -> EventTrendSnapshotRecord | None:
    if card.trend_snapshot_id is None:
        return None
    return await session.get(EventTrendSnapshotRecord, card.trend_snapshot_id)


def _trend_markdown(trend: EventTrendSnapshotRecord | None) -> str:
    if trend is None:
        return "- unavailable: no Trend Snapshot bound to this Card"
    availability = json.dumps(
        trend.feature_availability,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"- calculation_version: {trend.calculation_version}\n"
        f"- signal_velocity: {trend.signal_velocity}\n"
        f"- interaction_velocity: {trend.interaction_velocity}\n"
        f"- source_count: {trend.source_count}\n"
        f"- platform_count: {trend.platform_count}\n"
        f"- semantic_novelty: {trend.semantic_novelty}\n"
        f"- cn_gap: {trend.cn_gap}\n"
        f"- update_value: {trend.update_value}\n"
        f"- feature_availability: {availability}"
    )


def _claims_markdown(
    card: EventCardRecord,
    claims: dict[UUID, EvidenceClaimRecord],
) -> str:
    rows: list[str] = []
    groups = (
        ("confirmed", card.confirmed_claim_ids),
        ("investigating", card.investigating_claim_ids),
        ("single_source", card.single_source_claim_ids),
        ("disputed", card.disputed_claim_ids),
        ("false", card.false_claim_ids),
    )
    for state, claim_ids in groups:
        for raw_id in claim_ids:
            claim = claims.get(UUID(raw_id))
            if claim is not None:
                rows.append(
                    f"- [{state}] {claim.claim_text} (claim_id: {claim.id})"
                )
    return "\n".join(rows) if rows else "- none"


def _list_mapping(items: Sequence[dict[str, Any]], key: str) -> str:
    rows = [f"- {item.get(key, '')}" for item in items]
    return "\n".join(rows) if rows else "- none"


def _timeline_markdown(items: Sequence[dict[str, Any]]) -> str:
    rows = [
        (
            f"- {item.get('published_at') or item.get('collected_at')} | "
            f"{item.get('platform')} | {item.get('title') or '(untitled)'} | "
            f"{item.get('original_url')}"
        )
        for item in items
    ]
    return "\n".join(rows) if rows else "- none"


def _sources_markdown(items: Sequence[dict[str, Any]]) -> str:
    rows = [
        (
            f"- signal_id: {item.get('signal_id')} | {item.get('platform')} | "
            f"{item.get('original_url')}"
        )
        for item in items
    ]
    return "\n".join(rows) if rows else "- none"


def _materials_markdown(
    materials: Sequence[dict[str, Any]],
    warnings: Sequence[dict[str, Any]],
) -> str:
    rows = [
        (
            f"- {item.get('media_type')} | signal_id: {item.get('signal_id')} | "
            f"{item.get('source_url')} | {item.get('usage_note')}"
        )
        for item in materials
    ]
    rows.extend(
        f"- warning: {item.get('code')} | {item.get('message', '')}"
        for item in warnings
    )
    return "\n".join(rows) if rows else "- none"


def _draft_markdown(
    draft: EditorialDraftRecord | None,
    refs: Sequence[DraftClaimReferenceRecord],
) -> str:
    if draft is None:
        return "- no Draft selected"
    reference_lines = [
        (
            f"- {ref.section_key}: claim_id={ref.claim_id}, "
            f"usage={ref.usage.value}"
        )
        for ref in refs
    ]
    references = "\n".join(reference_lines) if reference_lines else "- none"
    return (
        f"### {draft.title or 'Untitled Draft'}\n\n"
        f"{draft.hook or ''}\n\n"
        f"{draft.body}\n\n"
        f"{draft.ending or ''}\n\n"
        f"Interaction: {draft.interaction_question or ''}\n\n"
        f"### Claim References\n{references}"
    )
