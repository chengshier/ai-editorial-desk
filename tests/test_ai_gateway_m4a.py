from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from packages.ai_gateway.domain import AIMessage, InvocationContext
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.database.models import AIInvocationAttemptRecord, AIInvocationRecord
from packages.database.session import get_async_sessionmaker
from tests.m4a_helpers import create_ai_stack, mock_factory


@pytest.mark.usefixtures("clean_database")
async def test_gateway_retry_is_bounded_and_audited(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        route_retry_limit=1,
        provider_retry_limit=1,
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "id": "req-success",
                "choices": [{"message": {"content": "done"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    result = await gateway.generate_text(
        task_key="draft_generation",
        messages=(AIMessage(role="user", content="hello"),),
        max_output_tokens=8,
    )
    assert result.text == "done"
    assert calls == 2

    attempts = list(
        (
            await db_session.scalars(
                select(AIInvocationAttemptRecord)
                .where(AIInvocationAttemptRecord.invocation_id == result.invocation_id)
                .order_by(AIInvocationAttemptRecord.attempt_no)
            )
        ).all()
    )
    assert [item.status for item in attempts] == ["failed", "succeeded"]
    assert [item.retry_index for item in attempts] == [0, 1]
    invocation = await db_session.get(AIInvocationRecord, result.invocation_id)
    assert invocation is not None
    assert invocation.retry_count == 1
    assert invocation.fallback_index == 0
    assert invocation.pricing_snapshot["pricing_version"] == "test-pricing-v1"


@pytest.mark.usefixtures("clean_database")
async def test_gateway_fallback_chain_is_explicit_and_audited(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        primary_name="model-primary",
        fallback_name="model-fallback",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "model-primary":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "fallback-ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    result = await gateway.generate_text(
        task_key="draft_generation",
        messages=(AIMessage(role="user", content="hello"),),
        max_output_tokens=4,
    )
    assert result.model_name == "model-fallback"
    attempts = list(
        (
            await db_session.scalars(
                select(AIInvocationAttemptRecord)
                .where(AIInvocationAttemptRecord.invocation_id == result.invocation_id)
                .order_by(AIInvocationAttemptRecord.attempt_no)
            )
        ).all()
    )
    assert [(item.model_name, item.fallback_index) for item in attempts] == [
        ("model-primary", 0),
        ("model-fallback", 1),
    ]
    assert attempts[0].error_code == AIErrorCode.PROVIDER_UNAVAILABLE.value
    invocation = await db_session.get(AIInvocationRecord, result.invocation_id)
    assert invocation is not None
    assert invocation.fallback_index == 1
    assert invocation.model_name == "model-fallback"


@pytest.mark.usefixtures("clean_database")
async def test_duplicate_invocation_id_never_calls_provider_twice(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(db_session)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    invocation_id = uuid4()
    first = await gateway.generate_text(
        task_key="draft_generation",
        messages=(AIMessage(role="user", content="same"),),
        invocation_id=invocation_id,
    )
    assert first.invocation_id == invocation_id
    with pytest.raises(AIGatewayError) as duplicate:
        await gateway.generate_text(
            task_key="draft_generation",
            messages=(AIMessage(role="user", content="same"),),
            invocation_id=invocation_id,
        )
    assert duplicate.value.code is AIErrorCode.INVALID_REQUEST
    assert calls == 1


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    "structured_payload",
    [
        {},
        {"name": 42},
    ],
)
async def test_structured_output_schema_failure_never_returns_success(
    db_session, structured_payload: dict[str, object]
) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
        route_retry_limit=1,
        provider_retry_limit=1,
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(structured_payload)}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await gateway.generate_structured(
            task_key="evidence_extraction",
            messages=(AIMessage(role="user", content="test"),),
            schema=schema,
            schema_name="generic_test",
            context=InvocationContext(schema_version="schema-v1"),
        )
    assert caught.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID
    assert calls == 2

    invocation = await db_session.scalar(
        select(AIInvocationRecord).order_by(AIInvocationRecord.started_at.desc()).limit(1)
    )
    assert invocation is not None
    assert invocation.status == "failed"
    assert invocation.schema_version == "schema-v1"
    attempts = list(
        (
            await db_session.scalars(
                select(AIInvocationAttemptRecord).where(
                    AIInvocationAttemptRecord.invocation_id == invocation.id
                )
            )
        ).all()
    )
    assert len(attempts) == 2
    assert all(item.error_code == AIErrorCode.STRUCTURED_OUTPUT_INVALID.value for item in attempts)


@pytest.mark.usefixtures("clean_database")
async def test_structured_output_valid_schema_returns_data(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{\"name\":\"ok\"}"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    result = await gateway.generate_structured(
        task_key="evidence_extraction",
        messages=(AIMessage(role="user", content="test"),),
        schema=schema,
        schema_name="generic_test",
        context=InvocationContext(schema_version="schema-v1"),
    )
    assert result.data == {"name": "ok"}


@pytest.mark.usefixtures("clean_database")
async def test_structured_parse_failure_persists_known_usage_cost_and_safe_detail(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
        structured_output_mode="json_object",
    )
    response_content = '{"ok":'
    reasoning_content = "private chain of thought"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "req-persisted-invalid"},
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": response_content,
                            "reasoning_content": reasoning_content,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await gateway.generate_structured(
            task_key="evidence_extraction",
            messages=(AIMessage(role="user", content="test"),),
            schema={"type": "object"},
            schema_name="generic_test",
        )
    assert caught.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID

    invocation = await db_session.scalar(select(AIInvocationRecord))
    assert invocation is not None
    assert invocation.status == "failed"
    assert (invocation.input_tokens, invocation.output_tokens, invocation.total_tokens) == (10, 2, 12)
    assert invocation.estimated_cost == Decimal("0.00001400")
    assert invocation.provider_request_id == "req-persisted-invalid"
    attempt = await db_session.scalar(select(AIInvocationAttemptRecord))
    assert attempt is not None
    assert attempt.status == "failed"
    assert (attempt.input_tokens, attempt.output_tokens, attempt.total_tokens) == (10, 2, 12)
    assert attempt.estimated_cost == Decimal("0.00001400")
    assert attempt.provider_request_id == "req-persisted-invalid"
    assert attempt.metadata_json["provider_response_detail"] == {
        "provider_request_id": "req-persisted-invalid",
        "finish_reason": "length",
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "content_empty": False,
        "content_length": len(response_content),
        "reasoning_content_present": True,
        "reasoning_content_length": len(reasoning_content),
    }
    rendered = repr(attempt.metadata_json)
    assert response_content not in rendered
    assert reasoning_content not in rendered


@pytest.mark.usefixtures("clean_database")
async def test_json_object_mode_still_rejects_business_schema_mismatch(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        task_key="evidence_extraction",
        capability="structured_output",
        structured_output_mode="json_object",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"name":42}'}}]},
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await gateway.generate_structured(
            task_key="evidence_extraction",
            messages=(AIMessage(role="user", content="test"),),
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            schema_name="generic_test",
        )
    assert caught.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID


@pytest.mark.usefixtures("clean_database")
async def test_auth_error_is_not_retried(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_ai_stack(
        db_session,
        route_retry_limit=3,
        provider_retry_limit=3,
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await gateway.generate_text(
            task_key="draft_generation",
            messages=(AIMessage(role="user", content="x"),),
        )
    assert caught.value.code is AIErrorCode.AUTH_ERROR
    assert calls == 1


def assert_uuid(value: UUID) -> None:
    assert isinstance(value, UUID)
