from __future__ import annotations

import httpx
import pytest

from apps.api.main import app
from tests.m4d_helpers import create_m4d_context

ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token-at-least-24-characters"}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m4d-api-editor"}


@pytest.mark.usefixtures("clean_database")
async def test_m4d_admin_api_card_pack_manual_revision_and_export(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get(f"/api/v1/admin/events/{context.event.id}/cards")
        assert unauthorized.status_code >= 400

        cards = await client.get(
            f"/api/v1/admin/events/{context.event.id}/cards",
            headers=ADMIN_HEADERS,
        )
        assert cards.status_code == 200
        assert cards.json()[0]["id"] == str(context.card.id)

        missing_actor = await client.post(
            f"/api/v1/admin/events/{context.event.id}/cards",
            headers=ADMIN_HEADERS,
            json={"trend_snapshot_id": str(context.trend.id)},
        )
        assert missing_actor.status_code >= 400

        card_response = await client.post(
            f"/api/v1/admin/events/{context.event.id}/cards",
            headers=WRITE_HEADERS,
            json={"trend_snapshot_id": str(context.trend.id)},
        )
        assert card_response.status_code == 200
        assert card_response.json()["created"] is False
        assert card_response.json()["card"]["id"] == str(context.card.id)

        pack_response = await client.post(
            f"/api/v1/admin/events/{context.event.id}/editorial-packs",
            headers=WRITE_HEADERS,
            json={"event_card_id": str(context.card.id)},
        )
        assert pack_response.status_code == 200
        assert pack_response.json()["created"] is False
        assert pack_response.json()["pack"]["id"] == str(context.pack.id)

        manual = await client.post(
            f"/api/v1/admin/events/{context.event.id}/drafts/manual",
            headers=WRITE_HEADERS,
            json={
                "event_card_id": str(context.card.id),
                "editorial_pack_id": str(context.pack.id),
                "draft_type": "short_30s",
                "reason": "API人工稿件",
                "title": "API Draft",
                "body": "监管部门确认已启动调查。",
                "references": [
                    {
                        "claim_id": str(context.claims["confirmed"].id),
                        "section_key": "main",
                        "usage": "fact",
                    }
                ],
            },
        )
        assert manual.status_code == 201
        draft_id = manual.json()["id"]
        assert manual.json()["source_type"] == "human"
        assert manual.json()["ai_invocation_id"] is None

        revision = await client.post(
            f"/api/v1/admin/events/{context.event.id}/drafts/{draft_id}/revisions",
            headers=WRITE_HEADERS,
            json={
                "change_note": "API revision",
                "body": "监管部门确认已启动调查；其他责任问题仍在调查中。",
                "references": [
                    {
                        "claim_id": str(context.claims["confirmed"].id),
                        "section_key": "confirmed",
                        "usage": "fact",
                    },
                    {
                        "claim_id": str(context.claims["investigating"].id),
                        "section_key": "investigating",
                        "usage": "attributed",
                    },
                ],
            },
        )
        assert revision.status_code == 201
        revision_id = revision.json()["id"]
        assert revision.json()["draft_version"] == 2
        assert revision.json()["parent_draft_id"] == draft_id

        detail = await client.get(
            f"/api/v1/admin/events/{context.event.id}/drafts/{revision_id}",
            headers=ADMIN_HEADERS,
        )
        assert detail.status_code == 200
        assert [item["draft_version"] for item in detail.json()["version_chain"]] == [1, 2]
        assert len(detail.json()["claim_references"]) == 2

        export = await client.get(
            f"/api/v1/admin/events/{context.event.id}/editorial-pack/export.md",
            headers=ADMIN_HEADERS,
            params={"pack_id": str(context.pack.id), "draft_id": revision_id},
        )
        assert export.status_code == 200
        assert "# Event" in export.text
        assert "## Draft" in export.text
        assert "API revision" not in export.text
        assert "raw_payload" not in export.text
        assert "credential_ref" not in export.text
        assert "must-not-export" not in export.text


@pytest.mark.usefixtures("clean_database")
async def test_m4d_ai_apply_disabled_route_is_explicit_and_safe(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/admin/events/{context.event.id}/drafts",
            headers=WRITE_HEADERS,
            json={
                "event_card_id": str(context.card.id),
                "editorial_pack_id": str(context.pack.id),
                "draft_type": "standard_90s",
            },
        )
    assert response.status_code >= 400
    body = response.text.casefold()
    assert "api_key" not in body
    assert "authorization" not in body
    assert "credential" not in body
    assert "raw_payload" not in body
