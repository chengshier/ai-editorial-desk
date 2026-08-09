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
    AITaskRouteRecord,
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
from packages.editorial.drafts_domain import DRAFT_PROMPT_VERSION, DRAFT_SCHEMA_VERSION
from packages.editorial.drafts_generation import DraftService
from packages.editorial.errors import (
    DraftRiskGateError,
    DraftValidationError,
    UnsafeDraftClaimUsageError,
    UnsupportedDraftClaimError,
)
from tests.m4a_helpers import create_ai_stack, mock_factory
from tests.m4d_helpers import (
    create_m4d_context,
    create_mock_draft_service,
    valid_draft_payload,
)


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
async def test_claim_permissions_unknown_and_fact_check_are_enforced(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)

    invalid_cases = [
        valid_draft_payload(claim_id=uuid4()),
        valid_draft_payload(
            claim_id=context.claims["investigating"].id,
            usage=DraftCitationUsage.FACT,
            text="监管部门已经确认额外责任方。",
        ),
        valid_draft_payload(
            claim_id=context.claims["single_source"].id,
            usage=DraftCitationUsage.FACT,
            text="现场确定发生了停电。",
        ),
        valid_draft_payload(
            claim_id=context.claims["disputed"].id,
            usage=DraftCitationUsage.FACT,
            text="设备故障就是确定原因。",
        ),
        valid_draft_payload(
            claim_id=context.claims["false"].id,
            usage=DraftCitationUsage.FACT,
            text="所有服务已经永久停止。",
        ),
    ]
    expected = [
        UnsupportedDraftClaimError,
        UnsafeDraftClaimUsageError,
        UnsafeDraftClaimUsageError,
        UnsafeDraftClaimUsageError,
        UnsafeDraftClaimUsageError,
    ]
    for payload, error_type in zip(invalid_cases, expected, strict=True):
        service, _calls = await create_mock_draft_service(
            db_session,
            response_data=payload,
        )
        with pytest.raises(error_type):
            await service.generate(
                event_id=context.event.id,
                event_card_id=context.card.id,
                editorial_pack_id=context.pack.id,
                draft_type=DraftType.STANDARD_90S,
                actor="writer",
                apply=False,
            )

    valid_attributed, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["investigating"].id,
            usage=DraftCitationUsage.ATTRIBUTED,
            text="相关责任问题目前仍在调查中。",
        ),
    )
    attributed = await valid_attributed.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="writer",
        apply=False,
    )
    assert attributed.candidate is not None


@pytest.mark.usefixtures("clean_database")
async def test_risk_gate_keeps_r4_fact_check_possible_and_never_deletes_event(db_session) -> None:  # type: ignore[no-untyped-def]
    r4 = await create_m4d_context(
        db_session,
        risk_level=EditorialRiskLevel.R4,
        recommended_format=EditorialRecommendedFormat.FACT_CHECK,
    )
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=r4.claims["false"].id,
            format_key="fact_check",
            usage=DraftCitationUsage.DEBUNKED,
            text="网传所有服务永久停止的说法已被现有证据反驳。",
        ),
    )
    outcome = await service.generate(
        event_id=r4.event.id,
        event_card_id=r4.card.id,
        editorial_pack_id=r4.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="fact-checker",
        apply=True,
    )
    assert outcome.draft is not None
    async with get_async_sessionmaker()() as session:
        assert await session.get(EventRecord, r4.event.id) is not None


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
async def test_malformed_route_budget_and_provider_failure_leave_no_draft(db_session) -> None:  # type: ignore[no-untyped-def]
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

    _provider, _model, _fallback, route = await create_ai_stack(
        db_session,
        task_key="draft_generation",
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
                    {
                        "message": {
                            "content": json.dumps(
                                valid_draft_payload(
                                    claim_id=context.claims["confirmed"].id
                                )
                            )
                        }
                    }
                ]
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(ok_handler)),
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

    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0


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
