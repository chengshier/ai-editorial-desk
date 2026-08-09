from __future__ import annotations

import pytest
from sqlalchemy import select

from packages.clustering.services import EventClusterMaintenanceService
from packages.database.models import (
    EventRecord,
    EventStatus,
    EvidenceVerificationState,
    RawSignalRecord,
)
from packages.editorial.drafts_services import (
    EditorialMarkdownExporter,
    EditorialPackService,
    EventCardService,
)
from packages.editorial.errors import DraftEventMergedError, StaleEditorialContextError
from packages.events.services import EventService
from packages.evidence.services import EventEvidenceService
from tests.m4d_helpers import create_m4d_context


@pytest.mark.usefixtures("clean_database")
async def test_card_pack_are_deterministic_safe_and_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    card = context.card
    pack = context.pack

    assert card.card_version == "event-card-v1"
    assert card.confirmed_claim_ids == [str(context.claims["confirmed"].id)]
    assert card.investigating_claim_ids == [str(context.claims["investigating"].id)]
    assert card.single_source_claim_ids == [str(context.claims["single_source"].id)]
    assert card.disputed_claim_ids == [str(context.claims["disputed"].id)]
    assert card.false_claim_ids == [str(context.claims["false"].id)]
    assert card.unknown_ids == [str(context.unknown.id)]
    assert card.trend_snapshot_id == context.trend.id
    assert card.editorial_score_id == context.score.id
    assert card.risk_level == context.score.risk_level
    assert card.recommended_format == context.score.recommended_format
    assert card.generated_by == "deterministic"
    assert card.ai_invocation_id is None
    assert len(card.input_hash) == 64
    assert len(card.evidence_snapshot_hash) == 64

    second_card, card_created = await EventCardService().create(
        event_id=context.event.id,
        trend_snapshot_id=context.trend.id,
    )
    assert card_created is False
    assert second_card.id == card.id

    second_pack, pack_created = await EditorialPackService().create(
        event_id=context.event.id,
        event_card_id=card.id,
    )
    assert pack_created is False
    assert second_pack.id == pack.id
    assert pack.pack_version == "editorial-pack-v1"
    assert len(pack.suggested_angles) <= 3
    assert all(item["claim_ids"] for item in pack.suggested_angles)
    assert len(pack.source_items) == 6
    assert any(item["code"] == "OPEN_UNKNOWN" for item in pack.warnings)

    assert len(pack.material_items) == 1
    material = pack.material_items[0]
    assert material["signal_id"] == str(context.signals[0].id)
    assert material["source_url"] == context.signals[0].original_url
    assert material["available_metadata"] == {
        "type": "video",
        "duration_seconds": 18,
        "width": 1080,
        "height": 1920,
        "mime_type": "video/mp4",
    }
    assert material["usage_note"].startswith("metadata_only_no_download")
    serialized_pack = str(pack.material_items) + str(pack.source_items) + str(pack.warnings)
    assert "must-not-export" not in serialized_pack
    assert "never-export" not in serialized_pack
    assert "raw-secret" not in serialized_pack

    stored = await db_session.scalar(
        select(RawSignalRecord).where(RawSignalRecord.id == context.signals[0].id)
    )
    assert stored is not None
    assert stored.raw_payload["authorization"] == "[REDACTED]"
    assert stored.media[0]["authorization"] == "never-export"

    exporter = EditorialMarkdownExporter()
    first = await exporter.render(
        event_id=context.event.id,
        editorial_pack_id=pack.id,
    )
    second = await exporter.render(
        event_id=context.event.id,
        editorial_pack_id=pack.id,
    )
    assert first == second
    for heading in (
        "# Event",
        "## Summary",
        "## Trend",
        "## Editorial Score",
        "## Risk",
        "## Claims",
        "## Unknowns",
        "## Timeline",
        "## Sources",
        "## Suggested Angles",
        "## Material Checklist",
        "## Draft",
    ):
        assert heading in first
    assert context.signals[0].original_url in first
    assert "raw-secret-never-export" not in first
    assert "must-not-export" not in first
    assert "token=must-not-export" not in first


@pytest.mark.usefixtures("clean_database")
async def test_evidence_change_creates_new_card_and_old_card_stays_historical(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    old_card = context.card

    changed = await EventEvidenceService().verify_claim(
        event_id=context.event.id,
        claim_id=context.claims["investigating"].id,
        verification_state=EvidenceVerificationState.SINGLE_SOURCE,
        reason="evidence state changed after original card",
        actor="editor",
    )
    assert changed.verification_state is EvidenceVerificationState.SINGLE_SOURCE

    new_card, created = await EventCardService().create(
        event_id=context.event.id,
        trend_snapshot_id=context.trend.id,
    )
    assert created is True
    assert new_card.id != old_card.id
    assert new_card.input_hash != old_card.input_hash
    assert new_card.evidence_snapshot_hash != old_card.evidence_snapshot_hash

    historical = await EventCardService().list(context.event.id)
    assert {item.id for item in historical} == {old_card.id, new_card.id}
    with pytest.raises(StaleEditorialContextError):
        await EditorialPackService().create(
            event_id=context.event.id,
            event_card_id=old_card.id,
        )


@pytest.mark.usefixtures("clean_database")
async def test_merged_event_blocks_new_card_pack_but_history_is_readable(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    target = await EventService(db_session).create(
        title="Merge target",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="editor",
    )
    await EventClusterMaintenanceService(db_session).merge(
        target_event_id=target.id,
        source_event_id=context.event.id,
        reason="fixture merge after M4-D artifacts",
        actor="editor",
    )
    await db_session.commit()

    source = await db_session.get(EventRecord, context.event.id)
    assert source is not None
    assert source.merged_into_event_id == target.id

    with pytest.raises(DraftEventMergedError) as card_error:
        await EventCardService().create(event_id=context.event.id)
    assert card_error.value.details == {"target_event_id": str(target.id)}

    with pytest.raises(DraftEventMergedError):
        await EditorialPackService().create(
            event_id=context.event.id,
            event_card_id=context.card.id,
        )

    cards = await EventCardService().list(context.event.id)
    packs = await EditorialPackService().list(context.event.id)
    assert context.card.id in {item.id for item in cards}
    assert context.pack.id in {item.id for item in packs}
