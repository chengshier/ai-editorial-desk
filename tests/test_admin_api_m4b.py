from __future__ import annotations

import httpx
import pytest

from apps.api.main import app
from packages.common.config import get_settings
from tests.m4b_helpers import create_event_context

ADMIN_ONLY = {"X-Admin-Token": get_settings().admin_token_value}
ADMIN_HEADERS = {
    "X-Admin-Token": get_settings().admin_token_value,
    "X-Actor-ID": "m4b-api-test",
}


@pytest.mark.usefixtures("clean_database")
async def test_evidence_admin_api_auth_actor_and_safe_source_view(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(
        db_session,
        texts=["TOP_SECRET_SIGNAL_BODY must not be returned by evidence view"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get(f"/api/v1/admin/events/{event.id}/evidence")
        assert unauthorized.status_code == 401

        missing_actor = await client.post(
            f"/api/v1/admin/events/{event.id}/claims",
            headers=ADMIN_ONLY,
            json={
                "claim_text": "人工 API Claim",
                "claim_type": "fact",
                "sources": [{"signal_id": str(signals[0].id), "role": "supporting"}],
            },
        )
        assert missing_actor.status_code == 422

        created = await client.post(
            f"/api/v1/admin/events/{event.id}/claims",
            headers=ADMIN_HEADERS,
            json={
                "claim_text": "人工 API Claim",
                "claim_type": "fact",
                "sources": [{"signal_id": str(signals[0].id), "role": "supporting"}],
            },
        )
        assert created.status_code == 201, created.text
        claim_id = created.json()["id"]

        fetched = await client.get(
            f"/api/v1/admin/events/{event.id}/evidence",
            headers=ADMIN_ONLY,
        )
        assert fetched.status_code == 200, fetched.text
        verified = await client.post(
            f"/api/v1/admin/events/{event.id}/claims/{claim_id}/verify",
            headers=ADMIN_HEADERS,
            json={
                "verification_state": "confirmed",
                "reason": "API 人工确认",
            },
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["verification_state"] == "confirmed"

    response_text = fetched.text
    assert "TOP_SECRET_SIGNAL_BODY" not in response_text
    assert "raw_payload" not in response_text
    assert "secret-that-must-not-enter-evidence" not in response_text
    assert "authorization" not in response_text.casefold()
    assert "embedding" not in response_text.casefold()
    assert "prompt" not in response_text.casefold()


@pytest.mark.usefixtures("clean_database")
async def test_unknown_api_and_disabled_route_error_are_explicit(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_event_context(db_session, texts=["来源"])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/admin/events/{event.id}/unknowns",
            headers=ADMIN_HEADERS,
            json={"unknown_text": "API Unknown"},
        )
        assert created.status_code == 201, created.text
        unknown_id = created.json()["id"]
        resolved = await client.patch(
            f"/api/v1/admin/events/{event.id}/unknowns/{unknown_id}",
            headers=ADMIN_HEADERS,
            json={"status": "resolved", "resolution_note": "人工解决"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "resolved"

        extraction = await client.post(
            f"/api/v1/admin/events/{event.id}/evidence/extract",
            headers=ADMIN_HEADERS,
            json={"apply": True},
        )
        assert extraction.status_code == 503, extraction.text
        body = extraction.json()
        assert body["error"]["code"] == "EVIDENCE_AI_ERROR"
        assert body["error"]["details"]["ai_error_code"] == "ROUTE_NOT_CONFIGURED"
