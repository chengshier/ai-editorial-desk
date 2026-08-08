from sqlalchemy import select

from packages.clustering.reprocessing import ClusteringReprocessService
from packages.clustering.services import EventClusterMaintenanceService
from packages.database.models import EventRecord, EventSignalRecord
from tests.m3c_helpers import auto_cluster, create_m3c_signal, create_source


async def test_manual_split_boundary_is_not_restored_by_reprocessing(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signals = [
        await create_m3c_signal(
            db_session,
            source,
            external_id=f"m3d-split-{index}",
            title="同一事件人工拆分",
            text="算法原本会把这些信号放在一起",
            url=f"https://example.com/m3d/split/{index}",
        )
        for index in range(3)
    ]
    outcomes = [await auto_cluster(db_session, signal.id) for signal in signals]
    original_event_id = outcomes[0].event_id
    assert original_event_id is not None
    assert all(item.event_id == original_event_id for item in outcomes)

    new_event = await EventClusterMaintenanceService(db_session).split(
        event_id=original_event_id,
        signal_ids=[signals[2].id],
        title="人工拆出的现实事件",
        reason="人工确认不是同一现实事件",
        actor="m3d-human-test",
    )

    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=[signals[2].id],
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=1,
        actor="m3d-reprocess",
        apply=True,
        confirmed=True,
    )
    assert summary.would_move == 0
    assert summary.would_detach == 0
    membership = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == signals[2].id)
    )
    assert membership is not None
    assert membership.event_id == new_event.id


async def test_manual_merge_is_not_reversed_by_reprocessing(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="m3d-merge-a",
        title="人工认为同一事件的第一条",
        text="算法证据很弱的文本一",
        url="https://example.com/m3d/merge/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="m3d-merge-b",
        title="人工认为同一事件的第二条",
        text="完全不同措辞的文本二",
        url="https://example.com/m3d/merge/b",
    )
    first_outcome = await auto_cluster(db_session, first.id)
    second_outcome = await auto_cluster(db_session, second.id)
    assert first_outcome.event_id is not None
    assert second_outcome.event_id is not None
    assert first_outcome.event_id != second_outcome.event_id

    target = await EventClusterMaintenanceService(db_session).merge(
        target_event_id=first_outcome.event_id,
        source_event_id=second_outcome.event_id,
        reason="人工确认两条属于同一现实事件",
        actor="m3d-human-test",
    )
    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=[second.id],
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=1,
        actor="m3d-reprocess",
        apply=True,
        confirmed=True,
    )
    assert summary.would_move == 0
    assert summary.would_detach == 0
    membership = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == second.id)
    )
    assert membership is not None
    assert membership.event_id == target.id
    merged_source = await db_session.get(EventRecord, second_outcome.event_id)
    assert merged_source is not None
    assert merged_source.merged_into_event_id == target.id
