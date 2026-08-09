from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import func, select

from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.database.models import (
    AIBudgetRecord,
    AIInvocationRecord,
    EditorialScoreRecord,
    EditorialScoringRunRecord,
    EditorialScoringStatus,
    EventRecord,
    EvidenceClaimType,
    EvidenceSourceRole,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import (
    EDITORIAL_PROMPT_VERSION,
    EDITORIAL_SCHEMA_VERSION,
    EDITORIAL_SCORING_VERSION,
)
from packages.editorial.errors import EditorialRiskConflictError
from packages.editorial.services import EditorialScoringService
from packages.evidence.services import EventEvidenceService
from tests.m4a_helpers import create_ai_stack, mock_factory
from tests.m4c_helpers import (
    BASE_TIME,
    TrendSignalSpec,
    create_mock_scoring_service,
    create_trend_context,
    create_trend_snapshot,
    valid_score_payload,
)

RAW_ONLY_SECRET = "secret-never-for-scoring"


@pytest.mark.usefixtures("clean_database")
async def test_ai_apply_recomputes_total_uses_gateway_and_is_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="source data", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service, calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(traffic_total=1),
    )

    first = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="scorer",
        apply=True,
    )
    second = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="scorer",
        apply=True,
    )

    assert first.score is not None
    assert first.traffic_total == 69.0
    assert first.score.traffic_total == 69.0
    assert first.reused is False
    assert second.score is not None
    assert second.score.id == first.score.id
    assert second.reused is True
    assert len(calls) == 1
    request_body = json.loads(calls[0].content.decode())
    assert request_body["model"] == "model-primary"
    user_message = request_body["messages"][1]["content"]
    assert "BEGIN UNTRUSTED EVENT DATA" in user_message
    assert '"interaction_velocity":null' in user_message
    assert RAW_ONLY_SECRET not in user_message
    assert "raw_payload" not in user_message
    assert "authorization" not in user_message.casefold()
    assert "embedding" not in user_message.casefold()

    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialScoreRecord)
        ) == 1
        invocation = await session.get(AIInvocationRecord, first.ai_invocation_id)
        assert invocation is not None
        assert invocation.task_key == "editorial_scoring"
        assert invocation.prompt_version == EDITORIAL_PROMPT_VERSION
        assert invocation.schema_version == EDITORIAL_SCHEMA_VERSION
        assert invocation.subject_type == "event"
        assert invocation.subject_id == str(event.id)
        assert "prompt" not in invocation.metadata_json
        assert "authorization" not in str(invocation.metadata_json).casefold()
        score = await session.get(EditorialScoreRecord, first.score.id)
        assert score is not None
        assert score.scoring_version == EDITORIAL_SCORING_VERSION


@pytest.mark.usefixtures("clean_database")
async def test_preview_records_invocation_and_run_but_no_score(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="preview", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service, calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(),
    )
    outcome = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="previewer",
        apply=False,
    )
    assert outcome.score is None
    assert outcome.ai_invocation_id is not None
    assert outcome.status is EditorialScoringStatus.SUCCEEDED
    assert outcome.traffic_total == 69.0
    assert len(calls) == 1
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialScoreRecord)
        ) == 0
        run = await session.get(EditorialScoringRunRecord, outcome.run_id)
        assert run is not None
        assert run.mode.value == "preview"
        assert run.ai_invocation_id == outcome.ai_invocation_id


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    "invalid_payload",
    [
        valid_score_payload(emotion=101),
        valid_score_payload(information_gap=-1),
        valid_score_payload(risk_level="R9"),
        valid_score_payload(recommended_format="super_viral"),
    ],
)
async def test_invalid_ai_score_is_rejected_without_clamping(
    db_session, invalid_payload: dict[str, object]
) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="invalid", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=invalid_payload,
    )
    with pytest.raises(AIGatewayError) as caught:
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )
    assert caught.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialScoreRecord)
        ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_route_budget_and_provider_failures_are_explicit(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="failure", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    _provider, _model, _fallback, route = await create_ai_stack(
        db_session,
        task_key="editorial_scoring",
        capability="structured_output",
    )
    calls = 0

    def ok_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(valid_score_payload())}}
                ]
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(ok_handler)),
    )
    service = EditorialScoringService(gateway=gateway)
    route.enabled = False
    await db_session.commit()
    with pytest.raises(AIGatewayError) as disabled:
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )
    assert disabled.value.code is AIErrorCode.ROUTE_NOT_CONFIGURED
    assert calls == 0

    route.enabled = True
    db_session.add(
        AIBudgetRecord(
            scope_type="global",
            scope_key="global",
            enabled=True,
            daily_cost_limit=None,
            monthly_cost_limit=None,
            daily_token_limit=0,
            unknown_usage_policy="block",
            config={},
            updated_by="test",
        )
    )
    await db_session.commit()
    with pytest.raises(AIGatewayError) as budget:
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )
    assert budget.value.code is AIErrorCode.BUDGET_EXCEEDED
    assert calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_provider_unavailable_creates_failed_run_and_no_score(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="provider unavailable", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    await create_ai_stack(
        db_session,
        task_key="editorial_scoring",
        capability="structured_output",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await EditorialScoringService(gateway=gateway).score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )
    assert caught.value.code is AIErrorCode.PROVIDER_UNAVAILABLE
    async with get_async_sessionmaker()() as session:
        run = await session.scalar(
            select(EditorialScoringRunRecord)
            .order_by(EditorialScoringRunRecord.created_at.desc())
            .limit(1)
        )
        assert run is not None
        assert run.status is EditorialScoringStatus.FAILED
        assert run.error_code == AIErrorCode.PROVIDER_UNAVAILABLE.value
        assert await session.scalar(
            select(func.count()).select_from(EditorialScoreRecord)
        ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_r0_guard_uses_real_evidence_state(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="single source", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(risk_level="R0"),
    )
    with pytest.raises(EditorialRiskConflictError):
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )

    claim = await EventEvidenceService().create_human_claim(
        event_id=event.id,
        actor="reviewer",
        claim_text="single source evidence",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.SUPPORTING)],
    )
    with pytest.raises(EditorialRiskConflictError):
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )

    await EventEvidenceService().verify_claim(
        event_id=event.id,
        claim_id=claim.id,
        verification_state=EvidenceVerificationState.CONFIRMED,
        reason="human verified",
        actor="reviewer",
    )
    accepted = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="scorer",
        apply=True,
    )
    assert accepted.score is not None
    assert accepted.score.risk_level.value == "R0"


@pytest.mark.usefixtures("clean_database")
async def test_r4_fact_check_is_valid_and_never_deletes_event(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="rumor correction", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    claim = await EventEvidenceService().create_human_claim(
        event_id=event.id,
        actor="reviewer",
        claim_text="rumor claim",
        claim_type=EvidenceClaimType.FACT,
        sources=[(signals[0].id, EvidenceSourceRole.CONTRADICTING)],
    )
    await EventEvidenceService().verify_claim(
        event_id=event.id,
        claim_id=claim.id,
        verification_state=EvidenceVerificationState.FALSE,
        reason="contradicting evidence verified",
        actor="reviewer",
    )
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(
            risk_level="R4",
            recommended_format="fact_check",
            model_reason="False claim can still be explained as a fact-check.",
        ),
    )
    outcome = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="scorer",
        apply=True,
    )
    assert outcome.score is not None
    assert outcome.score.risk_level.value == "R4"
    assert outcome.score.recommended_format.value == "fact_check"
    async with get_async_sessionmaker()() as session:
        stored_event = await session.get(EventRecord, event.id)
        assert stored_event is not None
