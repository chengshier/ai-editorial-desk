from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from packages.database.models import (
    ConfigurationChangeLog,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import EDITORIAL_SCORE_TEMPLATE_VERSION
from packages.editorial.errors import EditorialEventMergedError, EditorialValidationError
from packages.editorial.services import EditorialScoringService, TrendService
from packages.events.services import EventService
from tests.m4c_helpers import (
    BASE_TIME,
    WINDOW_END,
    WINDOW_START,
    TrendSignalSpec,
    create_mock_scoring_service,
    create_trend_context,
    create_trend_snapshot,
    valid_score_payload,
)


@pytest.mark.usefixtures("clean_database")
async def test_manual_score_requires_no_fake_invocation_and_is_audited(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="manual", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service = EditorialScoringService()
    score = await service.create_manual_score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="editor",
        reason="manual editorial judgment",
        dimensions={
            "emotion": 50,
            "information_gap": 50,
            "visual_value": 50,
            "user_relevance": 50,
            "discussion": 50,
            "novelty": 50,
            "extendability": 50,
        },
        risk_level=EditorialRiskLevel.R2,
        recommended_format=EditorialRecommendedFormat.DEEP_DIVE,
        model_reason="Human assessment, not an AI model response.",
    )
    assert score.source_type is EditorialScoreSourceType.HUMAN
    assert score.ai_invocation_id is None
    assert score.scoring_run_id is None
    assert score.traffic_total == 50.0
    assert score.score_template_version == EDITORIAL_SCORE_TEMPLATE_VERSION

    effective = await service.effective(event.id)
    assert effective.latest_human_score is not None
    assert effective.latest_human_score.id == score.id
    assert effective.effective_base_score_id == score.id
    assert effective.effective_values is not None
    assert effective.effective_values["traffic_total"] == 50.0

    async with get_async_sessionmaker()() as session:
        audit = await session.scalar(
            select(ConfigurationChangeLog).where(
                ConfigurationChangeLog.entity_type == "editorial_score",
                ConfigurationChangeLog.entity_id == score.id,
                ConfigurationChangeLog.action == "human_create",
            )
        )
        assert audit is not None
        assert audit.actor == "editor"
        assert audit.after_data["reason"] == "manual editorial judgment"

    with pytest.raises(EditorialValidationError):
        await service.create_manual_score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="editor",
            reason="   ",
            dimensions={
                "emotion": 50,
                "information_gap": 50,
                "visual_value": 50,
                "user_relevance": 50,
                "discussion": 50,
                "novelty": 50,
                "extendability": 50,
            },
            risk_level=EditorialRiskLevel.R2,
            recommended_format=EditorialRecommendedFormat.DEEP_DIVE,
        )


@pytest.mark.usefixtures("clean_database")
async def test_override_preserves_original_and_effective_view_recomputes_total(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="override", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service = EditorialScoringService()
    score = await service.create_manual_score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="editor",
        reason="baseline manual score",
        dimensions={
            "emotion": 50,
            "information_gap": 50,
            "visual_value": 50,
            "user_relevance": 50,
            "discussion": 50,
            "novelty": 50,
            "extendability": 50,
        },
        risk_level=EditorialRiskLevel.R2,
        recommended_format=EditorialRecommendedFormat.QUICK_EXPLAINER,
    )
    override = await service.override_score(
        event_id=event.id,
        score_id=score.id,
        actor="senior-editor",
        reason="visual evidence is stronger after review",
        overridden_fields={
            "emotion": 100,
            "risk_level": "R3",
            "recommended_format": "fact_check",
        },
    )
    assert override.editorial_score_id == score.id

    async with get_async_sessionmaker()() as session:
        original = await session.get(EditorialScoreRecord, score.id)
        assert original is not None
        assert original.emotion == 50
        assert original.risk_level is EditorialRiskLevel.R2
        assert original.recommended_format is EditorialRecommendedFormat.QUICK_EXPLAINER

    effective = await service.effective(event.id)
    assert effective.effective_values is not None
    assert effective.effective_values["emotion"] == 100
    assert effective.effective_values["risk_level"] == "R3"
    assert effective.effective_values["recommended_format"] == "fact_check"
    assert effective.effective_values["traffic_total"] == 60.0
    assert [item.id for item in effective.applied_overrides] == [override.id]

    with pytest.raises(EditorialValidationError):
        await service.override_score(
            event_id=event.id,
            score_id=score.id,
            actor="editor",
            reason=" ",
            overridden_fields={"emotion": 10},
        )
    with pytest.raises(EditorialValidationError):
        await service.override_score(
            event_id=event.id,
            score_id=score.id,
            actor="editor",
            reason="invalid field",
            overridden_fields={"traffic_total": 99},
        )


@pytest.mark.usefixtures("clean_database")
async def test_human_override_survives_later_ai_rerun(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="rerun", published_at=BASE_TIME)],
    )
    first_trend = await create_trend_snapshot(event.id)
    ai_service, calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(emotion=40, risk_level="R2"),
    )
    first = await ai_service.score(
        event_id=event.id,
        trend_snapshot_id=first_trend.id,
        actor="scorer",
        apply=True,
    )
    assert first.score is not None
    override = await ai_service.override_score(
        event_id=event.id,
        score_id=first.score.id,
        actor="editor",
        reason="human keeps risk elevated",
        overridden_fields={"emotion": 90, "risk_level": "R3"},
    )

    second_trend = (
        await TrendService().calculate(
            event_id=event.id,
            window_start_at=WINDOW_START - timedelta(hours=1),
            window_end_at=WINDOW_END,
        )
    ).snapshot
    second = await ai_service.score(
        event_id=event.id,
        trend_snapshot_id=second_trend.id,
        actor="scorer",
        apply=True,
    )
    assert second.score is not None
    assert second.score.id != first.score.id
    assert len(calls) == 2

    effective = await ai_service.effective(event.id)
    assert effective.latest_ai_score is not None
    assert effective.latest_ai_score.id == second.score.id
    assert effective.effective_base_score_id == second.score.id
    assert effective.effective_values is not None
    assert effective.effective_values["emotion"] == 90
    assert effective.effective_values["risk_level"] == "R3"
    assert override.id in {item.id for item in effective.applied_overrides}


@pytest.mark.usefixtures("clean_database")
async def test_merged_event_blocks_manual_score_and_override(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="merge", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service = EditorialScoringService()
    score = await service.create_manual_score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="editor",
        reason="before merge",
        dimensions={
            "emotion": 50,
            "information_gap": 50,
            "visual_value": 50,
            "user_relevance": 50,
            "discussion": 50,
            "novelty": 50,
            "extendability": 50,
        },
        risk_level=EditorialRiskLevel.R2,
        recommended_format=EditorialRecommendedFormat.DEEP_DIVE,
    )
    target = await EventService(db_session).create(
        title="target",
        summary=None,
        category=None,
        status=EventStatus.GROWING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m4c-test",
    )
    async with db_session.begin():
        stored_event = await db_session.get(EventRecord, event.id)
        assert stored_event is not None
        stored_event.merged_into_event_id = target.id

    with pytest.raises(EditorialEventMergedError):
        await service.override_score(
            event_id=event.id,
            score_id=score.id,
            actor="editor",
            reason="after merge",
            overridden_fields={"risk_level": "R3"},
        )
    with pytest.raises(EditorialEventMergedError):
        await service.create_manual_score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="editor",
            reason="after merge",
            dimensions={
                "emotion": 50,
                "information_gap": 50,
                "visual_value": 50,
                "user_relevance": 50,
                "discussion": 50,
                "novelty": 50,
                "extendability": 50,
            },
            risk_level=EditorialRiskLevel.R3,
            recommended_format=EditorialRecommendedFormat.FACT_CHECK,
        )
