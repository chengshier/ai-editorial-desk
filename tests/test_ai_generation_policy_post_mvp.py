from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from apps.api.schemas.m4a import AITaskRouteUpdate
from packages.ai_gateway.domain import AIMessage
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.ai_gateway.generation_policy import (
    generation_policy_from_config,
    merge_generation_policy,
    resolve_max_output_tokens,
)
from packages.database.models import AIBudgetRecord
from packages.database.session import get_async_sessionmaker
from tests.m4a_helpers import create_ai_stack, mock_factory


def test_generation_policy_uses_route_value_before_code_fallback() -> None:
    config = {
        "max_retry_delay_seconds": 1,
        "generation_policy": {"max_output_tokens": 8192},
    }
    assert resolve_max_output_tokens(route_config=config, fallback=4096) == 8192
    assert resolve_max_output_tokens(route_config={}, fallback=4096) == 4096


def test_generation_policy_merge_preserves_unrelated_route_config() -> None:
    original = {
        "max_retry_delay_seconds": 1,
        "generation_policy": {"future_setting": "keep-me"},
        "other": {"enabled": True},
    }
    updated = merge_generation_policy(config=original, max_output_tokens=6000)
    assert updated["max_retry_delay_seconds"] == 1
    assert updated["other"] == {"enabled": True}
    assert updated["generation_policy"] == {
        "future_setting": "keep-me",
        "max_output_tokens": 6000,
    }

    cleared = merge_generation_policy(config=updated, max_output_tokens=None)
    assert cleared["generation_policy"] == {"future_setting": "keep-me"}


@pytest.mark.parametrize(
    "config",
    [
        {"generation_policy": "invalid"},
        {"generation_policy": {"max_output_tokens": True}},
        {"generation_policy": {"max_output_tokens": 0}},
        {"generation_policy": {"max_output_tokens": -1}},
        {"generation_policy": {"max_output_tokens": 12.5}},
    ],
)
def test_invalid_generation_policy_is_rejected_by_runtime_and_admin_schema(
    config: dict[str, object],
) -> None:
    with pytest.raises(AIGatewayError) as runtime_error:
        generation_policy_from_config(config)
    assert runtime_error.value.code is AIErrorCode.INVALID_REQUEST

    with pytest.raises(ValidationError):
        AITaskRouteUpdate(config=config)


@pytest.mark.usefixtures("clean_database")
async def test_gateway_sends_route_max_output_tokens_to_provider(db_session) -> None:  # type: ignore[no-untyped-def]
    _, _, _, route = await create_ai_stack(db_session)
    route.config = {
        **route.config,
        "generation_policy": {"max_output_tokens": 23},
    }
    await db_session.commit()
    seen_max_tokens: list[int | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_max_tokens.append(body.get("max_tokens"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "configured"}}],
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
        max_output_tokens=8,
    )

    assert result.text == "configured"
    assert seen_max_tokens == [23]


@pytest.mark.usefixtures("clean_database")
async def test_gateway_budget_reservation_uses_same_effective_route_limit(db_session) -> None:  # type: ignore[no-untyped-def]
    _, _, _, route = await create_ai_stack(db_session)
    route.config = {
        **route.config,
        "generation_policy": {"max_output_tokens": 23},
    }
    db_session.add(
        AIBudgetRecord(
            scope_type="task",
            scope_key="draft_generation",
            enabled=True,
            daily_token_limit=20,
            unknown_usage_policy="block",
            config={},
            updated_by="test",
        )
    )
    await db_session.commit()
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "should-not-run"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    with pytest.raises(AIGatewayError) as caught:
        await gateway.generate_text(
            task_key="draft_generation",
            messages=(AIMessage(role="user", content="hello"),),
            max_output_tokens=8,
        )

    assert caught.value.code is AIErrorCode.BUDGET_EXCEEDED
    assert provider_calls == 0
