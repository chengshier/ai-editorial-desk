from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from packages.database.models import (
    DraftSourceType,
    DraftStatus,
    DraftType,
    EditorialDraftRecord,
    EditorialRecommendedFormat,
)
from tests.m4d_helpers import create_m4d_context


def _draft_row(context, chain_id, version: int, input_char: str) -> EditorialDraftRecord:  # type: ignore[no-untyped-def]
    return EditorialDraftRecord(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_chain_id=chain_id,
        draft_type=DraftType.SHORT_30S,
        format_key=EditorialRecommendedFormat.QUICK_EXPLAINER,
        duration_target_seconds=30,
        language="zh-CN",
        draft_version=version,
        parent_draft_id=None,
        source_type=DraftSourceType.HUMAN,
        status=DraftStatus.EDITED,
        title=None,
        title_candidates=[],
        hook=None,
        hook_candidates=[],
        cover_text_candidates=[],
        sections=[],
        body="database version constraint fixture",
        ending=None,
        interaction_question=None,
        prompt_version=None,
        schema_version=None,
        ai_invocation_id=None,
        generation_run_id=None,
        input_hash=input_char * 64,
        created_by_actor="db-test",
        change_note="constraint fixture",
    )


@pytest.mark.usefixtures("clean_database")
async def test_postgresql_rejects_duplicate_chain_version(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    chain_id = uuid4()
    db_session.add(_draft_row(context, chain_id, 1, "a"))
    await db_session.commit()

    db_session.add(_draft_row(context, chain_id, 1, "b"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
