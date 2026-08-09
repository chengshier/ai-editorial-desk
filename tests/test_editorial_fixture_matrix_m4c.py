from __future__ import annotations

import pytest

from packages.database.models import EventUnknownStatus
from packages.editorial.errors import EditorialRiskConflictError
from packages.editorial.services import EditorialScoringService
from packages.evidence.services import EventEvidenceService
from tests.m4c_helpers import (
    BASE_TIME,
    TrendSignalSpec,
    create_mock_scoring_service,
    create_trend_context,
    create_trend_snapshot,
    valid_score_payload,
)


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    ("case_name", "overrides"),
    [
        (
            "high_emotion_low_evidence",
            {"emotion": 95, "information_gap": 70, "risk_level": "R3"},
        ),
        (
            "high_trend_high_risk",
            {"discussion": 95, "risk_level": "R4", "recommended_format": "fact_check"},
        ),
        (
            "high_information_gap_low_trend",
            {"information_gap": 95, "discussion": 25, "risk_level": "R2"},
        ),
        (
            "low_visual_value",
            {"visual_value": 5, "recommended_format": "quick_explainer"},
        ),
        (
            "strong_visual_value",
            {"visual_value": 95, "recommended_format": "deep_dive"},
        ),
        (
            "high_extendability",
            {"extendability": 95, "recommended_format": "daily_compilation"},
        ),
    ],
)
async def test_editorial_offline_fixture_matrix_keeps_trend_and_ai_dimensions_separate(
    db_session, case_name: str, overrides: dict[str, object]
) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text=case_name, published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    before = {
        "signal_count": trend.signal_count,
        "signal_velocity": trend.signal_velocity,
        "interaction_velocity": trend.interaction_velocity,
        "input_hash": trend.input_hash,
    }
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(**overrides),
    )
    outcome = await service.score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="fixture-scorer",
        apply=True,
    )
    assert outcome.score is not None
    latest_trend = await EditorialScoringService().input_builder.build(
        event_id=event.id,
        trend_snapshot_id=trend.id,
    )
    assert latest_trend.payload["trend"]["signal_count"] == before["signal_count"]
    assert latest_trend.payload["trend"]["signal_velocity"] == before["signal_velocity"]
    assert latest_trend.payload["trend"]["interaction_velocity"] is None
    assert latest_trend.payload["trend"]["id"] == str(trend.id)


@pytest.mark.usefixtures("clean_database")
async def test_open_unknown_blocks_ai_r0_until_human_resolves_it(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="unknown", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    unknown = await EventEvidenceService().create_unknown(
        event_id=event.id,
        unknown_text="core fact remains unresolved",
        actor="reviewer",
    )
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(risk_level="R0"),
    )
    with pytest.raises(EditorialRiskConflictError):
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )

    await EventEvidenceService().update_unknown(
        event_id=event.id,
        unknown_id=unknown.id,
        status=EventUnknownStatus.RESOLVED,
        actor="reviewer",
        resolution_note="resolved after manual review",
    )
    # R0 still cannot pass because there is no confirmed Claim. This proves resolving
    # Unknown does not fabricate positive Evidence.
    with pytest.raises(EditorialRiskConflictError):
        await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="scorer",
            apply=True,
        )
