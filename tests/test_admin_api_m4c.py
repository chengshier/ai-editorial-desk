from __future__ import annotations

import httpx
import pytest

from apps.api.main import app
from packages.common.config import get_settings
from tests.m4c_helpers import BASE_TIME, TrendSignalSpec, create_trend_context

ADMIN_ONLY = {"X-Admin-Token": get_settings().admin_token_value}
ADMIN_HEADERS = {
    "X-Admin-Token": get_settings().admin_token_value,
    "X-Actor-ID": "m4c-api-test",
}


@pytest.mark.usefixtures("clean_database")
async def test_m4c_admin_api_auth_trend_manual_override_and_effective(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="API_SECRET_BODY", published_at=BASE_TIME)],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get(f"/api/v1/admin/events/{event.id}/trend")
        assert unauthorized.status_code == 401

        missing_actor = await client.post(
            f"/api/v1/admin/events/{event.id}/trend/calculate",
            headers=ADMIN_ONLY,
            json={
                "window_start_at": "2026-08-09T04:00:00Z",
                "window_end_at": "2026-08-09T08:00:00Z",
            },
        )
        assert missing_actor.status_code == 422

        calculated = await client.post(
            f"/api/v1/admin/events/{event.id}/trend/calculate",
            headers=ADMIN_HEADERS,
            json={
                "window_start_at": "2026-08-09T04:00:00Z",
                "window_end_at": "2026-08-09T08:00:00Z",
            },
        )
        assert calculated.status_code == 200, calculated.text
        trend = calculated.json()["snapshot"]
        assert trend["signal_velocity"] == 0.25
        assert trend["interaction_velocity"] is None
        assert trend["feature_availability"]["interaction_velocity"] is False

        manual = await client.post(
            f"/api/v1/admin/events/{event.id}/editorial-scores/manual",
            headers=ADMIN_HEADERS,
            json={
                "trend_snapshot_id": trend["id"],
                "emotion": 50,
                "information_gap": 50,
                "visual_value": 50,
                "user_relevance": 50,
                "discussion": 50,
                "novelty": 50,
                "extendability": 50,
                "risk_level": "R2",
                "recommended_format": "quick_explainer",
                "reason": "API manual decision",
            },
        )
        assert manual.status_code == 201, manual.text
        score = manual.json()
        assert score["source_type"] == "human"
        assert score["traffic_total"] == 50.0
        assert score["ai_invocation_id"] is None

        override = await client.post(
            f"/api/v1/admin/events/{event.id}/editorial-scores/{score['id']}/override",
            headers=ADMIN_HEADERS,
            json={
                "emotion": 100,
                "risk_level": "R3",
                "recommended_format": "fact_check",
                "reason": "API senior editor override",
            },
        )
        assert override.status_code == 201, override.text
        assert override.json()["actor"] == "m4c-api-test"

        effective = await client.get(
            f"/api/v1/admin/events/{event.id}/editorial-scores/effective",
            headers=ADMIN_ONLY,
        )
        assert effective.status_code == 200, effective.text
        body = effective.json()
        assert body["latest_human_score"]["id"] == score["id"]
        assert body["effective_values"]["emotion"] == 100
        assert body["effective_values"]["risk_level"] == "R3"
        assert body["effective_values"]["recommended_format"] == "fact_check"
        assert body["effective_values"]["traffic_total"] == 60.0

        listed = await client.get(
            f"/api/v1/admin/events/{event.id}/editorial-scores",
            headers=ADMIN_ONLY,
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    all_text = calculated.text + manual.text + override.text + effective.text + listed.text
    assert "API_SECRET_BODY" not in all_text
    assert "raw_payload" not in all_text
    assert "authorization" not in all_text.casefold()
    assert "embedding" not in all_text.casefold()
    assert "prompt" not in all_text.casefold()


@pytest.mark.usefixtures("clean_database")
async def test_ai_scoring_disabled_route_is_safe_and_explicit(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="route disabled", published_at=BASE_TIME)],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        calculated = await client.post(
            f"/api/v1/admin/events/{event.id}/trend/calculate",
            headers=ADMIN_HEADERS,
            json={
                "window_start_at": "2026-08-09T04:00:00Z",
                "window_end_at": "2026-08-09T08:00:00Z",
            },
        )
        assert calculated.status_code == 200
        trend_id = calculated.json()["snapshot"]["id"]
        scoring = await client.post(
            f"/api/v1/admin/events/{event.id}/editorial-scores/preview",
            headers=ADMIN_HEADERS,
            json={"trend_snapshot_id": trend_id},
        )
        assert scoring.status_code == 503, scoring.text
        error = scoring.json()["error"]
        assert error["code"] == "EDITORIAL_AI_ERROR"
        assert error["details"]["ai_error_code"] == "ROUTE_NOT_CONFIGURED"
        assert "credential" not in scoring.text.casefold()
