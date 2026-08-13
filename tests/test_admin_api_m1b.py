import httpx
import pytest
from sqlalchemy import select

from apps.api.main import app
from packages.common.config import get_settings
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.database.models import ConfigurationChangeLog, ConnectorDefinition

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}


async def _account_with_references(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "weibo")
    )
    assert definition is not None
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="API 微博实例",
        config={"modes": ["search"], "keyword": "AI 编辑部"},
        schedule_config={},
        actor="admin",
    )
    return await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform="weibo",
        display_name="API 测试账号",
        account_identifier="api-account-1",
        credential_ref="secret://weibo/api-account-1",
        browser_profile_ref="profile://weibo/api-account-1",
        actor="admin",
    )


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
async def test_definition_runtime_switch_requires_actor_and_survives_sync(db_session) -> None:  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(select(ConnectorDefinition).limit(1))
    assert definition is not None
    definition_id = definition.id
    await db_session.commit()
    transport = httpx.ASGITransport(app=app)
    headers = {**ADMIN_HEADERS, "X-Actor-ID": "definition-operator"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing_actor = await client.post(
            f"/api/v1/admin/connector-definitions/{definition_id}/disable",
            headers=ADMIN_HEADERS,
        )
        assert missing_actor.status_code == 422
        disabled = await client.post(
            f"/api/v1/admin/connector-definitions/{definition_id}/disable",
            headers=headers,
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["is_enabled"] is False

    await ConnectorDefinitionSyncService(db_session).sync()
    await db_session.refresh(definition)
    assert definition.is_enabled is False

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        enabled = await client.post(
            f"/api/v1/admin/connector-definitions/{definition_id}/enable",
            headers=headers,
        )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["is_enabled"] is True
    audit = await db_session.scalar(
        select(ConfigurationChangeLog).where(
            ConfigurationChangeLog.entity_id == definition_id,
            ConfigurationChangeLog.action == "disable",
        )
    )
    assert audit is not None
    assert audit.actor == "definition-operator"


@pytest.mark.usefixtures("clean_database")
async def test_account_references_can_be_cleared_without_api_or_audit_leak(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account_with_references(db_session)
    account_id = account.id
    credential_reference = account.credential_ref
    browser_profile_reference = account.browser_profile_ref
    headers = {**ADMIN_HEADERS, "X-Actor-ID": "api-editor"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/admin/platform-accounts/{account_id}",
            headers=headers,
            json={"credential_ref": None, "browser_profile_ref": None},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["credential_configured"] is False
    assert payload["browser_profile_configured"] is False
    assert "credential_ref" not in payload
    assert "browser_profile_ref" not in payload
    assert credential_reference not in response.text
    assert browser_profile_reference not in response.text

    await db_session.refresh(account)
    assert account.credential_ref is None
    assert account.browser_profile_ref is None
    assert account.updated_by == "api-editor"

    audit = await db_session.scalar(
        select(ConfigurationChangeLog).where(
            ConfigurationChangeLog.entity_id == account_id,
            ConfigurationChangeLog.action == "update",
        )
    )
    assert audit is not None
    assert audit.after_data["credential_reference_changed"] is True
    assert audit.after_data["browser_profile_reference_changed"] is True
    assert audit.after_data["has_credential_reference"] is False
    assert audit.after_data["browser_profile_configured"] is False
    audit_text = f"{audit.before_data}{audit.after_data}"
    assert credential_reference not in audit_text
    assert browser_profile_reference not in audit_text


@pytest.mark.usefixtures("clean_database")
async def test_health_endpoints_remain_public() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200