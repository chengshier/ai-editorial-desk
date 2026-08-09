from __future__ import annotations

import pytest

from packages.database.models import (
    DraftCitationUsage,
    DraftSourceType,
    DraftType,
    EditorialDraftRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_services import DraftService, HumanDraftReference
from packages.editorial.errors import DraftValidationError
from tests.m4d_helpers import create_m4d_context


@pytest.mark.usefixtures("clean_database")
async def test_human_revision_keeps_original_and_builds_monotonic_chain(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    root = await service.create_manual(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.SHORT_30S,
        actor="editor-a",
        reason="root revision chain",
        body="第一版：监管部门确认已启动调查。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="main",
                usage=DraftCitationUsage.FACT,
            )
        ],
    )
    revision = await service.revise(
        event_id=context.event.id,
        parent_draft_id=root.id,
        actor="editor-b",
        change_note="补充谨慎归因",
        body="第二版：监管部门确认已启动调查；其他责任问题仍在调查中。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="confirmed",
                usage=DraftCitationUsage.FACT,
            ),
            HumanDraftReference(
                claim_id=context.claims["investigating"].id,
                section_key="investigating",
                usage=DraftCitationUsage.ATTRIBUTED,
            ),
        ],
    )
    assert revision.parent_draft_id == root.id
    assert revision.draft_chain_id == root.draft_chain_id
    assert revision.draft_version == 2
    assert revision.source_type is DraftSourceType.HUMAN
    assert revision.ai_invocation_id is None

    async with get_async_sessionmaker()() as session:
        persisted_root = await session.get(EditorialDraftRecord, root.id)
        assert persisted_root is not None
        assert persisted_root.body == "第一版：监管部门确认已启动调查。"
        assert persisted_root.draft_version == 1

    chain = await service.chain(context.event.id, revision.id)
    assert [(item.id, item.draft_version) for item in chain] == [
        (root.id, 1),
        (revision.id, 2),
    ]

    with pytest.raises(DraftValidationError):
        await service.revise(
            event_id=context.event.id,
            parent_draft_id=root.id,
            actor="editor-c",
            change_note="旧版本不能再次成为新Revision父节点",
            body="不会写入的新版本",
            references=[
                HumanDraftReference(
                    claim_id=context.claims["confirmed"].id,
                    section_key="main",
                    usage=DraftCitationUsage.FACT,
                )
            ],
        )
