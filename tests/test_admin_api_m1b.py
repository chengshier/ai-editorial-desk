import httpx
import pytest

from apps.api.main import app
from packages.connector_management.services import ConnectorDefinitionSyncService

ADMIN_HEADERS = {"X-Admin-Token": "test-only-admin-token-at-least-24-characters"}


@pytest.mark.usefixtures("clean_database")
async def test_admin_api_auth_actor_errors_and_pagination(db_session) -> None:  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/v1/admin/connector-definitions")
        assert missing.status_code == 401
        assert "token" not in missing.text.casefold()

        wrong = await client.get(
            "/api/v1/admin/connector-definitions",
            headers={"X-Admin-Token": "wrong-value"},
        )
        assert wrong.status_code == 401

        too_large = await client.get(
            "/api/v1/admin/connector-definitions?page_size=101",
            headers=ADMIN_HEADERS,
        )
        assert too_large.status_code == 422
        assert too_large.json()["error"]["code"] == "validation_error"

        valid = await client.get(
            "/api/v1/admin/connector-definitions?page_size=5",
            headers=ADMIN_HEADERS,
        )
        assert valid.status_code == 200
        assert len(valid.json()["items"]) == 5
        definition_id = valid.json()["items"][0]["id"]

        missing_actor = await client.post(
            "/api/v1/admin/connector-instances",
            headers=ADMIN_HEADERS,
            json={
                "definition_id": definition_id,
                "name": "测试实例",
                "config": {},
                "schedule_config": {},
            },
        )
        assert missing_actor.status_code == 422
        assert missing_actor.json()["error"]["code"] == "actor_required"

        not_found = await client.get(
            "/api/v1/admin/connector-definitions/00000000-0000-0000-0000-000000000000",
            headers=ADMIN_HEADERS,
        )
        assert not_found.status_code == 404
        assert not_found.json()["error"]["code"] == "resource_not_found"


@pytest.mark.usefixtures("clean_database")
async def test_health_endpoints_remain_public() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
