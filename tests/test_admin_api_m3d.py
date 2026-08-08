import httpx
import pytest
from sqlalchemy import func, select

from apps.api.main import app
from packages.common.config import get_settings
from packages.database.models import (
    ClusteringProcessingRunRecord,
    EventRecord,
    EventSignalRecord,
)
from tests.m3c_helpers import create_m3c_signal, create_source

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m3d-api-test"}


@pytest.mark.usefixtures("clean_database")
async def test_m3d_admin_endpoints_require_admin_token() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        evaluation = await client.post("/api/v1/admin/clustering/evaluate", json={})
        preview = await client.post(
            "/api/v1/admin/clustering/reprocess/preview",
            json={
                "signal_ids": ["00000000-0000-0000-0000-000000000001"],
                "algorithm_version": "event-match-v1",
                "max_items": 1,
            },
        )
        apply = await client.post(
            "/api/v1/admin/clustering/reprocess",
            json={
                "signal_ids": ["00000000-0000-0000-0000-000000000001"],
                "algorithm_version": "event-match-v1",
                "max_items": 1,
                "confirmation": True,
            },
        )
    assert evaluation.status_code == 401
    assert preview.status_code == 401
    assert apply.status_code == 401


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_apply_requires_actor_and_confirmation(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session,
        source,
        external_id="m3d-api-guard",
        title="受保护的重处理输入",
        text="仅用于验证写操作门槛",
    )
    payload = {
        "signal_ids": [str(signal.id)],
        "algorithm_version": "event-match-v1",
        "max_items": 1,
        "confirmation": True,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        no_actor = await client.post(
            "/api/v1/admin/clustering/reprocess",
            headers=ADMIN_HEADERS,
            json=payload,
        )
        no_confirmation = await client.post(
            "/api/v1/admin/clustering/reprocess",
            headers=WRITE_HEADERS,
            json={**payload, "confirmation": False},
        )
    assert no_actor.status_code == 422
    assert no_confirmation.status_code == 422


@pytest.mark.usefixtures("clean_database")
async def test_evaluation_api_only_uses_registered_dataset_and_policy() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/clustering/evaluate",
            headers=ADMIN_HEADERS,
            json={
                "dataset_version": "m3-clustering-eval-v1",
                "algorithm_version": "event-match-v1",
                "threshold_sweep": True,
            },
        )
        unknown_dataset = await client.post(
            "/api/v1/admin/clustering/evaluate",
            headers=ADMIN_HEADERS,
            json={"dataset_version": "unknown-dataset"},
        )
        unknown_policy = await client.post(
            "/api/v1/admin/clustering/evaluate",
            headers=ADMIN_HEADERS,
            json={"algorithm_version": "event-match-v2"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_kind"] == "OFFLINE ENGINEERING EVALUATION"
    assert body["dataset_version"] == "m3-clustering-eval-v1"
    assert body["algorithm_version"] == "event-match-v1"
    assert body["threshold_sweep_read_only"] is True
    assert body["production_policy_modified"] is False
    assert "raw_payload" not in response.text
    assert '"embedding"' not in response.text.casefold()
    assert unknown_dataset.status_code == 422
    assert unknown_policy.status_code == 422


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_preview_is_bounded_dry_run_without_business_mutation(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session,
        source,
        external_id="m3d-api-preview",
        title="预览不会创建事件",
        text="dry-run 只允许写 processing audit",
    )
    before_event_count = int(
        await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0
    )
    before_membership_count = int(
        await db_session.scalar(select(func.count()).select_from(EventSignalRecord)) or 0
    )
    await db_session.rollback()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/clustering/reprocess/preview",
            headers=ADMIN_HEADERS,
            json={
                "signal_ids": [str(signal.id)],
                "algorithm_version": "event-match-v1",
                "max_items": 1,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["scanned"] == 1
    assert body["would_create_event"] == 1
    assert body["would_detach"] == 0
    assert int(
        await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0
    ) == before_event_count
    assert int(
        await db_session.scalar(select(func.count()).select_from(EventSignalRecord)) or 0
    ) == before_membership_count
    assert int(
        await db_session.scalar(select(func.count()).select_from(ClusteringProcessingRunRecord))
        or 0
    ) == 1
