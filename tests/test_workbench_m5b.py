from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from apps.api.main import app
from packages.common.config import get_settings
from packages.database.models import EditorialDecisionType
from packages.editorial.candidates import CandidateGenerationRequest, DailyCandidateService
from packages.editorial.decisions import EditorialDecisionService
from tests.m4d_helpers import create_m4d_context

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
AS_OF = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)


@pytest.mark.usefixtures("clean_database")
async def test_m5b_workbench_overlay_is_read_only_and_filters_current_decision(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    context = await create_m4d_context(db_session, title="M5-B archived workbench event")
    outcome = await DailyCandidateService().apply(
        CandidateGenerationRequest(
            business_date=AS_OF.date(),
            timezone="UTC",
            as_of_at=AS_OF,
            lookback_hours=24,
            requested_limit=20,
        ),
        actor="m5b-workbench",
        confirmed=True,
    )
    candidate = next(
        item for item in outcome.candidates if item.event_id == context.event.id
    )
    archived = await EditorialDecisionService().decide(
        event_id=context.event.id,
        candidate_id=candidate.id,
        decision=EditorialDecisionType.ARCHIVE,
        actor="m5b-workbench",
        reason="archive for workbench filter",
        confirmation=True,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        filtered = await client.get(
            "/api/v1/admin/workbench/events",
            headers=ADMIN_HEADERS,
            params={"decision": "archive"},
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        item = filtered.json()["items"][0]
        assert item["current_editorial_decision"]["id"] == str(archived.decision.id)
        assert item["current_editorial_decision"]["decision"] == "archive"
        assert item["latest_candidate"]["id"] == str(candidate.id)
        assert item["latest_candidate"]["rank"] == 1
        assert item["latest_candidate_run"]["id"] == str(outcome.run.id)

        detail = await client.get(
            f"/api/v1/admin/workbench/events/{context.event.id}",
            headers=ADMIN_HEADERS,
        )
        assert detail.status_code == 200
        assert detail.json()["current_editorial_decision"]["decision"] == "archive"
        assert detail.json()["latest_candidate"]["rank"] == 1

        overview = await client.get(
            "/api/v1/admin/workbench/overview",
            headers=ADMIN_HEADERS,
        )
        assert overview.status_code == 200
        workflow = overview.json()["candidate_workflow"]
        assert workflow["current_decision_counts"]["archive"] == 1
        assert overview.json()["production_ai_provider_validation"] == "NOT_TESTED"

        forbidden_write = await client.post(
            f"/api/v1/admin/workbench/events/{context.event.id}/decision",
            headers={**ADMIN_HEADERS, "X-Actor-ID": "m5b-workbench"},
            json={"decision": "watch", "reason": "must not exist"},
        )
        assert forbidden_write.status_code in {404, 405}

    payload = "\n".join([filtered.text, detail.text, overview.text]).casefold()
    for forbidden in (
        "raw_payload",
        "credential_ref",
        "authorization",
        "api_key",
        "cookie",
        "embedding",
        "prompt_version",
    ):
        assert forbidden not in payload
