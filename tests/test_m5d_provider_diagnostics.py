from __future__ import annotations

import argparse
import asyncio
import importlib
import json
from uuid import uuid4


def test_validation_cli_emits_only_sanitized_connection_error_detail(
    monkeypatch,
    capsys,
) -> None:
    module = importlib.import_module("scripts.run_m5d_provider_validation")
    monkeypatch.delenv("CI", raising=False)
    invocation_id = uuid4()

    class FakeTester:
        def __init__(self, factory) -> None:
            del factory

        async def test(self, **kwargs):
            del kwargs
            return invocation_id, "failed", "INVALID_REQUEST"

        async def error_detail(self, value):
            assert value == invocation_id
            return {
                "provider_error_type": "invalid_request_error",
                "provider_error_param": "max_tokens",
                "provider_error_message": "value must be positive [REDACTED]",
            }

        async def response_detail(self, value):
            assert value == invocation_id
            return {
                "provider_request_id": "req-safe-detail",
                "finish_reason": "length",
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "content_empty": False,
                "content_length": 6,
                "reasoning_content_present": True,
            }

    async def dispose() -> None:
        return None

    monkeypatch.setattr(module, "AIConnectionTester", FakeTester)
    monkeypatch.setattr(module, "get_async_sessionmaker", lambda: object())
    monkeypatch.setattr(module, "dispose_database", dispose)

    result = asyncio.run(
        module._run(
            argparse.Namespace(
                provider_id=uuid4(),
                model_id=uuid4(),
                actor="m5d-human",
                business_invocation_id=None,
                confirm_paid_call=True,
            )
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["connection_test_error_code"] == "INVALID_REQUEST"
    assert payload["connection_test_error_detail"] == {
        "provider_error_type": "invalid_request_error",
        "provider_error_param": "max_tokens",
        "provider_error_message": "value must be positive [REDACTED]",
    }
    assert payload["connection_test_response_detail"] == {
        "provider_request_id": "req-safe-detail",
        "finish_reason": "length",
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "content_empty": False,
        "content_length": 6,
        "reasoning_content_present": True,
    }
    assert "Authorization" not in json.dumps(payload)
