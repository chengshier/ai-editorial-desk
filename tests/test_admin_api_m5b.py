from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import func, select

from apps.api.main import app
from packages.common.config import get_settings
from packages.database.models import AIInvocationRecord, EditorialRiskLevel
from packages.database.session import get_async_engine
from packages.editorial.candidates import CandidateGenerationRequest, DailyCandidateService
from packages.editorial.workflow_queries import EditorialWorkflowQueryService
from tests.m4d_helpers import create_m4d_context

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}
WRITE_HEADERS = {**ADMIN_HEADERS, "X-Actor-ID": "m5b-api-editor"}
AS_OF = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
REQUEST = {
    "business_date": "2026-08-09",
    "timezone": "UTC",
    "as_of_at": AS_OF.isoformat(),
    "lookback_hours": 24,
    "requested_limit": 20,
}


@pytest.mark.usefixtures("clean_database")
async def test_m5b_admin_api_auth_safe_projection_and_no_automatic_ai(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    context = await create_m4d_context(
        db_session,
        risk_level=EditorialRiskLevel.R3,
        title="M5-B API candidate",
    )
    before_ai = int(
        await db_session.scalar(select(func.count(AIInvocationRecord.id))) or 0
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.post(
            "/api/v1/admin/editorial/candidate-runs/preview",
            json=REQUEST,
        )
        assert unauthorized.status_code >= 400

        preview = await client.post(
            "/api/v1/admin/editorial/candidate-runs/preview",
            headers=ADMIN_HEADERS,
            json=REQUEST,
        )
        assert preview.status_code == 200
        assert preview.json()["ranking_version"] == "candidate-ranking-v1"
        assert preview.json()["candidate_count"] == 1

        missing_actor = await client.post(
            "/api/v1/admin/editorial/candidate-runs",
            headers=ADMIN_HEADERS,
            json={**REQUEST, "confirmation": True},
        )
        assert missing_actor.status_code >= 400

        applied = await client.post(
            "/api/v1/admin/editorial/candidate-runs",
            headers=WRITE_HEADERS,
            json={**REQUEST, "confirmation": True},
        )
        assert applied.status_code == 201
        candidate = applied.json()["candidates"][0]
        assert candidate["event_id"] == str(context.event.id)
        assert candidate["candidate_group"] == "review_required"

        no_ack = await client.post(
            f"/api/v1/admin/editorial/events/{context.event.id}/decision",
            headers=WRITE_HEADERS,
            json={
                "candidate_id": candidate["id"],
                "decision": "adopt",
                "reason": "editor accepts review-required topic",
                "risk_acknowledged": False,
                "confirmation": False,
            },
        )
        assert no_ack.status_code == 409
        assert no_ack.json()["error"]["code"] == "RISK_ACKNOWLEDGEMENT_REQUIRED"

        adopted = await client.post(
            f"/api/v1/admin/editorial/events/{context.event.id}/decision",
            headers=WRITE_HEADERS,
            json={
                "candidate_id": candidate["id"],
                "decision": "adopt",
                "reason": "editor accepts review-required topic",
                "risk_acknowledged": True,
                "confirmation": False,
            },
        )
        assert adopted.status_code == 201
        assert adopted.json()["decision"]["decision"] == "adopt"

        history = await client.get(
            f"/api/v1/admin/editorial/events/{context.event.id}/decisions",
            headers=ADMIN_HEADERS,
        )
        assert history.status_code == 200
        assert history.json()[0]["candidate_rank"] == 1

    after_ai = int(
        await db_session.scalar(select(func.count(AIInvocationRecord.id))) or 0
    )
    assert before_ai == after_ai
    payload = "\n".join([preview.text, applied.text, adopted.text, history.text]).casefold()
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


@pytest.mark.usefixtures("clean_database")
async def test_candidate_list_decision_overlay_query_count_is_bounded(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    await create_m4d_context(db_session, title="M5-B bounded one")
    await create_m4d_context(db_session, title="M5-B bounded two")
    request = CandidateGenerationRequest(
        business_date=AS_OF.date(),
        timezone="UTC",
        as_of_at=AS_OF,
        lookback_hours=24,
        requested_limit=20,
    )
    run = await DailyCandidateService().apply(
        request,
        actor="m5b-query-test",
        confirmed=True,
    )
    service = EditorialWorkflowQueryService()
    engine = get_async_engine().sync_engine
    counts: list[int] = []
    current = 0

    def before_cursor_execute(*args: Any, **kwargs: Any) -> None:
        nonlocal current
        del args, kwargs
        current += 1

    sa_event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        current = 0
        one = await service.list_candidates(run_id=run.run.id, top_n=1)
        counts.append(current)
        assert one.total == 1
        current = 0
        two = await service.list_candidates(run_id=run.run.id, top_n=20)
        counts.append(current)
        assert two.total == 2
    finally:
        sa_event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert counts[1] <= counts[0] + 1
    assert counts[1] <= 5
