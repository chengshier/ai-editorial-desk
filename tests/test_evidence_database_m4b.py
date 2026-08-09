from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.database.models import (
    EventUnknownRecord,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    EvidenceClaimType,
    EvidenceCreatedByType,
    EvidenceSourceRole,
    EvidenceVerificationState,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.evidence.domain import claim_fingerprint
from packages.evidence.errors import EvidenceValidationError
from packages.evidence.services import EventEvidenceService
from tests.m4b_helpers import create_event_context


@pytest.mark.usefixtures("clean_database")
async def test_claim_fingerprint_source_unique_and_event_membership(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["来源一", "来源二"])
    other_event, other_signals = await create_event_context(db_session, texts=["无关来源"])
    del other_event
    service = EventEvidenceService()

    first = await service.create_human_claim(
        event_id=event.id,
        actor="editor-a",
        claim_text="  已发布   官方公告  ",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )
    duplicate = await service.create_human_claim(
        event_id=event.id,
        actor="editor-b",
        claim_text="已发布 官方公告",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )
    assert duplicate.id == first.id

    async with get_async_sessionmaker()() as session:
        claim_count = await session.scalar(
            select(func.count()).select_from(EvidenceClaimRecord)
        )
        source_count = await session.scalar(
            select(func.count()).select_from(EvidenceClaimSourceRecord)
        )
    assert claim_count == 1
    assert source_count == 1

    with pytest.raises(EvidenceValidationError):
        await service.attach_source(
            event_id=event.id,
            claim_id=first.id,
            signal_id=other_signals[0].id,
            role=EvidenceSourceRole.SUPPORTING,
            actor="editor-a",
        )


@pytest.mark.usefixtures("clean_database")
async def test_raw_signal_delete_is_restricted_by_evidence_source(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["可追溯事实"])
    await EventEvidenceService().create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="事实 A",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )

    async with get_async_sessionmaker()() as session:
        signal = await session.get(RawSignalRecord, signals[0].id)
        assert signal is not None
        await session.delete(signal)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.usefixtures("clean_database")
async def test_database_rejects_invalid_confidence_and_missing_invocation(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_event_context(db_session, texts=["事实"])

    async with get_async_sessionmaker()() as session:
        invalid_confidence = EvidenceClaimRecord(
            event_id=event.id,
            claim_text="confidence invalid",
            claim_type=EvidenceClaimType.FACT,
            verification_state=EvidenceVerificationState.INVESTIGATING,
            extraction_confidence=1.5,
            claim_fingerprint=claim_fingerprint("confidence invalid", EvidenceClaimType.FACT),
            extraction_version="test-v1",
            extraction_run_id=None,
            ai_invocation_id=None,
            created_by_type=EvidenceCreatedByType.HUMAN,
            created_by_actor="editor",
            editor_note=None,
        )
        session.add(invalid_confidence)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        missing_invocation = EvidenceClaimRecord(
            event_id=event.id,
            claim_text="missing invocation",
            claim_type=EvidenceClaimType.FACT,
            verification_state=EvidenceVerificationState.INVESTIGATING,
            extraction_confidence=0.5,
            claim_fingerprint=claim_fingerprint("missing invocation", EvidenceClaimType.FACT),
            extraction_version="test-v1",
            extraction_run_id=None,
            ai_invocation_id=uuid4(),
            created_by_type=EvidenceCreatedByType.AI,
            created_by_actor=None,
            editor_note=None,
        )
        session.add(missing_invocation)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.usefixtures("clean_database")
async def test_human_claim_has_no_invocation_and_unknown_is_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["事实"])
    service = EventEvidenceService()
    claim = await service.create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="人工事实",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )
    assert claim.created_by_type is EvidenceCreatedByType.HUMAN
    assert claim.ai_invocation_id is None

    first = await service.create_unknown(
        event_id=event.id,
        unknown_text="  事故原因   尚不清楚 ",
        actor="editor",
    )
    duplicate = await service.create_unknown(
        event_id=event.id,
        unknown_text="事故原因 尚不清楚",
        actor="editor",
    )
    assert duplicate.id == first.id

    async with get_async_sessionmaker()() as session:
        count = await session.scalar(select(func.count()).select_from(EventUnknownRecord))
    assert count == 1
