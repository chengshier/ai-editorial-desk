from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.ai_gateway.gateway import AIGateway
from packages.database.models import (
    EventUnknownRecord,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    EvidenceClaimType,
    EvidenceSourceRole,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.evidence.services import EventEvidenceService, EvidenceExtractionService
from tests.m4a_helpers import create_ai_stack, mock_factory
from tests.m4b_helpers import create_event_context


def _response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        },
    )


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_apply_same_result_without_duplicate_business_rows(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    event, signals = await create_event_context(db_session, texts=["同一来源"])
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
    )
    payload = {
        "claims": [
            {
                "text": "并发事实",
                "type": "fact",
                "supporting_signal_ids": [str(signals[0].id)],
                "contradicting_signal_ids": [],
                "confidence": 0.8,
            }
        ],
        "unknowns": [{"text": "并发未知项"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(payload)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    service = EvidenceExtractionService(gateway=gateway)
    first, second = await asyncio.gather(
        service.extract(event_id=event.id, actor="worker-a", apply=True),
        service.extract(event_id=event.id, actor="worker-b", apply=True),
    )
    assert first.run_id != second.run_id
    assert first.ai_invocation_id != second.ai_invocation_id

    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EvidenceClaimRecord)
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(EvidenceClaimSourceRecord)
        ) == 1
        assert await session.scalar(select(func.count()).select_from(EventUnknownRecord)) == 1


@pytest.mark.usefixtures("clean_database")
async def test_human_verify_and_ai_apply_converge_to_human_confirmed(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    event, signals = await create_event_context(db_session, texts=["人工支持来源"])
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
    )
    evidence_service = EventEvidenceService()
    claim = await evidence_service.create_human_claim(
        event_id=event.id,
        actor="editor",
        claim_text="并发核验事实",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )

    payload = {
        "claims": [
            {
                "text": "并发核验事实",
                "type": "fact",
                "supporting_signal_ids": [str(signals[0].id)],
                "contradicting_signal_ids": [],
                "confidence": 0.99,
                "verification_state": "single_source",
            }
        ],
        "unknowns": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(payload)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    extraction_service = EvidenceExtractionService(gateway=gateway)
    await asyncio.gather(
        evidence_service.verify_claim(
            event_id=event.id,
            claim_id=claim.id,
            verification_state=EvidenceVerificationState.CONFIRMED,
            reason="Human verification wins",
            actor="reviewer",
        ),
        extraction_service.extract(
            event_id=event.id,
            actor="worker",
            apply=True,
        ),
    )

    async with get_async_sessionmaker()() as session:
        stored = await session.get(EvidenceClaimRecord, claim.id)
        assert stored is not None
        assert stored.verification_state is EvidenceVerificationState.CONFIRMED
        assert stored.editor_note == "Human verification wins"
