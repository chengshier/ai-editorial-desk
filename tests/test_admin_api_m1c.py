from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from apps.api.main import app
from apps.api.routers.admin.collector_runtime import get_collector_runtime
from packages.collector_runtime import CollectorRuntime
from packages.common.config import get_settings
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import (
    BaseConnector,
    CollectionResult,
    CollectRequest,
    RawSignal,
)
from packages.connectors.manual import ManualURLConnector
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import ConnectorDefinition
from packages.database.session import get_async_sessionmaker

ADMIN_HEADERS = {
    "X-Admin-Token": get_settings().admin_token_value,
    "X-Actor-ID": "api-tester",
}


class APIFakeRSSConnector(BaseConnector):
    connector_type = "rss"

    async def health_check(self) -> dict[str, object]:
        return {"implemented": True}

    async def collect(self, request: CollectRequest) -> CollectionResult:
        return CollectionResult(
            signals=(
                RawSignal(
                    platform="rss",
                    external_id="api-entry-1",
                    url="https://example.com/article?utm_source=test",
                    title="API signal",
                    text="API body",
                    published_at=datetime(2026, 8, 6, tzinfo=UTC),
                    raw_payload={"authorization": "must-redact", "safe": "yes"},
                ),
            ),
            checkpoint={"etag": '"api"'},
            metadata={"fetch_status": "fetched"},
        )


async def _enabled_instance(db_session, connector_type: str):  # type: ignore[no-untyped-def]
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == connector_type
        )
    )
    assert definition is not None
    definition_id = definition.id
    config = (
        {"feed_urls": ["https://example.com/feed.xml"]}
        if connector_type == "rss"
        else {}
    )
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"api-{connector_type}-{uuid4()}",
        config=config,
        schedule_config={},
        actor="admin",
    )
    return await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )


def _runtime_override() -> CollectorRuntime:
    registry = ConnectorRegistry()
    registry.register("rss", APIFakeRSSConnector)
    registry.register("manual", ManualURLConnector)
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )


@pytest.mark.usefixtures("clean_database")
async def test_m1c_admin_api_closed_loop(db_session) -> None:  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    rss_instance = await _enabled_instance(db_session, "rss")
    manual_instance = await _enabled_instance(db_session, "manual")
    app.dependency_overrides[get_collector_runtime] = _runtime_override
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthorized = await client.get("/api/v1/admin/sources")
            assert unauthorized.status_code == 401

            definitions = await client.get(
                "/api/v1/admin/connector-definitions?page_size=100",
                headers=ADMIN_HEADERS,
            )
            assert definitions.status_code == 200
            by_type = {
                item["connector_type"]: item
                for item in definitions.json()["items"]
            }
            assert by_type["rss"]["implemented"] is True
            assert by_type["manual"]["implemented"] is True
            assert by_type["reddit"]["implemented"] is False
            assert by_type["rss"]["validated"] is False

            missing_actor = await client.post(
                "/api/v1/admin/sources",
                headers={"X-Admin-Token": get_settings().admin_token_value},
                json={
                    "connector_instance_id": str(rss_instance.id),
                    "name": "missing actor",
                    "source_type": "rss",
                    "mode": "feed",
                    "scope_key": "missing-actor",
                    "external_ref": "https://example.com/feed.xml",
                    "config": {},
                },
            )
            assert missing_actor.status_code == 422

            source_response = await client.post(
                "/api/v1/admin/sources",
                headers=ADMIN_HEADERS,
                json={
                    "connector_instance_id": str(rss_instance.id),
                    "name": "API Feed",
                    "source_type": "rss",
                    "mode": "feed",
                    "scope_key": "api-feed",
                    "external_ref": "https://example.com/feed.xml",
                    "config": {},
                    "enabled": True,
                },
            )
            assert source_response.status_code == 201
            source_id = source_response.json()["id"]

            sensitive = await client.post(
                "/api/v1/admin/sources",
                headers=ADMIN_HEADERS,
                json={
                    "connector_instance_id": str(rss_instance.id),
                    "name": "unsafe",
                    "source_type": "rss",
                    "mode": "feed",
                    "scope_key": "unsafe-feed",
                    "external_ref": "https://example.com/unsafe.xml",
                    "config": {"access_token": "plaintext"},
                },
            )
            assert sensitive.status_code == 400
            assert "plaintext" not in sensitive.text

            test_run = await client.post(
                f"/api/v1/admin/connector-instances/{rss_instance.id}/test-runs",
                headers=ADMIN_HEADERS,
                json={
                    "source_id": source_id,
                    "requested_limit": 5,
                    "dry_run": False,
                },
            )
            assert test_run.status_code == 200
            assert test_run.json()["status"] == "succeeded"
            assert test_run.json()["inserted_count"] == 1
            run_id = test_run.json()["run_id"]

            run_detail = await client.get(
                f"/api/v1/admin/connector-runs/{run_id}",
                headers=ADMIN_HEADERS,
            )
            assert run_detail.status_code == 200
            assert run_detail.json()["source_id"] == source_id
            assert run_detail.json()["failed_count"] == 0

            signals = await client.get(
                f"/api/v1/admin/raw-signals?source_id={source_id}",
                headers=ADMIN_HEADERS,
            )
            assert signals.status_code == 200
            assert signals.json()["total"] == 1
            signal = signals.json()["items"][0]
            assert signal["original_url"].endswith("utm_source=test")
            assert signal["canonical_url"] == "https://example.com/article"
            assert signal["raw_payload"]["authorization"] == "[REDACTED]"
            assert "must-redact" not in signals.text

            budget = await client.post(
                "/api/v1/admin/collection-budgets",
                headers=ADMIN_HEADERS,
                json={
                    "scope_type": "task",
                    "scope_key": source_id,
                    "max_runs_per_day": 5,
                    "max_items_per_run": 10,
                    "max_items_per_day": 50,
                    "max_concurrency": 1,
                    "timezone": "UTC",
                },
            )
            assert budget.status_code == 201
            budget_id = budget.json()["id"]
            patched = await client.patch(
                f"/api/v1/admin/collection-budgets/{budget_id}",
                headers=ADMIN_HEADERS,
                json={"max_runs_per_day": 6},
            )
            assert patched.status_code == 200
            assert patched.json()["max_runs_per_day"] == 6

            manual_payload = {
                "connector_instance_id": str(manual_instance.id),
                "url": "HTTPS://Example.COM:443/manual?utm_campaign=x",
                "title": "Manual title",
                "text": "Manual body",
                "fetch_metadata": False,
            }
            manual_first = await client.post(
                "/api/v1/admin/manual-imports",
                headers=ADMIN_HEADERS,
                json=manual_payload,
            )
            assert manual_first.status_code == 200
            assert manual_first.json()["duplicate"] is False
            assert manual_first.json()["normalized_url"] == "https://example.com/manual"
            manual_second = await client.post(
                "/api/v1/admin/manual-imports",
                headers=ADMIN_HEADERS,
                json=manual_payload,
            )
            assert manual_second.status_code == 200
            assert manual_second.json()["duplicate"] is True
            assert manual_second.json()["signal_id"] == manual_first.json()["signal_id"]

            too_large = await client.get(
                "/api/v1/admin/raw-signals?page_size=101",
                headers=ADMIN_HEADERS,
            )
            assert too_large.status_code == 422
    finally:
        app.dependency_overrides.pop(get_collector_runtime, None)
