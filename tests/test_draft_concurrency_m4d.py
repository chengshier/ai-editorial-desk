from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from packages.database.models import (
    DraftCitationUsage,
    DraftType,
    EditorialDraftRecord,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_services import (
    DraftService,
    EditorialPackService,
    EventCardService,
    HumanDraftReference,
)
from packages.editorial.errors import DraftValidationError
from packages.evidence.services import EventEvidenceService
from tests.m4d_helpers import create_m4d_context, create_mock_draft_service, valid_draft_payload


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_same_card_and_pack_converge(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    await EventEvidenceService().verify_claim(
        event_id=context.event.id,
        claim_id=context.claims["investigating"].id,
        verification_state=EvidenceVerificationState.SINGLE_SOURCE,
        reason="force a new card input for concurrency",
        actor="editor",
    )

    card_results = await asyncio.gather(
        EventCardService().create(
            event_id=context.event.id,
            trend_snapshot_id=context.trend.id,
        ),
        EventCardService().create(
            event_id=context.event.id,
            trend_snapshot_id=context.trend.id,
        ),
    )
    assert card_results[0][0].id == card_results[1][0].id
    assert sum(int(created) for _card, created in card_results) == 1
    new_card = card_results[0][0]

    pack_results = await asyncio.gather(
        EditorialPackService().create(
            event_id=context.event.id,
            event_card_id=new_card.id,
        ),
        EditorialPackService().create(
            event_id=context.event.id,
            event_card_id=new_card.id,
        ),
    )
    assert pack_results[0][0].id == pack_results[1][0].id
    assert sum(int(created) for _pack, created in pack_results) == 1


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_same_ai_apply_create_one_draft(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service, calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["confirmed"].id,
            unknown_id=context.unknown.id,
        ),
    )

    outcomes = await asyncio.gather(
        service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="worker-a",
            apply=True,
        ),
        service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="worker-b",
            apply=True,
        ),
    )
    assert outcomes[0].draft is not None
    assert outcomes[1].draft is not None
    assert outcomes[0].draft.id == outcomes[1].draft.id
    assert len(calls) == 1
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_same_parent_create_only_one_v2(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    root = await service.create_manual(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.SHORT_30S,
        actor="editor-root",
        reason="concurrency root",
        body="监管部门确认已启动调查。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="main",
                usage=DraftCitationUsage.FACT,
            )
        ],
    )

    async def revise(actor: str, suffix: str):  # type: ignore[no-untyped-def]
        return await DraftService().revise(
            event_id=context.event.id,
            parent_draft_id=root.id,
            actor=actor,
            change_note=f"parallel revision {suffix}",
            body=f"并发版本{suffix}：监管部门确认已启动调查。",
            references=[
                HumanDraftReference(
                    claim_id=context.claims["confirmed"].id,
                    section_key="main",
                    usage=DraftCitationUsage.FACT,
                )
            ],
        )

    results = await asyncio.gather(
        revise("editor-a", "A"),
        revise("editor-b", "B"),
        return_exceptions=True,
    )
    drafts = [item for item in results if isinstance(item, EditorialDraftRecord)]
    errors = [item for item in results if isinstance(item, Exception)]
    assert len(drafts) == 1
    assert drafts[0].draft_version == 2
    assert len(errors) == 1
    assert isinstance(errors[0], DraftValidationError)

    chain = await service.chain(context.event.id, drafts[0].id)
    assert [item.draft_version for item in chain] == [1, 2]
