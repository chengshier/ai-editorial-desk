import pytest

from packages.clustering.services import ClusteringBatchProcessor
from packages.connector_management.exceptions import BusinessValidationError
from tests.m3c_helpers import create_m3c_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_bounded_batch_processes_unique_signal_ids_with_counters(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="batch-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="batch-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营。最新",
    )
    empty = await create_m3c_signal(
        db_session,
        source,
        external_id="batch-empty",
        title=" ",
        text="",
    )
    summary = await ClusteringBatchProcessor(db_session).process(
        signal_ids=[second.id, first.id, empty.id, second.id],
        embedding_version=None,
        actor="batch-test",
        batch_size=2,
    )
    assert summary.requested == 3
    assert summary.processed == 3
    assert summary.created_event == 1
    assert summary.attached == 1
    assert summary.skipped == 1
    assert summary.ambiguous == 0
    assert summary.failed == 0
    assert [item.signal_id for item in summary.outcomes] == sorted(
        {first.id, second.id, empty.id}, key=lambda value: value.int
    )


@pytest.mark.usefixtures("clean_database")
async def test_batch_size_is_bounded(db_session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(BusinessValidationError):
        await ClusteringBatchProcessor(db_session).process(
            signal_ids=[],
            embedding_version=None,
            actor="batch-test",
            batch_size=101,
        )
