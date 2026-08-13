from __future__ import annotations

import os

import httpx
import pytest

from apps.api.main import app
from packages.common.config import get_settings

ADMIN_HEADERS = {
    "X-Admin-Token": get_settings().admin_token_value,
    "X-Actor-ID": "m4a-api-test",
}


@pytest.mark.usefixtures("clean_database")
async def test_ai_admin_api_requires_admin_token() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/ai/providers")
    assert response.status_code == 401


@pytest.mark.usefixtures("clean_database")
async def test_provider_api_never_returns_credential_or_secret() -> None:
    os.environ["M4A_API_KEY"] = "sk-secret-never-returned"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/admin/ai/providers",
            headers=ADMIN_HEADERS,
            json={
                "provider_key": "api-provider",
                "display_name": "API Provider",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example/v1",
                "credential_ref": "env://M4A_API_KEY",
                "enabled": False,
                "config": {},
            },
        )
        assert created.status_code == 201, created.text
        provider_id = created.json()["id"]
        fetched = await client.get(
            f"/api/v1/admin/ai/providers/{provider_id}",
            headers=ADMIN_HEADERS,
        )
    assert fetched.status_code == 200
    text = fetched.text
    body = fetched.json()
    assert body["credential_configured"] is True
    assert body["credential_ref_masked"] == "env://***"
    assert "M4A_API_KEY" not in text
    assert "sk-secret-never-returned" not in text
    assert "credential_ref\"" not in text
    assert "authorization" not in text.casefold()


@pytest.mark.usefixtures("clean_database")
async def test_provider_config_rejects_inline_api_key() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/ai/providers",
            headers=ADMIN_HEADERS,
            json={
                "provider_key": "unsafe-provider",
                "display_name": "Unsafe Provider",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example/v1",
                "enabled": False,
                "config": {"api_key": "must-not-store"},
            },
        )
    assert response.status_code == 400
    assert "must-not-store" not in response.text


@pytest.mark.usefixtures("clean_database")
async def test_connection_test_without_credential_is_explicit_not_tested() -> None:
    os.environ.pop("M4A_MISSING_KEY", None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        provider_response = await client.post(
            "/api/v1/admin/ai/providers",
            headers=ADMIN_HEADERS,
            json={
                "provider_key": "missing-credential-provider",
                "display_name": "Missing Credential",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example/v1",
                "credential_ref": "env://M4A_MISSING_KEY",
                "enabled": True,
                "config": {},
            },
        )
        assert provider_response.status_code == 201, provider_response.text
        provider = provider_response.json()
        model_response = await client.post(
            "/api/v1/admin/ai/models",
            headers=ADMIN_HEADERS,
            json={
                "provider_id": provider["id"],
                "model_key": "tiny-test-model",
                "model_name": "vendor-test-model",
                "capabilities": ["text_generation"],
                "enabled": True,
                "pricing_version": "unknown",
                "config": {},
            },
        )
        assert model_response.status_code == 201, model_response.text
        tested = await client.post(
            f"/api/v1/admin/ai/providers/{provider['id']}/test",
            headers=ADMIN_HEADERS,
            json={"model_id": model_response.json()["id"]},
        )
        fetched = await client.get(
            f"/api/v1/admin/ai/providers/{provider['id']}",
            headers=ADMIN_HEADERS,
        )
    assert tested.status_code == 200
    assert tested.json()["status"] == "failed"
    assert tested.json()["error_code"] == "CREDENTIAL_NOT_CONFIGURED"
    assert fetched.json()["validation_status"] == "NOT_TESTED"


@pytest.mark.usefixtures("clean_database")
async def test_model_api_rejects_unknown_structured_output_mode() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        provider = await client.post(
            "/api/v1/admin/ai/providers",
            headers=ADMIN_HEADERS,
            json={
                "provider_key": "mode-provider",
                "display_name": "Mode Provider",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example/v1",
                "enabled": False,
                "config": {},
            },
        )
        assert provider.status_code == 201, provider.text
        response = await client.post(
            "/api/v1/admin/ai/models",
            headers=ADMIN_HEADERS,
            json={
                "provider_id": provider.json()["id"],
                "model_key": "mode-model",
                "model_name": "mode-model",
                "capabilities": ["structured_output"],
                "config": {"structured_output_mode": "vendor_default"},
            },
        )
    assert response.status_code == 400
    assert "vendor_default" not in response.text
