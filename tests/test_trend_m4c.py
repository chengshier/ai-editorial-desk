from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from packages.database.models import EventRecord, EventSignalRelation, EventStatus, EventTrendSnapshotRecord
from packages.editorial.domain import (
    GEOGRAPHY_UNAVAILABLE,
    INTERACTION_UNAVAILABLE,
    SEMANTIC_NOVELTY_UNAVAILABLE,
    TREND_CALCULATION_VERSION,
)
from packages.editorial.errors import EditorialEventMergedError, TrendValidationError
from packages.editorial.services import TrendService
from packages.events.services import EventService
from tests.m4c_helpers import (
    BASE_TIME,
    WINDOW_END,
    WINDOW_START,
    TrendSignalSpec,
    create_trend_context,
)


@pytest.mark.usefixtures("clean_database")
async def test_trend_is_deterministic_and_preserves_unavailable_semantics(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[
            TrendSignalSpec(
                text="first",
                published_at=BASE_TIME,
                source_group="source-a",
                platform="rss",
            ),
            TrendSignalSpec(
                text="official response",
                published_at=BASE_TIME + timedelta(minutes=30),
                source_group="source-b",
                platform="weibo",
                relation=EventSignalRelation.OFFICIAL_RESPONSE,
                metrics={"likes": 900000, "views": 10000000},
            ),
            TrendSignalSpec(
                text="correction",
                published_at=BASE_TIME + timedelta(hours=1),
                source_group="source-b",
                platform="bilibili",
                relation=EventSignalRelation.CORRECTION,
                metrics={"likes": 1, "views": 2},
            ),
        ],
    )

    first = await TrendService().calculate(
        event_id=event.id,
        window_start_at=WINDOW_START,
        window_end_at=WINDOW_END,
    )
    second = await TrendService().calculate(
        event_id=event.id,
        window_start_at=WINDOW_START,
        window_end_at=WINDOW_END,
    )

    snapshot = first.snapshot
    assert first.created is True
    assert second.created is False
    assert second.snapshot.id == snapshot.id
    assert snapshot.calculation_version == TREND_CALCULATION_VERSION
    assert snapshot.signal_count == 3
    assert snapshot.new_signal_count == 3
    assert snapshot.source_count == 2
    assert snapshot.platform_count == 3
    assert snapshot.signal_velocity == 0.75
    assert snapshot.cross_source is True
    assert snapshot.cross_platform is True
    assert snapshot.interaction_velocity is None
    assert snapshot.cn_gap is None
    assert snapshot.semantic_novelty is None
    assert snapshot.update_value == 38.0
    assert snapshot.feature_availability["interaction_velocity"] is False
    assert snapshot.feature_availability["cn_gap"] is False
    assert snapshot.feature_availability["semantic_novelty"] is False
    unavailable = snapshot.component_metrics["unavailable_reasons"]
    assert unavailable["interaction_velocity"] == INTERACTION_UNAVAILABLE
    assert unavailable["cn_gap"] == GEOGRAPHY_UNAVAILABLE
    assert unavailable["semantic_novelty"] == SEMANTIC_NOVELTY_UNAVAILABLE

    async with db_session.begin():
        row_count = await db_session.scalar(
            select(func.count())
            .select_from(EventTrendSnapshotRecord)
            .where(EventTrendSnapshotRecord.event_id == event.id)
        )
        stored_event = await db_session.get(EventRecord, event.id)
        assert stored_event is not None
        assert stored_event.status is EventStatus.EMERGING
    assert row_count == 1


@pytest.mark.usefixtures("clean_database")
async def test_trend_zero_is_distinct_from_unavailable_and_covers_source_platform_shapes(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[
            TrendSignalSpec(
                text="source a",
                published_at=BASE_TIME,
                source_group="source-a",
                platform="rss",
            ),
            TrendSignalSpec(
                text="source b same platform",
                published_at=BASE_TIME + timedelta(minutes=5),
                source_group="source-b",
                platform="rss",
            ),
        ],
    )

    same_platform = await TrendService().calculate(
        event_id=event.id,
        window_start_at=WINDOW_START,
        window_end_at=WINDOW_END,
    )
    assert same_platform.snapshot.source_count == 2
    assert same_platform.snapshot.platform_count == 1
    assert same_platform.snapshot.cross_source is True
    assert same_platform.snapshot.cross_platform is False

    stable = await TrendService().calculate(
        event_id=event.id,
        window_start_at=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        window_end_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    assert stable.snapshot.new_signal_count == 0
    assert stable.snapshot.signal_velocity == 0.0
    assert stable.snapshot.interaction_velocity is None
    assert stable.snapshot.feature_availability["signal_velocity"] is True
    assert stable.snapshot.feature_availability["interaction_velocity"] is False


@pytest.mark.usefixtures("clean_database")
async def test_resolved_event_can_be_analyzed_without_status_mutation(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        status=EventStatus.RESOLVED,
        specs=[TrendSignalSpec(text="resolved", published_at=BASE_TIME)],
    )
    outcome = await TrendService().calculate(
        event_id=event.id,
        window_start_at=WINDOW_START,
        window_end_at=WINDOW_END,
    )
    assert outcome.snapshot.new_signal_count == 1
    async with db_session.begin():
        stored = await db_session.get(EventRecord, event.id)
        assert stored is not None
        assert stored.status is EventStatus.RESOLVED


@pytest.mark.usefixtures("clean_database")
async def test_merged_event_blocks_new_trend_but_history_remains_readable(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="before merge", published_at=BASE_TIME)],
    )
    existing = await TrendService().calculate(
        event_id=source.id,
        window_start_at=WINDOW_START,
        window_end_at=WINDOW_END,
    )
    target = await EventService(db_session).create(
        title="Merge target",
        summary=None,
        category=None,
        status=EventStatus.GROWING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m4c-test",
    )
    async with db_session.begin():
        stored_source = await db_session.get(EventRecord, source.id)
        assert stored_source is not None
        stored_source.merged_into_event_id = target.id

    with pytest.raises(EditorialEventMergedError) as exc_info:
        await TrendService().calculate(
            event_id=source.id,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END,
        )
    assert exc_info.value.details["target_event_id"] == str(target.id)
    latest = await TrendService().latest(source.id)
    assert latest is not None
    assert latest.id == existing.snapshot.id


@pytest.mark.usefixtures("clean_database")
async def test_trend_window_is_explicit_utc_and_bounded(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _signals = await create_trend_context(
        db_session,
        specs=[TrendSignalSpec(text="bounded", published_at=BASE_TIME)],
    )
    service = TrendService()
    with pytest.raises(TrendValidationError):
        await service.calculate(
            event_id=event.id,
            window_start_at=datetime(2026, 8, 9, 4, 0),
            window_end_at=WINDOW_END,
        )
    with pytest.raises(TrendValidationError):
        await service.calculate(
            event_id=event.id,
            window_start_at=WINDOW_END,
            window_end_at=WINDOW_START,
        )
    with pytest.raises(TrendValidationError):
        await service.calculate(
            event_id=event.id,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_START + timedelta(days=8),
        )
