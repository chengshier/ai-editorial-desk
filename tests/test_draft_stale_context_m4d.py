from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.clustering.services import EventClusterMaintenanceService
from packages.database.models import (
    DraftCitationUsage,
    DraftGenerationMode,
    DraftType,
    EditorialDraftRecord,
    EventStatus,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_domain import validate_draft_candidate
from packages.editorial.drafts_services import DraftService, HumanDraftReference
from packages.editorial.errors import DraftEventMergedError, StaleEditorialContextError
from packages.events.services import EventService
from packages.evidence.services import EventEvidenceService
from tests.m4d_helpers import create_m4d_context, valid_draft_payload


@pytest.mark.usefixtures("clean_database")
async def test_evidence_change_between_snapshot_and_apply_is_stale(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    snapshot = await service.input_builder.build(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
    )
    run, created = await service._start_run(  # noqa: SLF001
        snapshot,
        actor="worker",
        mode=DraftGenerationMode.APPLY,
    )
    assert created is True
    candidate = validate_draft_candidate(
        valid_draft_payload(claim_id=context.claims["confirmed"].id)
    )

    await EventEvidenceService().verify_claim(
        event_id=context.event.id,
        claim_id=context.claims["investigating"].id,
        verification_state=EvidenceVerificationState.SINGLE_SOURCE,
        reason="Evidence changed during hypothetical provider call",
        actor="editor",
    )

    invocation_id = uuid4()
    with pytest.raises(StaleEditorialContextError):
        await service._apply_ai_draft(  # noqa: SLF001
            run_id=run.id,
            invocation_id=invocation_id,
            snapshot=snapshot,
            candidate=candidate,
            actor="worker",
        )
    await service._finish_failed(  # noqa: SLF001
        run.id,
        invocation_id,
        "STALE_EDITORIAL_CONTEXT",
        "fixture stale context",
    )
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_merge_between_snapshot_and_apply_blocks_old_event(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    snapshot = await service.input_builder.build(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
    )
    run, created = await service._start_run(  # noqa: SLF001
        snapshot,
        actor="worker",
        mode=DraftGenerationMode.APPLY,
    )
    assert created is True
    candidate = validate_draft_candidate(
        valid_draft_payload(claim_id=context.claims["confirmed"].id)
    )

    target = await EventService(db_session).create(
        title="M4-D merge target",
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
        reason="merge during hypothetical provider call",
        actor="editor",
    )
    await db_session.commit()

    invocation_id = uuid4()
    with pytest.raises(DraftEventMergedError) as caught:
        await service._apply_ai_draft(  # noqa: SLF001
            run_id=run.id,
            invocation_id=invocation_id,
            snapshot=snapshot,
            candidate=candidate,
            actor="worker",
        )
    assert caught.value.details == {"target_event_id": str(target.id)}
    await service._finish_failed(  # noqa: SLF001
        run.id,
        invocation_id,
        "EVENT_MERGED",
        "fixture merge context",
    )
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_merged_event_blocks_human_revision_but_keeps_history(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    root = await service.create_manual(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.SHORT_30S,
        actor="editor",
        reason="pre-merge draft",
        body="监管部门确认已启动调查。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="main",
                usage=DraftCitationUsage.FACT,
            )
        ],
    )
    target = await EventService(db_session).create(
        title="Revision merge target",
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
        reason="merge before revision",
        actor="editor",
    )
    await db_session.commit()

    with pytest.raises(DraftEventMergedError):
        await service.revise(
            event_id=context.event.id,
            parent_draft_id=root.id,
            actor="editor",
            change_note="must not revise merged source event",
            body="should not be saved",
            references=[
                HumanDraftReference(
                    claim_id=context.claims["confirmed"].id,
                    section_key="main",
                    usage=DraftCitationUsage.FACT,
                )
            ],
        )
    historical = await service.list(context.event.id)
    assert [item.id for item in historical] == [root.id]
