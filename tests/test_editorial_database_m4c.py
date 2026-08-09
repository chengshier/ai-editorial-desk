from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from packages.database.models import (
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EditorialScoreOverrideRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventTrendSnapshotRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.domain import EDITORIAL_SCORING_VERSION, TREND_CALCULATION_VERSION
from packages.editorial.services import EditorialScoringService
from tests.m4c_helpers import (
    BASE_TIME,
    WINDOW_END,
    WINDOW_START,
    TrendSignalSpec,
    create_trend_context,
    create_trend_snapshot,
)


def _score_values() -> dict[str, object]:
    return {
        "score_template": "general",
        "score_template_version": "score-template-general-v1",
        "scoring_version": EDITORIAL_SCORING_VERSION,
        "emotion": 50,
        "information_gap": 50,
        "visual_value": 50,
        "user_relevance": 50,
        "discussion": 50,
        "novelty": 50,
        "extendability": 50,
        "traffic_total": 50.0,
        "risk_level": EditorialRiskLevel.R2,
        "recommended_format": EditorialRecommendedFormat.DEEP_DIVE,
        "model_reason": None,
        "input_hash": "a" * 64,
        "created_by_actor": "test",
    }


@pytest.mark.usefixtures("clean_database")
async def test_database_rejects_invalid_trend_window_counts_and_hash(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="db", published_at=BASE_TIME)],
    )
    invalid_rows = [
        EventTrendSnapshotRecord(
            event_id=event.id,
            calculation_version=TREND_CALCULATION_VERSION,
            window_start_at=WINDOW_END,
            window_end_at=WINDOW_START,
            signal_count=1,
            new_signal_count=1,
            source_count=1,
            platform_count=1,
            signal_velocity=1.0,
            interaction_velocity=None,
            cross_source=False,
            cross_platform=False,
            semantic_novelty=None,
            cn_gap=None,
            update_value=10.0,
            feature_availability={},
            component_metrics={},
            input_hash="a" * 64,
        ),
        EventTrendSnapshotRecord(
            event_id=event.id,
            calculation_version=TREND_CALCULATION_VERSION,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END,
            signal_count=-1,
            new_signal_count=0,
            source_count=0,
            platform_count=0,
            signal_velocity=0.0,
            interaction_velocity=None,
            cross_source=False,
            cross_platform=False,
            semantic_novelty=None,
            cn_gap=None,
            update_value=0.0,
            feature_availability={},
            component_metrics={},
            input_hash="b" * 64,
        ),
        EventTrendSnapshotRecord(
            event_id=event.id,
            calculation_version=TREND_CALCULATION_VERSION,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END + timedelta(minutes=1),
            signal_count=1,
            new_signal_count=1,
            source_count=1,
            platform_count=1,
            signal_velocity=1.0,
            interaction_velocity=None,
            cross_source=False,
            cross_platform=False,
            semantic_novelty=None,
            cn_gap=None,
            update_value=10.0,
            feature_availability={},
            component_metrics={},
            input_hash="short",
        ),
    ]
    async with get_async_sessionmaker()() as session:
        for row in invalid_rows:
            session.add(row)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()


@pytest.mark.usefixtures("clean_database")
async def test_database_enforces_score_range_and_source_provenance(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="score db", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    async with get_async_sessionmaker()() as session:
        invalid_range = EditorialScoreRecord(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            source_type=EditorialScoreSourceType.HUMAN,
            source_reason="manual",
            ai_invocation_id=None,
            scoring_run_id=None,
            **_score_values(),
        )
        invalid_range.emotion = 101
        session.add(invalid_range)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        ai_without_provenance = EditorialScoreRecord(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            source_type=EditorialScoreSourceType.AI,
            source_reason=None,
            ai_invocation_id=None,
            scoring_run_id=None,
            **_score_values(),
        )
        session.add(ai_without_provenance)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        human_without_reason = EditorialScoreRecord(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            source_type=EditorialScoreSourceType.HUMAN,
            source_reason="",
            ai_invocation_id=None,
            scoring_run_id=None,
            **_score_values(),
        )
        session.add(human_without_reason)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.usefixtures("clean_database")
async def test_override_actor_reason_and_trend_history_are_restricted(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="override db", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    score = await EditorialScoringService().create_manual_score(
        event_id=event.id,
        trend_snapshot_id=trend.id,
        actor="editor",
        reason="baseline",
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
    async with get_async_sessionmaker()() as session:
        session.add(
            EditorialScoreOverrideRecord(
                editorial_score_id=score.id,
                overridden_fields={"risk_level": "R3"},
                reason="",
                actor="editor",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        session.add(
            EditorialScoreOverrideRecord(
                editorial_score_id=score.id,
                overridden_fields={"risk_level": "R3"},
                reason="valid",
                actor="",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        stored_trend = await session.get(EventTrendSnapshotRecord, trend.id)
        assert stored_trend is not None
        await session.delete(stored_trend)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
