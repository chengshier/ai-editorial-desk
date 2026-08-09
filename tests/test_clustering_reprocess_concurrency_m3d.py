import asyncio

from sqlalchemy import func, select

from packages.clustering.reprocessing import ClusteringReprocessService
from packages.database.models import (
    EventAssignmentAction,
    EventAssignmentRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
)
from packages.database.session import get_async_sessionmaker
from packages.events.services import EventService
from tests.m3c_helpers import create_m3c_signal, create_source


async def _create_fragment(db_session, signal_id, title: str):  # type: ignore[no-untyped-def]
    service = EventService(db_session)
    event = await service.create(
        title=title,
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m3d-concurrency-setup",
    )
    await service.attach_signal(
        event_id=event.id,
        signal_id=signal_id,
        relation=EventSignalRelation.RELATED,
        confidence=1.0,
        attached_by=EventSignalAttachedBy.RULE,
        actor="m3d-concurrency-setup",
    )
    return event


async def test_concurrent_reprocess_apply_converges_without_duplicate_move(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="concurrent-reprocess-a",
        title="并发碎片事件",
        text="相同正文用于模拟两个 worker 各建了一个 Event",
        url="https://example.com/m3d/concurrent/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="concurrent-reprocess-b",
        title="并发碎片事件",
        text="相同正文用于模拟两个 worker 各建了一个 Event",
        url="https://example.com/m3d/concurrent/b",
    )
    first_event = await _create_fragment(db_session, first.id, "Fragment A")
    second_event = await _create_fragment(db_session, second.id, "Fragment B")
    first_event_id = first_event.id
    second_event_id = second_event.id
    all_signal_ids = [first.id, second.id]
    movable_signal_id = (
        second.id if first_event_id.int < second_event_id.int else first.id
    )
    target_signal_ids = [movable_signal_id]
    expected_event_id = min((first_event_id, second_event_id), key=lambda value: value.int)
    await db_session.rollback()

    async def apply_once(actor: str):
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            return await ClusteringReprocessService(session).reprocess(
                signal_ids=target_signal_ids,
                time_from=None,
                time_to=None,
                algorithm_version="event-match-v1",
                embedding_version=None,
                max_items=1,
                actor=actor,
                apply=True,
                confirmed=True,
            )

    left, right = await asyncio.wait_for(
        asyncio.gather(
            apply_once("m3d-concurrent-left"),
            apply_once("m3d-concurrent-right"),
        ),
        timeout=30.0,
    )
    assert left.scanned == right.scanned == 1
    assert left.failed == right.failed == 0
    assert left.would_move + right.would_move == 1
    memberships = list(
        (
            await db_session.execute(
                select(EventSignalRecord.signal_id, EventSignalRecord.event_id).where(
                    EventSignalRecord.signal_id.in_(all_signal_ids)
                )
            )
        ).all()
    )
    assert len(memberships) == 2
    assert {event_id for _signal_id, event_id in memberships} == {expected_event_id}
    move_count = int(
        await db_session.scalar(
            select(func.count()).select_from(EventAssignmentRecord).where(
                EventAssignmentRecord.action == EventAssignmentAction.MOVE
            )
        )
        or 0
    )
    assert move_count == 1
