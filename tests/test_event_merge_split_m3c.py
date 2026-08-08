import asyncio

import pytest
from sqlalchemy import func, select

from packages.clustering.repositories import (
    MatchOverrideRepository,
    SignalEventSuppressionRepository,
)
from packages.clustering.services import (
    ClusterOutcomeStatus,
    EventClusterMaintenanceService,
    SignalMatchService,
)
from packages.connector_management.exceptions import BusinessValidationError
from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    MatchOverrideDecision,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.events.services import EventService
from tests.m3c_helpers import auto_cluster, create_m3c_signal, create_source


async def _human_event(db_session, *, title: str):  # type: ignore[no-untyped-def]
    return await EventService(db_session).create(
        title=title,
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )


async def _human_attach(db_session, event_id, signal_id, *, confidence=1.0):  # type: ignore[no-untyped-def]
    return await EventService(db_session).attach_signal(
        event_id=event_id,
        signal_id=signal_id,
        relation=EventSignalRelation.RELATED,
        confidence=confidence,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )


@pytest.mark.usefixtures("clean_database")
async def test_manual_merge_moves_memberships_keeps_source_and_deduplicates(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    shared = await create_m3c_signal(
        db_session, source, external_id="merge-shared", title="共享信号", text="共享正文"
    )
    source_only = await create_m3c_signal(
        db_session, source, external_id="merge-source", title="来源事件", text="来源正文"
    )
    target = await _human_event(db_session, title="Target Event")
    source_event = await _human_event(db_session, title="Source Event")
    await _human_attach(db_session, target.id, shared.id, confidence=0.9)
    await _human_attach(db_session, source_event.id, shared.id, confidence=0.7)
    await _human_attach(db_session, source_event.id, source_only.id, confidence=0.8)

    merged = await EventClusterMaintenanceService(db_session).merge(
        target_event_id=target.id,
        source_event_id=source_event.id,
        reason="人工确认属于同一现实事件",
        actor="editor",
    )
    assert merged.id == target.id
    await db_session.refresh(source_event)
    assert source_event.merged_into_event_id == target.id
    assert source_event.status is EventStatus.EMERGING
    assert await db_session.get(RawSignalRecord, shared.id) is not None
    assert await db_session.get(RawSignalRecord, source_only.id) is not None
    target_signal_ids = set(
        await db_session.scalars(
            select(EventSignalRecord.signal_id).where(EventSignalRecord.event_id == target.id)
        )
    )
    assert target_signal_ids == {shared.id, source_only.id}
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(EventSignalRecord)
            .where(EventSignalRecord.event_id == source_event.id)
        )
        or 0
    ) == 0

    active_page = await EventService(db_session).list(
        page=1, page_size=20, status=None, include_merged=False
    )
    all_page = await EventService(db_session).list(
        page=1, page_size=20, status=None, include_merged=True
    )
    assert {item.id for item in active_page.items} == {target.id}
    assert {item.id for item in all_page.items} == {target.id, source_event.id}


@pytest.mark.usefixtures("clean_database")
async def test_merge_rejects_self_and_flattens_existing_merge_chain(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_source(db_session)
    event_a = await _human_event(db_session, title="A")
    event_b = await _human_event(db_session, title="B")
    event_c = await _human_event(db_session, title="C")
    service = EventClusterMaintenanceService(db_session)
    with pytest.raises(BusinessValidationError):
        await service.merge(
            target_event_id=event_a.id,
            source_event_id=event_a.id,
            reason="self",
            actor="editor",
        )
    await service.merge(
        target_event_id=event_b.id,
        source_event_id=event_a.id,
        reason="A merge B",
        actor="editor",
    )
    await service.merge(
        target_event_id=event_c.id,
        source_event_id=event_b.id,
        reason="B merge C",
        actor="editor",
    )
    await db_session.refresh(event_a)
    await db_session.refresh(event_b)
    assert event_a.merged_into_event_id == event_c.id
    assert event_b.merged_into_event_id == event_c.id
    with pytest.raises(BusinessValidationError):
        await service.merge(
            target_event_id=event_a.id,
            source_event_id=event_c.id,
            reason="cycle attempt",
            actor="editor",
        )


@pytest.mark.usefixtures("clean_database")
async def test_manual_split_moves_subset_recalculates_and_persists_distinct_overrides(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signals = [
        await create_m3c_signal(
            db_session,
            source,
            external_id=f"split-{index}",
            title="相同事件标题",
            text="相同事件正文",
            platform="rss" if index < 2 else "weibo",
        )
        for index in range(3)
    ]
    event = await _human_event(db_session, title="需要拆分的 Event")
    for signal in signals:
        await _human_attach(db_session, event.id, signal.id)

    new_event = await EventClusterMaintenanceService(db_session).split(
        event_id=event.id,
        signal_ids=[signals[2].id],
        title="拆分后的 Event",
        reason="人工确认第三条属于另一个现实事件",
        actor="editor",
    )
    await db_session.refresh(event)
    await db_session.refresh(new_event)
    assert event.source_count == 1
    assert event.platform_count == 1
    assert new_event.source_count == 1
    assert new_event.platform_count == 1
    assert set(
        await db_session.scalars(
            select(EventSignalRecord.signal_id).where(EventSignalRecord.event_id == event.id)
        )
    ) == {signals[0].id, signals[1].id}
    assert set(
        await db_session.scalars(
            select(EventSignalRecord.signal_id).where(
                EventSignalRecord.event_id == new_event.id
            )
        )
    ) == {signals[2].id}

    overrides = MatchOverrideRepository(db_session)
    for remaining in signals[:2]:
        override = await overrides.get(signals[2].id, remaining.id)
        assert override is not None
        assert override.decision is MatchOverrideDecision.DISTINCT
    suppressions = SignalEventSuppressionRepository(db_session)
    assert await suppressions.is_active(signals[2].id, event.id)
    assert await suppressions.is_active(signals[0].id, new_event.id)

    preview = await SignalMatchService(db_session).preview(signal_id=signals[2].id)
    decisions = {item.candidate_signal_id: item for item in preview.decisions}
    assert decisions[signals[0].id].decision.value == "distinct"
    assert decisions[signals[0].id].primary_method.value == "human"


@pytest.mark.usefixtures("clean_database")
async def test_split_rejects_missing_signal_and_all_signal_split(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session, source, external_id="split-boundary-a", title="A", text="A正文"
    )
    second = await create_m3c_signal(
        db_session, source, external_id="split-boundary-b", title="B", text="B正文"
    )
    outside = await create_m3c_signal(
        db_session, source, external_id="split-outside", title="C", text="C正文"
    )
    event = await _human_event(db_session, title="Boundary")
    await _human_attach(db_session, event.id, first.id)
    await _human_attach(db_session, event.id, second.id)
    service = EventClusterMaintenanceService(db_session)
    with pytest.raises(BusinessValidationError):
        await service.split(
            event_id=event.id,
            signal_ids=[outside.id],
            title="invalid",
            reason="missing",
            actor="editor",
        )
    with pytest.raises(BusinessValidationError):
        await service.split(
            event_id=event.id,
            signal_ids=[first.id, second.id],
            title="invalid",
            reason="all",
            actor="editor",
        )


@pytest.mark.usefixtures("clean_database")
async def test_manual_detach_suppression_prevents_automatic_reattach(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="detach-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="detach-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营。最新",
    )
    first_outcome = await auto_cluster(db_session, first.id)
    second_outcome = await auto_cluster(db_session, second.id)
    assert second_outcome.event_id == first_outcome.event_id
    assert first_outcome.event_id is not None

    detached = await EventService(db_session).detach_signal(
        event_id=first_outcome.event_id,
        signal_id=second.id,
        actor="editor",
    )
    assert detached is True
    assert await SignalEventSuppressionRepository(db_session).is_active(
        second.id, first_outcome.event_id
    )

    rerun = await auto_cluster(db_session, second.id)
    assert rerun.status is ClusterOutcomeStatus.AMBIGUOUS
    assert rerun.code == "HUMAN_EVENT_SUPPRESSION"
    assert await db_session.scalar(
        select(func.count())
        .select_from(EventSignalRecord)
        .where(
            EventSignalRecord.event_id == first_outcome.event_id,
            EventSignalRecord.signal_id == second.id,
        )
    ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_opposite_merge_uses_deterministic_lock_order(db_session) -> None:  # type: ignore[no-untyped-def]
    await create_source(db_session)
    event_a = await _human_event(db_session, title="Concurrent A")
    event_b = await _human_event(db_session, title="Concurrent B")
    event_a_id = event_a.id
    event_b_id = event_b.id

    async def merge_once(target_id, source_id):  # type: ignore[no-untyped-def]
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            try:
                result = await EventClusterMaintenanceService(session).merge(
                    target_event_id=target_id,
                    source_event_id=source_id,
                    reason="concurrent merge",
                    actor="editor",
                )
                return ("ok", result.id)
            except BusinessValidationError:
                return ("rejected", None)

    first, second = await asyncio.gather(
        merge_once(event_a_id, event_b_id),
        merge_once(event_b_id, event_a_id),
    )
    assert {first[0], second[0]} == {"ok", "rejected"}
    events = list((await db_session.scalars(select(EventRecord))).all())
    active = [event for event in events if event.merged_into_event_id is None]
    merged = [event for event in events if event.merged_into_event_id is not None]
    assert len(active) == 1
    assert len(merged) == 1
    assert merged[0].merged_into_event_id == active[0].id
