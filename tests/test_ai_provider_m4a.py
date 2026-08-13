from __future__ import annotations

import json
import os
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from packages.ai_gateway.domain import (
    AIMessage,
    AIModelTarget,
    StructuredProviderRequest,
    TextProviderRequest,
)
from packages.ai_gateway.errors import AIErrorCode, AIProviderError
from packages.ai_gateway.openai_compatible import OpenAICompatibleProvider
from tests.m4a_helpers import allow_test_host


def target(*, structured_output_mode: str | None = None) -> AIModelTarget:
    os.environ["M4A_TEST_KEY"] = "super-secret-test-key"
    return AIModelTarget(
        model_id=uuid4(),
        provider_id=uuid4(),
        provider_key="provider-under-test",
        provider_type="openai_compatible",
        base_url="https://provider.test/v1",
        credential_ref="env://M4A_TEST_KEY",
        provider_timeout_seconds=5,
        provider_retry_limit=1,
        provider_config={},
        model_key="internal-model",
        model_name="vendor-model",
        capabilities=("text_generation", "structured_output"),
        dimensions=None,
        input_price_per_million=Decimal("1"),
        output_price_per_million=Decimal("2"),
        embedding_price_per_million=None,
        pricing_version="pricing-v1",
        model_config=(
            {"structured_output_mode": structured_output_mode}
            if structured_output_mode is not None
            else {}
        ),
    )


async def test_openai_compatible_success_parses_usage_and_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer super-secret-test-key"
        body = json.loads(request.content)
        assert body["model"] == "vendor-model"
        return httpx.Response(
            200,
            json={
                "id": "body-id",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
            headers={"x-request-id": "req-123"},
        )

    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        host_validator=allow_test_host,
    )
    result = await adapter.generate_text(
        target=target(),
        request=TextProviderRequest(messages=(AIMessage(role="user", content="hello"),)),
        timeout_seconds=2,
    )
    assert result.text == "ok"
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 2
    assert result.usage.total_tokens == 5
    assert result.provider_request_id == "req-123"


@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (401, AIErrorCode.AUTH_ERROR, False),
        (429, AIErrorCode.RATE_LIMITED, True),
        (404, AIErrorCode.MODEL_NOT_FOUND, False),
        (500, AIErrorCode.PROVIDER_UNAVAILABLE, True),
    ],
)
async def test_openai_compatible_maps_http_errors(
    status: int,
    expected: AIErrorCode,
    retryable: bool,
) -> None:
    headers = {"retry-after": "0"} if status == 429 else {}
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers)),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )
    assert caught.value.code is expected
    assert caught.value.retryable is retryable


async def test_openai_compatible_400_preserves_sanitized_provider_diagnostic() -> None:
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_parameter",
                        "param": "max_tokens",
                        "message": "max_tokens must be greater than zero",
                    }
                },
            )
        ),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )

    assert caught.value.code is AIErrorCode.INVALID_REQUEST
    assert caught.value.provider_error_detail == {
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "invalid_parameter",
        "provider_error_param": "max_tokens",
        "provider_error_message": "max_tokens must be greater than zero",
    }


async def test_openai_compatible_422_is_invalid_request_with_redacted_diagnostic() -> None:
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                422,
                json={
                    "error": {
                        "type": "validation_error",
                        "message": "Bearer ds-0123456789abcdef and token=abcdef0123456789 are invalid",
                    }
                },
            )
        ),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )

    assert caught.value.code is AIErrorCode.INVALID_REQUEST
    detail = caught.value.provider_error_detail
    assert detail is not None
    assert detail["provider_error_type"] == "validation_error"
    assert "ds-0123456789abcdef" not in repr(detail)
    assert "abcdef0123456789" not in repr(detail)
    assert "[REDACTED]" in detail["provider_error_message"]


async def test_structured_parse_failure_keeps_safe_response_diagnostic_and_usage() -> None:
    response_content = '{"ok":'
    reasoning_content = "private chain of thought"
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"x-request-id": "req-structured-invalid"},
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
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                },
            )
        ),
        host_validator=allow_test_host,
    )

    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_structured(
            target=target(structured_output_mode="json_object"),
            request=StructuredProviderRequest(
                messages=(AIMessage(role="user", content="x"),),
                schema={"type": "object"},
                schema_name="test_schema",
            ),
            timeout_seconds=1,
        )

    error = caught.value
    assert error.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID
    assert error.provider_request_id == "req-structured-invalid"
    assert error.provider_usage is not None
    assert error.provider_usage.total_tokens == 12
    assert error.provider_response_detail == {
        "provider_request_id": "req-structured-invalid",
        "finish_reason": "length",
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "content_empty": False,
        "content_length": len(response_content),
        "reasoning_content_present": True,
        "reasoning_content_length": len(reasoning_content),
    }
    assert response_content not in repr(error.provider_response_detail)
    assert reasoning_content not in repr(error.provider_response_detail)


async def test_structured_empty_content_keeps_only_empty_response_diagnostic() -> None:
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": ""}}]},
            )
        ),
        host_validator=allow_test_host,
    )

    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_structured(
            target=target(),
            request=StructuredProviderRequest(
                messages=(AIMessage(role="user", content="x"),),
                schema={"type": "object"},
                schema_name="test_schema",
            ),
            timeout_seconds=1,
        )

    assert caught.value.provider_response_detail == {
        "content_empty": True,
        "content_length": 0,
        "reasoning_content_present": False,
    }


async def test_openai_compatible_malformed_error_body_never_becomes_diagnostic() -> None:
    raw_body = "Authorization: Bearer super-secret-test-key"
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(400, text=raw_body)),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )

    assert caught.value.code is AIErrorCode.INVALID_REQUEST
    assert caught.value.provider_error_detail is None
    assert raw_body not in str(caught.value)


async def test_openai_compatible_timeout_and_network_are_retryable() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timeout_adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(timeout_handler),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as timeout_error:
        await timeout_adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )
    assert timeout_error.value.code is AIErrorCode.TIMEOUT
    assert timeout_error.value.retryable is True

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    network_adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(network_handler),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as network_error:
        await network_adapter.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )
    assert network_error.value.code is AIErrorCode.NETWORK_ERROR
    assert network_error.value.retryable is True


async def test_openai_compatible_rejects_malformed_json_and_refusal() -> None:
    malformed = OpenAICompatibleProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as malformed_error:
        await malformed.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )
    assert malformed_error.value.code is AIErrorCode.INVALID_RESPONSE

    refusal = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"refusal": "no", "content": ""}}]},
            )
        ),
        host_validator=allow_test_host,
    )
    with pytest.raises(AIProviderError) as refusal_error:
        await refusal.generate_text(
            target=target(),
            request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
            timeout_seconds=1,
        )
    assert refusal_error.value.code is AIErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize("mode", [None, "json_object"])
async def test_openai_compatible_structured_invalid_json_is_explicit(
    mode: str | None,
) -> None:
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{bad-json"}}]},
            )
        ),
        host_validator=allow_test_host,
    )
    request = StructuredProviderRequest(
        messages=(AIMessage(role="user", content="x"),),
        schema={"type": "object"},
        schema_name="test_schema",
    )
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_structured(
            target=target(structured_output_mode=mode),
            request=request,
            timeout_seconds=1,
        )
    assert caught.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID
    assert caught.value.retryable is True


async def test_structured_output_defaults_to_strict_json_schema_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "test_schema",
                "strict": True,
                "schema": {"type": "object"},
            },
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        host_validator=allow_test_host,
    )
    result = await adapter.generate_structured(
        target=target(),
        request=StructuredProviderRequest(
            messages=(AIMessage(role="user", content="x"),),
            schema={"type": "object"},
            schema_name="test_schema",
        ),
        timeout_seconds=1,
    )
    assert result.data == {}


async def test_structured_output_json_object_payload_has_no_json_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "json_schema" not in body["response_format"]
        assert body["messages"][0]["role"] == "system"
        assert "Return only a JSON object" in body["messages"][0]["content"]
        assert '"required":["name"]' in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"name":"ok"}'}}]},
        )

    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        host_validator=allow_test_host,
    )
    result = await adapter.generate_structured(
        target=target(structured_output_mode="json_object"),
        request=StructuredProviderRequest(
            messages=(AIMessage(role="user", content="x"),),
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            schema_name="test_schema",
        ),
        timeout_seconds=1,
    )
    assert result.data == {"name": "ok"}


async def test_structured_output_unknown_mode_fails_closed() -> None:
    adapter = OpenAICompatibleProvider(host_validator=allow_test_host)
    with pytest.raises(AIProviderError) as caught:
        await adapter.generate_structured(
            target=target(structured_output_mode="vendor_default"),
            request=StructuredProviderRequest(
                messages=(AIMessage(role="user", content="x"),),
                schema={"type": "object"},
                schema_name="test_schema",
            ),
            timeout_seconds=1,
        )
    assert caught.value.code is AIErrorCode.INVALID_REQUEST


async def test_usage_can_be_unknown_without_fabricating_zero() -> None:
    adapter = OpenAICompatibleProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
            )
        ),
        host_validator=allow_test_host,
    )
    result = await adapter.generate_text(
        target=target(),
        request=TextProviderRequest(messages=(AIMessage(role="user", content="x"),)),
        timeout_seconds=1,
    )
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None
