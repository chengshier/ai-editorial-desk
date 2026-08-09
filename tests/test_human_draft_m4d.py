from __future__ import annotations

import pytest
from sqlalchemy import select

from packages.database.models import (
    ConfigurationChangeLog,
    DraftCitationUsage,
    DraftSourceType,
    DraftStatus,
    DraftType,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_services import DraftService, HumanDraftReference
from packages.editorial.errors import UnsafeDraftClaimUsageError
from tests.m4d_helpers import create_m4d_context


@pytest.mark.usefixtures("clean_database")
async def test_human_draft_is_versioned_cited_and_audited(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    draft = await service.create_manual(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="human-editor",
        reason="人工完成第一版稿件",
        title="人工稿件",
        body="监管部门确认已启动调查。\n\n后续以正式结论为准。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="main",
                usage=DraftCitationUsage.FACT,
            )
        ],
    )
    assert draft.source_type is DraftSourceType.HUMAN
    assert draft.status is DraftStatus.EDITED
    assert draft.draft_version == 1
    assert draft.parent_draft_id is None
    assert draft.draft_chain_id == draft.id
    assert draft.ai_invocation_id is None
    assert draft.generation_run_id is None
    assert draft.prompt_version is None
    assert draft.schema_version is None
    assert "\n\n" in draft.body

    _detail, refs = await service.detail(context.event.id, draft.id)
    assert len(refs) == 1
    assert refs[0].claim_id == context.claims["confirmed"].id

    async with get_async_sessionmaker()() as session:
        audits = list(
            await session.scalars(
                select(ConfigurationChangeLog).where(
                    ConfigurationChangeLog.entity_type == "editorial_draft",
                    ConfigurationChangeLog.entity_id == draft.id,
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].actor == "human-editor"
        assert audits[0].action == "human_create"
        assert audits[0].after_data["reason"] == "人工完成第一版稿件"


@pytest.mark.usefixtures("clean_database")
async def test_human_draft_respects_claim_verification_permissions(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service = DraftService()
    for claim_key in ("investigating", "false"):
        with pytest.raises(UnsafeDraftClaimUsageError):
            await service.create_manual(
                event_id=context.event.id,
                event_card_id=context.card.id,
                editorial_pack_id=context.pack.id,
                draft_type=DraftType.SHORT_30S,
                actor="editor",
                reason="验证引用权限",
                body="这是一段测试稿件。",
                references=[
                    HumanDraftReference(
                        claim_id=context.claims[claim_key].id,
                        section_key="main",
                        usage=DraftCitationUsage.FACT,
                    )
                ],
            )
