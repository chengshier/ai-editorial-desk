from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from packages.database.models import EditorialScoreRecord, EventTrendSnapshotRecord
from packages.database.session import get_async_sessionmaker
from packages.editorial.services import TrendService
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
async def test_two_workers_same_trend_converge_to_one_snapshot(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[
            TrendSignalSpec(text="one", published_at=BASE_TIME),
            TrendSignalSpec(text="two", published_at=BASE_TIME + timedelta(minutes=5)),
        ],
    )

    async def calculate():  # type: ignore[no-untyped-def]
        return await TrendService().calculate(
            event_id=event.id,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END,
        )

    first, second = await asyncio.gather(calculate(), calculate())
    assert first.snapshot.id == second.snapshot.id
    assert sorted([first.created, second.created]) == [False, True]
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count())
            .select_from(EventTrendSnapshotRecord)
            .where(EventTrendSnapshotRecord.event_id == event.id)
        ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_same_ai_apply_create_one_score_artifact(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="score", published_at=BASE_TIME)],
    )
    trend = await create_trend_snapshot(event.id)
    service, calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(),
    )

    async def score():  # type: ignore[no-untyped-def]
        return await service.score(
            event_id=event.id,
            trend_snapshot_id=trend.id,
            actor="worker",
            apply=True,
        )

    first, second = await asyncio.gather(score(), score())
    assert first.score is not None
    assert second.score is not None
    assert first.score.id == second.score.id
    assert len(calls) in (1, 2)
    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count())
            .select_from(EditorialScoreRecord)
            .where(EditorialScoreRecord.event_id == event.id)
        ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_human_override_and_ai_rerun_never_silently_drop_human_decision(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="concurrent", published_at=BASE_TIME)],
    )
    first_trend = await create_trend_snapshot(event.id)
    service, _calls = await create_mock_scoring_service(
        db_session,
        response_data=valid_score_payload(emotion=30, risk_level="R2"),
    )
    first = await service.score(
        event_id=event.id,
        trend_snapshot_id=first_trend.id,
        actor="worker",
        apply=True,
    )
    assert first.score is not None

    second_trend = (
        await TrendService().calculate(
            event_id=event.id,
            window_start_at=WINDOW_START - timedelta(hours=1),
            window_end_at=WINDOW_END,
        )
    ).snapshot

    async def override():  # type: ignore[no-untyped-def]
        return await service.override_score(
            event_id=event.id,
            score_id=first.score.id,
            actor="editor",
            reason="human risk decision",
            overridden_fields={"emotion": 95, "risk_level": "R3"},
        )

    async def rerun():  # type: ignore[no-untyped-def]
        return await service.score(
            event_id=event.id,
            trend_snapshot_id=second_trend.id,
            actor="worker",
            apply=True,
        )

    human_override, rerun_result = await asyncio.gather(override(), rerun())
    assert rerun_result.score is not None
    effective = await service.effective(event.id)
    assert effective.effective_values is not None
    assert effective.effective_values["emotion"] == 95
    assert effective.effective_values["risk_level"] == "R3"
    assert human_override.id in {item.id for item in effective.applied_overrides}
