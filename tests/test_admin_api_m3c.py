import httpx
import pytest
from sqlalchemy import func, select

from apps.api.main import app
from packages.common.config import get_settings
from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    SignalFingerprintRecord,
    SignalMatchDecisionRecord,
)
from packages.events.services import EventService
from tests.m3c_helpers import create_m3c_signal, create_source

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m3c-api-test"}


@pytest.mark.usefixtures("clean_database")
async def test_clustering_admin_api_requires_admin_token() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post(
            "/api/v1/admin/clustering/preview",
            json={"signal_id": "00000000-0000-0000-0000-000000000001"},
        )
        cluster = await client.post(
            "/api/v1/admin/clustering/signals/00000000-0000-0000-0000-000000000001",
            json={},
        )
    assert preview.status_code == 401
    assert cluster.status_code == 401


@pytest.mark.usefixtures("clean_database")
async def test_clustering_write_requires_actor() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/clustering/signals/00000000-0000-0000-0000-000000000001",
            headers=ADMIN_HEADERS,
            json={},
        )
    assert response.status_code == 400


@pytest.mark.usefixtures("clean_database")
async def test_preview_is_side_effect_free_and_returns_no_raw_payload_or_vector(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="preview-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="preview-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营。最新",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/clustering/preview",
            headers=ADMIN_HEADERS,
            json={"signal_id": str(first.id)},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["signal_id"] == str(first.id)
    assert any(item["candidate_signal_id"] == str(second.id) for item in body["decisions"])
    assert "raw_payload" not in response.text
    assert '"vector"' not in response.text.casefold()
    assert int(
        await db_session.scalar(select(func.count()).select_from(SignalFingerprintRecord)) or 0
    ) == 0
    assert int(
        await db_session.scalar(select(func.count()).select_from(SignalMatchDecisionRecord)) or 0
    ) == 0
    assert int(await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0) == 0
    assert int(
        await db_session.scalar(select(func.count()).select_from(EventSignalRecord)) or 0
    ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_execute_cluster_and_batch_endpoints(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session, source, external_id="api-cluster-a", title="事件A", text="事件A正文"
    )
    second = await create_m3c_signal(
        db_session, source, external_id="api-cluster-b", title="事件B", text="完全不同正文"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        one = await client.post(
            f"/api/v1/admin/clustering/signals/{first.id}",
            headers=WRITE_HEADERS,
            json={},
        )
        batch = await client.post(
            "/api/v1/admin/clustering/batch",
            headers=WRITE_HEADERS,
            json={"signal_ids": [str(second.id)], "batch_size": 1},
        )
    assert one.status_code == 200
    assert one.json()["status"] == "created_event"
    assert batch.status_code == 200
    assert batch.json()["processed"] == 1
    assert batch.json()["failed"] == 0


@pytest.mark.usefixtures("clean_database")
async def test_merge_and_split_admin_endpoints(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signals = [
        await create_m3c_signal(
            db_session,
            source,
            external_id=f"api-merge-split-{index}",
            title=f"Signal {index}",
            text=f"正文 {index}",
        )
        for index in range(3)
    ]

    service = EventService(db_session)
    target = await service.create(
        title="Target",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )
    source_event = await service.create(
        title="Source",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )
    await service.attach_signal(
        event_id=target.id,
        signal_id=signals[0].id,
        relation=EventSignalRelation.RELATED,
        confidence=1.0,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )
    for signal in signals[1:]:
        await service.attach_signal(
            event_id=source_event.id,
            signal_id=signal.id,
            relation=EventSignalRelation.RELATED,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        merged = await client.post(
            f"/api/v1/admin/events/{target.id}/merge",
            headers=WRITE_HEADERS,
            json={"source_event_id": str(source_event.id), "reason": "same incident"},
        )
        split = await client.post(
            f"/api/v1/admin/events/{target.id}/split",
            headers=WRITE_HEADERS,
            json={
                "signal_ids": [str(signals[2].id)],
                "title": "Split Event",
                "reason": "human correction",
            },
        )
    assert merged.status_code == 200
    assert split.status_code == 201
    await db_session.refresh(source_event)
    assert source_event.merged_into_event_id == target.id
    assert split.json()["id"] != str(target.id)
