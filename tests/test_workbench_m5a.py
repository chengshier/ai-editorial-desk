from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import event as sa_event

from apps.api.main import app
from packages.common.config import get_settings
from packages.database.session import get_async_engine
from packages.events.services import EventService
from packages.workbench.services import EditorialWorkbenchQueryService
from tests.m4d_helpers import create_m4d_context

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m5a-editor"}


@pytest.mark.usefixtures("clean_database")
async def test_workbench_api_filters_effective_override_merged_and_safe_projection(db_session) -> None:  # type: ignore[no-untyped-def]
    target = await create_m4d_context(db_session, title="M5 target event")
    source = await create_m4d_context(db_session, title="M5 source event")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft = await client.post(
            f"/api/v1/admin/events/{target.event.id}/drafts/manual",
            headers=WRITE_HEADERS,
            json={
                "event_card_id": str(target.card.id),
                "editorial_pack_id": str(target.pack.id),
                "draft_type": "short_30s",
                "reason": "M5-A filter fixture",
                "body": "监管部门确认已启动调查。",
                "references": [
                    {
                        "claim_id": str(target.claims["confirmed"].id),
                        "section_key": "main",
                        "usage": "fact",
                    }
                ],
            },
        )
        assert draft.status_code == 201

        override = await client.post(
            f"/api/v1/admin/events/{target.event.id}/editorial-scores/{target.score.id}/override",
            headers=WRITE_HEADERS,
            json={"risk_level": "R3", "emotion": 88, "reason": "M5-A effective override"},
        )
        assert override.status_code == 201

        merge = await client.post(
            f"/api/v1/admin/events/{target.event.id}/merge",
            headers=WRITE_HEADERS,
            json={"source_event_id": str(source.event.id), "reason": "M5-A merged fixture"},
        )
        assert merge.status_code == 200

        filtered = await client.get(
            "/api/v1/admin/workbench/events",
            headers=ADMIN_HEADERS,
            params={"risk": "R3", "has_evidence": "true", "has_draft": "true"},
        )
        assert filtered.status_code == 200
        body = filtered.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["event"]["id"] == str(target.event.id)
        assert item["effective_editorial"]["risk_level"] == "R3"
        assert item["effective_editorial"]["emotion"] == 88
        assert item["human_override_applied"] is True
        assert item["latest_trend"]["id"] == str(target.trend.id)
        assert item["latest_card"]["id"] == str(target.card.id)

        default_list = await client.get(
            "/api/v1/admin/workbench/events", headers=ADMIN_HEADERS
        )
        assert default_list.status_code == 200
        assert default_list.json()["total"] == 1

        with_merged = await client.get(
            "/api/v1/admin/workbench/events",
            headers=ADMIN_HEADERS,
            params={"include_merged": "true"},
        )
        assert with_merged.status_code == 200
        assert with_merged.json()["total"] == 2
        merged_item = next(
            row
            for row in with_merged.json()["items"]
            if row["event"]["id"] == str(source.event.id)
        )
        assert merged_item["event"]["merged_into_event_id"] == str(target.event.id)

        detail = await client.get(
            f"/api/v1/admin/workbench/events/{target.event.id}", headers=ADMIN_HEADERS
        )
        assert detail.status_code == 200
        assert detail.json()["signal_summary"]["total"] == target.event.source_count
        assert detail.json()["draft_summary"]["chain_count"] == 1

        signals = await client.get(
            f"/api/v1/admin/workbench/events/{target.event.id}/signals",
            headers=ADMIN_HEADERS,
        )
        assert signals.status_code == 200
        signal_body = signals.text.casefold()
        assert "raw_payload" not in signal_body
        assert "credential" not in signal_body
        assert "authorization" not in signal_body
        assert "api_key" not in signal_body
        assert signals.json()["items"][0]["original_url"].startswith("https://")

        all_payload = "\n".join(
            [filtered.text, default_list.text, with_merged.text, detail.text, signals.text]
        ).casefold()
        assert "raw_payload" not in all_payload
        assert "credential_ref" not in all_payload
        assert "authorization" not in all_payload
        assert "embedding" not in all_payload


@pytest.mark.usefixtures("clean_database")
async def test_workbench_overview_is_read_only_and_keeps_provider_validation_not_tested(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session, title="M5 overview event")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/workbench/overview", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_event_count"] == 1
    assert payload["events_with_evidence_count"] == 1
    assert payload["open_unknown_count"] == 1
    assert payload["artifact_counts"]["trend_snapshots"] >= 1
    assert payload["artifact_counts"]["editorial_scores"] >= 1
    assert payload["artifact_counts"]["event_cards"] >= 1
    assert payload["artifact_counts"]["editorial_packs"] >= 1
    assert payload["production_ai_provider_validation"] == "NOT_TESTED"
    assert str(context.event.id) not in response.text


@pytest.mark.usefixtures("clean_database")
async def test_workbench_event_page_enrichment_query_count_is_bounded(db_session) -> None:  # type: ignore[no-untyped-def]
    first = await create_m4d_context(db_session, title="M5 bounded one")
    await EventService(db_session).create(
        title="M5 bounded two",
        summary="plain event",
        category="technology",
        actor="m5a-test",
    )
    await db_session.commit()
    service = EditorialWorkbenchQueryService()
    engine = get_async_engine().sync_engine

    def count_queries(fn: Callable[[], Any]) -> tuple[Any, int]:
        del fn
        raise AssertionError("sync helper must not be called")

    counts: list[int] = []
    current = 0

    def before_cursor_execute(*args: Any, **kwargs: Any) -> None:
        nonlocal current
        del args, kwargs
        current += 1

    sa_event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        current = 0
        one = await service.list_events(page=1, page_size=1, include_merged=True)
        counts.append(current)
        assert one.total == 2
        current = 0
        two = await service.list_events(page=1, page_size=100, include_merged=True)
        counts.append(current)
        assert two.total == 2
        assert any(item["event"].id == first.event.id for item in two.items)
    finally:
        sa_event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert counts[1] <= counts[0] + 1
    assert counts[1] < 20
