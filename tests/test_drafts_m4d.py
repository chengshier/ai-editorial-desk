from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.database.models import (
    AIBudgetRecord,
    AIInvocationRecord,
    DraftCitationUsage,
    DraftGenerationRunRecord,
    DraftGenerationStatus,
    DraftSourceType,
    DraftType,
    EditorialDraftRecord,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EventRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.drafts_domain import (
    DRAFT_PROMPT_VERSION,
    DRAFT_SCHEMA_V1,
    DRAFT_SCHEMA_VERSION,
    DRAFT_SYSTEM_PROMPT,
)
from packages.editorial.drafts_generation import DraftService
from packages.editorial.errors import (
    DraftRiskGateError,
    UnsafeDraftClaimUsageError,
    UnsupportedDraftClaimError,
)
from tests.m4a_helpers import create_ai_stack, mock_factory
from tests.m4d_helpers import (
    create_m4d_context,
    create_mock_draft_service,
    valid_draft_payload,
)


def test_draft_system_prompt_requires_exact_json_schema_contract() -> None:
    prompt = DRAFT_SYSTEM_PROMPT

    assert DRAFT_PROMPT_VERSION == "draft-generation-v2"
    assert "exactly one complete JSON object" in prompt
    assert "Do not use Markdown or code fences" in prompt
    assert "Do not add prose before or after the JSON object" in prompt
    assert "must conform exactly to the supplied JSON Schema" in prompt
    assert "remain attributed to that source" in prompt
    assert "uncollected video content happened" in prompt
    for field in DRAFT_SCHEMA_V1["required"]:
        assert field in prompt
    section_schema = DRAFT_SCHEMA_V1["properties"]["sections"]["items"]
    for field in section_schema["required"]:
        assert field in prompt
    citation_schema = section_schema["properties"]["citations"]["items"]
    for field in citation_schema["required"]:
        assert field in prompt


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    ("draft_type", "duration", "payload_type"),
    [
        (DraftType.SHORT_30S, 30, "short_30s"),
        (DraftType.STANDARD_90S, 90, "standard_90s"),
        (DraftType.DEEP_180S, 180, "deep_180s"),
    ],
)
async def test_ai_draft_variants_use_gateway_citations_and_are_idempotent(
    db_session,
    draft_type: DraftType,
    duration: int,
    payload_type: str,
) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service, calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["confirmed"].id,
            draft_type=payload_type,
            unknown_id=context.unknown.id,
        ),
    )

    first = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=draft_type,
        actor="writer",
        apply=True,
    )
    second = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=draft_type,
        actor="writer",
        apply=True,
    )

    assert first.draft is not None
    assert first.draft.duration_target_seconds == duration
    assert first.draft.draft_version == 1
    assert first.draft.source_type is DraftSourceType.AI
    assert first.draft.title == "这件事目前确认了什么？"
    assert first.draft.hook == "先把已经确认和仍待核实的信息分开。"
    assert first.draft.prompt_version == DRAFT_PROMPT_VERSION
    assert first.draft.schema_version == DRAFT_SCHEMA_VERSION
    assert first.draft.ai_invocation_id is not None
    assert first.draft.generation_run_id is not None
    assert second.draft is not None
    assert second.draft.id == first.draft.id
    assert second.reused is True
    assert len(calls) == 1

    request_body = json.loads(calls[0].content.decode())
    assert request_body["model"] == "model-primary"
    system_message = request_body["messages"][0]["content"]
    user_message = request_body["messages"][1]["content"]
    assert "UNTRUSTED DATA" in system_message
    assert "BEGIN UNTRUSTED EDITORIAL DATA" in user_message
    assert "Ignore previous instructions" not in user_message
    assert "raw_payload" not in user_message
    assert "authorization" not in user_message.casefold()
    assert "embedding" not in user_message.casefold()

    detail, refs = await service.detail(context.event.id, first.draft.id)
    assert detail.id == first.draft.id
    assert [(ref.section_key, ref.claim_id, ref.usage) for ref in refs] == [
        ("main", context.claims["confirmed"].id, DraftCitationUsage.FACT)
    ]
    async with get_async_sessionmaker()() as session:
        invocation = await session.get(AIInvocationRecord, first.ai_invocation_id)
        assert invocation is not None
        assert invocation.task_key == "draft_generation"
        assert invocation.prompt_version == DRAFT_PROMPT_VERSION
        assert invocation.schema_version == DRAFT_SCHEMA_VERSION
        assert invocation.subject_type == "event"
        assert invocation.subject_id == str(context.event.id)
        assert invocation.metadata_json["draft_type"] == draft_type.value


@pytest.mark.usefixtures("clean_database")
async def test_preview_spends_gateway_but_writes_no_draft(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service, calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["confirmed"].id,
            unknown_id=context.unknown.id,
        ),
    )
    outcome = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="previewer",
        apply=False,
    )
    assert outcome.draft is None
    assert outcome.candidate is not None
    assert outcome.ai_invocation_id is not None
    assert outcome.status is DraftGenerationStatus.SUCCEEDED
    assert len(calls) == 1
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0
        run = await session.get(DraftGenerationRunRecord, outcome.run_id)
        assert run is not None
        assert run.mode.value == "preview"
        assert run.ai_invocation_id == outcome.ai_invocation_id


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "investigating_as_fact",
        "single_source_as_fact",
        "disputed_as_fact",
        "false_as_fact",
    ],
)
async def test_invalid_claim_permission_is_rejected(
    db_session,
    case: str,
) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    if case == "missing":
        claim_id = uuid4()
        text = "不存在的Claim。"
        expected_error = UnsupportedDraftClaimError
    else:
        claim_key = case.removesuffix("_as_fact")
        claim_id = context.claims[claim_key].id
        text = "模型试图把弱Evidence写成确定事实。"
        expected_error = UnsafeDraftClaimUsageError
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=claim_id,
            usage=DraftCitationUsage.FACT,
            text=text,
        ),
    )
    with pytest.raises(expected_error):
        await service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )


@pytest.mark.usefixtures("clean_database")
async def test_investigating_claim_is_valid_when_explicitly_attributed(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["investigating"].id,
            usage=DraftCitationUsage.ATTRIBUTED,
            text="相关责任问题目前仍在调查中。",
        ),
    )
    outcome = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="writer",
        apply=False,
    )
    assert outcome.candidate is not None


@pytest.mark.usefixtures("clean_database")
async def test_risk_gate_keeps_r4_fact_check_possible_and_never_deletes_event(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(
        db_session,
        risk_level=EditorialRiskLevel.R4,
        recommended_format=EditorialRecommendedFormat.FACT_CHECK,
    )
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["false"].id,
            format_key="fact_check",
            usage=DraftCitationUsage.DEBUNKED,
            text="网传所有服务永久停止的说法已被现有证据反驳。",
        ),
    )
    outcome = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="fact-checker",
        apply=True,
    )
    assert outcome.draft is not None
    async with get_async_sessionmaker()() as session:
        assert await session.get(EventRecord, context.event.id) is not None


@pytest.mark.usefixtures("clean_database")
async def test_r3_regular_path_requires_explicit_human_approval(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(
        db_session,
        risk_level=EditorialRiskLevel.R3,
        recommended_format=EditorialRecommendedFormat.DEEP_DIVE,
    )
    service, calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["confirmed"].id,
            format_key="deep_dive",
        ),
    )
    with pytest.raises(DraftRiskGateError):
        await service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=True,
        )
    assert calls == []
    allowed = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="editor",
        apply=True,
        risk_approval_reason="已人工确认只使用已确认Claim并保留归因。",
    )
    assert allowed.draft is not None


@pytest.mark.usefixtures("clean_database")
async def test_malformed_structured_output_leaves_no_draft(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data={"draft_type": "standard_90s"},
    )
    with pytest.raises(AIGatewayError) as malformed:
        await service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )
    assert malformed.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID


@pytest.mark.usefixtures("clean_database")
async def test_route_disabled_fails_before_provider_call(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    _provider, _model, _fallback, route = await create_ai_stack(
        db_session,
        task_key="draft_generation",
        capability="structured_output",
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(500)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    route.enabled = False
    await db_session.commit()
    with pytest.raises(AIGatewayError) as disabled:
        await DraftService(gateway=gateway).generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )
    assert disabled.value.code is AIErrorCode.ROUTE_NOT_CONFIGURED
    assert calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_budget_exceeded_fails_before_provider_call(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    await create_ai_stack(
        db_session,
        task_key="draft_generation",
        capability="structured_output",
    )
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
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(500)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as budget:
        await DraftService(gateway=gateway).generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )
    assert budget.value.code is AIErrorCode.BUDGET_EXCEEDED
    assert calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_provider_503_marks_run_failed_and_no_draft(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    await create_ai_stack(
        db_session,
        task_key="draft_generation",
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
        await DraftService(gateway=gateway).generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )
    assert caught.value.code is AIErrorCode.PROVIDER_UNAVAILABLE
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0
        run = await session.scalar(
            select(DraftGenerationRunRecord).order_by(
                DraftGenerationRunRecord.created_at.desc()
            )
        )
        assert run is not None
        assert run.status is DraftGenerationStatus.FAILED
        assert run.error_code == AIErrorCode.PROVIDER_UNAVAILABLE.value
