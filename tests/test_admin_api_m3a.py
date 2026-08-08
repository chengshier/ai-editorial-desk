from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from apps.api.main import app
from packages.common.config import get_settings
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import ConnectorDefinition, RawSignalRecord
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m3a-api-editor"}


async def _signal(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="M3-A API RSS",
        config={"feed_urls": ["https://example.com/m3a-api.xml"]},
        schedule_config={},
        actor="m3a-api-test",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M3-A API Source",
        source_type="rss",
        mode="feed",
        scope_key="https://example.com/m3a-api.xml",
        external_ref="https://example.com/m3a-api.xml",
        config={},
        enabled=True,
        actor="m3a-api-test",
    )
    raw = RawSignal(
        platform="rss",
        external_id="m3a-api-signal",
        url="https://example.com/m3a-api-signal",
        title="M3-A API Signal",
        text="API 测试正文",
        published_at=datetime(2026, 8, 7, 8, 30, tzinfo=UTC),
        raw_payload={"token": "must-redact", "safe": "visible-in-db-only"},
        language="zh-CN",
    )
    normalized = NormalizedSignal.from_connector_signal(
        source_id=source.id,
        connector_instance_id=source.connector_instance_id,
        connector_run_id=None,
        connector_type="rss",
        signal=raw,
        canonical_url=normalize_http_url(raw.url),
    )
    result = (await RawSignalService(db_session).ingest_many([normalized]))[0]
    stored = await db_session.get(RawSignalRecord, result.signal_id)
    assert stored is not None
    return stored


@pytest.mark.usefixtures("clean_database")
async def test_event_api_requires_admin_token_and_actor() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/api/v1/admin/events")
        assert unauthorized.status_code == 401

        missing_actor = await client.post(
            "/api/v1/admin/events",
            headers=ADMIN_HEADERS,
            json={"title": "缺少 Actor"},
        )
        assert missing_actor.status_code == 422
        assert missing_actor.json()["error"]["code"] == "actor_required"


@pytest.mark.usefixtures("clean_database")
async def test_event_api_create_list_detail_status_and_pagination() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/admin/events",
            headers=WRITE_HEADERS,
            json={"title": "人工事件一"},
        )
        second = await client.post(
            "/api/v1/admin/events",
            headers=WRITE_HEADERS,
            json={"title": "人工事件二", "status": "stable"},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["first_seen_at"] is None
        assert first.json()["summary"] is None
        assert first.json()["source_count"] == 0
        assert first.json()["platform_count"] == 0

        page = await client.get(
            "/api/v1/admin/events?page=1&page_size=1",
            headers=ADMIN_HEADERS,
        )
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert page.json()["has_next"] is True

        stable = await client.get(
            "/api/v1/admin/events?status=stable",
            headers=ADMIN_HEADERS,
        )
        assert stable.status_code == 200
        assert [item["id"] for item in stable.json()["items"]] == [second.json()["id"]]

        detail = await client.get(
            f"/api/v1/admin/events/{first.json()['id']}",
            headers=ADMIN_HEADERS,
        )
        assert detail.status_code == 200
        assert detail.json()["title"] == "人工事件一"

        invalid_page = await client.get(
            "/api/v1/admin/events?page_size=101",
            headers=ADMIN_HEADERS,
        )
        assert invalid_page.status_code == 422


@pytest.mark.usefixtures("clean_database")
async def test_event_signal_api_attach_duplicate_list_detach_and_data_safety(db_session) -> None:  # type: ignore[no-untyped-def]
    signal = await _signal(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event_response = await client.post(
            "/api/v1/admin/events",
            headers=WRITE_HEADERS,
            json={"title": "关联测试事件"},
        )
        event_id = event_response.json()["id"]
        payload = {
            "signal_id": str(signal.id),
            "relation": "origin",
            "confidence": 0.88,
            "attached_by": "human",
        }
        first = await client.post(
            f"/api/v1/admin/events/{event_id}/signals",
            headers=WRITE_HEADERS,
            json=payload,
        )
        duplicate = await client.post(
            f"/api/v1/admin/events/{event_id}/signals",
            headers=WRITE_HEADERS,
            json={**payload, "relation": "report", "confidence": 0.2},
        )
        assert first.status_code == 200
        assert duplicate.status_code == 200
        assert first.json()["id"] == duplicate.json()["id"]
        assert duplicate.json()["relation"] == "origin"
        assert duplicate.json()["confidence"] == pytest.approx(0.88)
        assert "raw_payload" not in first.text
        assert "visible-in-db-only" not in first.text

        links = await client.get(
            f"/api/v1/admin/events/{event_id}/signals?page=1&page_size=1",
            headers=ADMIN_HEADERS,
        )
        assert links.status_code == 200
        assert links.json()["total"] == 1
        assert links.json()["items"][0]["signal_id"] == str(signal.id)
        assert "raw_payload" not in links.text

        detail = await client.get(
            f"/api/v1/admin/events/{event_id}", headers=ADMIN_HEADERS
        )
        assert detail.json()["source_count"] == 1
        assert detail.json()["platform_count"] == 1
        assert detail.json()["first_seen_at"].startswith("2026-08-07T08:30:00")

        detached = await client.delete(
            f"/api/v1/admin/events/{event_id}/signals/{signal.id}",
            headers=WRITE_HEADERS,
        )
        repeated_detach = await client.delete(
            f"/api/v1/admin/events/{event_id}/signals/{signal.id}",
            headers=WRITE_HEADERS,
        )
        assert detached.status_code == 204
        assert repeated_detach.status_code == 204

    assert await db_session.get(RawSignalRecord, signal.id) is not None


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    "payload",
    [
        {"relation": "report", "confidence": -0.1, "attached_by": "human"},
        {"relation": "report", "confidence": 1.1, "attached_by": "human"},
        {"relation": "unknown", "confidence": 1.0, "attached_by": "human"},
        {"relation": "report", "confidence": 1.0, "attached_by": "unknown"},
        {"relation": "report", "confidence": 1.0, "attached_by": "embedding"},
    ],
)
async def test_event_signal_api_rejects_invalid_confidence_relation_or_attached_by(
    db_session, payload: dict[str, object]
) -> None:  # type: ignore[no-untyped-def]
    signal = await _signal(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = await client.post(
            "/api/v1/admin/events",
            headers=WRITE_HEADERS,
            json={"title": "输入校验事件"},
        )
        response = await client.post(
            f"/api/v1/admin/events/{event.json()['id']}/signals",
            headers=WRITE_HEADERS,
            json={"signal_id": str(signal.id), **payload},
        )
    assert response.status_code == 422


@pytest.mark.usefixtures("clean_database")
async def test_event_signal_api_missing_raw_signal_returns_safe_404() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = await client.post(
            "/api/v1/admin/events",
            headers=WRITE_HEADERS,
            json={"title": "缺失信号事件"},
        )
        response = await client.post(
            f"/api/v1/admin/events/{event.json()['id']}/signals",
            headers=WRITE_HEADERS,
            json={
                "signal_id": "00000000-0000-0000-0000-000000000001",
                "relation": "report",
                "confidence": 1.0,
                "attached_by": "human",
            },
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"
    assert "database" not in response.text.casefold()
