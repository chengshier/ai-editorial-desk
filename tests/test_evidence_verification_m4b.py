from __future__ import annotations

import pytest

from packages.database.models import (
    EvidenceClaimType,
    EvidenceSourceRole,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.evidence.errors import EventMergedError, EvidenceValidationError
from packages.evidence.input_builder import EvidenceInputBuilder
from packages.evidence.services import EventEvidenceService
from tests.m4b_helpers import create_event_context


@pytest.mark.usefixtures("clean_database")
async def test_human_confirmed_requires_support_and_protects_last_support(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["支持", "反驳"])
    service = EventEvidenceService()
    claim = await service.create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="需要人工确认的事实",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )
    assert claim.verification_state is EvidenceVerificationState.SINGLE_SOURCE

    confirmed = await service.verify_claim(
        event_id=event.id,
        claim_id=claim.id,
        verification_state=EvidenceVerificationState.CONFIRMED,
        reason="人工核验支持来源后确认",
        actor="reviewer",
    )
    assert confirmed.verification_state is EvidenceVerificationState.CONFIRMED
    assert confirmed.editor_note == "人工核验支持来源后确认"

    with pytest.raises(EvidenceValidationError):
        await service.remove_source(
            event_id=event.id,
            claim_id=claim.id,
            signal_id=signals[0].id,
            actor="reviewer",
        )


@pytest.mark.usefixtures("clean_database")
async def test_human_false_requires_contradiction_and_protects_last_contradiction(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["支持", "反驳"])
    service = EventEvidenceService()
    claim = await service.create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="待核验说法",
        claim_type=EvidenceClaimType.ALLEGATION,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )

    with pytest.raises(EvidenceValidationError):
        await service.verify_claim(
            event_id=event.id,
            claim_id=claim.id,
            verification_state=EvidenceVerificationState.FALSE,
            reason="尚无反驳来源",
            actor="reviewer",
        )

    await service.attach_source(
        event_id=event.id,
        claim_id=claim.id,
        signal_id=signals[1].id,
        role=EvidenceSourceRole.CONTRADICTING,
        actor="reviewer",
    )
    rejected = await service.verify_claim(
        event_id=event.id,
        claim_id=claim.id,
        verification_state=EvidenceVerificationState.FALSE,
        reason="人工核验反驳证据后判为 false",
        actor="reviewer",
    )
    assert rejected.verification_state is EvidenceVerificationState.FALSE

    with pytest.raises(EvidenceValidationError):
        await service.remove_source(
            event_id=event.id,
            claim_id=claim.id,
            signal_id=signals[1].id,
            actor="reviewer",
        )


@pytest.mark.usefixtures("clean_database")
async def test_confirmed_without_support_is_rejected(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(db_session, texts=["反驳"])
    service = EventEvidenceService()
    claim = await service.create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="只有反驳的说法",
        claim_type=EvidenceClaimType.ALLEGATION,
        sources=[(signals[0].id, EvidenceSourceRole.CONTRADICTING)],
    )
    assert claim.verification_state is EvidenceVerificationState.DISPUTED
    with pytest.raises(EvidenceValidationError):
        await service.verify_claim(
            event_id=event.id,
            claim_id=claim.id,
            verification_state=EvidenceVerificationState.CONFIRMED,
            reason="不能缺少支持证据",
            actor="reviewer",
        )


@pytest.mark.usefixtures("clean_database")
async def test_merged_event_blocks_new_evidence_and_input_builder(db_session) -> None:  # type: ignore[no-untyped-def]
    source_event, source_signals = await create_event_context(db_session, texts=["旧事件"])
    target_event, _ = await create_event_context(db_session, texts=["目标事件"])
    async with get_async_sessionmaker()() as session:
        stored = await session.get(type(source_event), source_event.id)
        assert stored is not None
        stored.merged_into_event_id = target_event.id
        await session.commit()

    with pytest.raises(EventMergedError) as create_error:
        await EventEvidenceService().create_human_claim(
            event_id=source_event.id,
            actor="editor",
            claim_text="不应写入旧事件",
            claim_type=EvidenceClaimType.FACT,
            sources=[(source_signals[0].id, EvidenceSourceRole.SUPPORTING)],
        )
    assert create_error.value.details == {"target_event_id": str(target_event.id)}

    with pytest.raises(EventMergedError):
        await EvidenceInputBuilder().build(event_id=source_event.id)
