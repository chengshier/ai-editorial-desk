from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.clustering.evaluation import normalized_cluster_partition
from packages.clustering.services import (
    ClusteringBatchProcessor,
    ClusterOutcomeStatus,
    EventClusteringService,
)
from packages.database.models import EventSignalRecord
from tests.m3c_helpers import add_test_embeddings, create_m3c_signal, create_source


async def _build_scenario(
    db_session,  # type: ignore[no-untyped-def]
    source,
    *,
    name: str,
    base_time: datetime,
):  # type: ignore[no-untyped-def]
    specifications = {
        "A0": ("事件A", "事件A共同正文", (1.0, 0.0)),
        "A1": ("事件A", "事件A共同正文", (1.0, 0.0)),
        "A2": ("事件A", "事件A共同正文", (0.99, 0.01)),
        "A3": ("事件A", "事件A共同正文", (0.98, 0.02)),
        "B0": ("事件B", "事件B共同正文", (0.0, 1.0)),
        "B1": ("事件B", "事件B共同正文", (0.0, 1.0)),
        "B2": ("事件B", "事件B共同正文", (0.01, 0.99)),
        "C1": ("信息不足的边界事件", "目前无法确认归属", (0.70, 0.70)),
    }
    all_signals = {}
    vectors = {}
    for index, (label, (title, text, vector)) in enumerate(specifications.items()):
        signal = await create_m3c_signal(
            db_session,
            source,
            external_id=f"{name}-{label}",
            title=f"{name}-{title}",
            text=f"{name}-{text}",
            url=f"https://example.com/m3d/{name}/{label}",
            published_at=base_time + timedelta(minutes=index),
        )
        all_signals[label] = signal
        vectors[signal.id] = vector
    embedding_version = f"m3d-convergence-{name}"
    await add_test_embeddings(
        db_session,
        embedding_version=embedding_version,
        vectors=vectors,
    )
    seed_service = EventClusteringService(db_session)
    for label in ("A0", "B0"):
        seeded = await seed_service.cluster_signal(
            signal_id=all_signals[label].id,
            embedding_version=embedding_version,
            actor="m3d-convergence-seed",
        )
        assert seeded.status is ClusterOutcomeStatus.CREATED_EVENT
    targets = {
        label: signal
        for label, signal in all_signals.items()
        if label not in {"A0", "B0"}
    }
    return targets, embedding_version


async def _partition(db_session, signals):  # type: ignore[no-untyped-def]
    ids = [signal.id for signal in signals.values()]
    rows = list(
        (
            await db_session.execute(
                select(EventSignalRecord.signal_id, EventSignalRecord.event_id).where(
                    EventSignalRecord.signal_id.in_(ids)
                )
            )
        ).all()
    )
    by_signal = {signal_id: event_id for signal_id, event_id in rows}
    logical_memberships = {
        label: str(by_signal[signal.id]) if signal.id in by_signal else None
        for label, signal in signals.items()
    }
    await db_session.rollback()
    return normalized_cluster_partition(logical_memberships)


async def _process_order(
    db_session,  # type: ignore[no-untyped-def]
    signals,
    embedding_version: str,
    order: list[str],
):  # type: ignore[no-untyped-def]
    outcomes = {}
    service = EventClusteringService(db_session)
    for label in order:
        outcomes[label] = await service.cluster_signal(
            signal_id=signals[label].id,
            embedding_version=embedding_version,
            actor="m3d-convergence",
        )
    return outcomes


EXPECTED_PARTITION = frozenset(
    {
        frozenset({"A1", "A2", "A3"}),
        frozenset({"B1", "B2"}),
        frozenset({"C1"}),
    }
)


@pytest.mark.usefixtures("clean_database")
async def test_processing_order_converges_to_same_normalized_partition(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    forward_signals, forward_embedding = await _build_scenario(
        db_session,
        source,
        name="forward",
        base_time=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
    )
    forward_outcomes = await _process_order(
        db_session,
        forward_signals,
        forward_embedding,
        ["A1", "A2", "A3", "B1", "B2", "C1"],
    )
    forward_partition = await _partition(db_session, forward_signals)

    reverse_signals, reverse_embedding = await _build_scenario(
        db_session,
        source,
        name="reverse",
        base_time=datetime(2026, 8, 5, 1, 0, tzinfo=UTC),
    )
    reverse_outcomes = await _process_order(
        db_session,
        reverse_signals,
        reverse_embedding,
        ["C1", "B2", "B1", "A3", "A2", "A1"],
    )
    reverse_partition = await _partition(db_session, reverse_signals)

    assert forward_partition == reverse_partition == EXPECTED_PARTITION
    assert forward_outcomes["C1"].status is ClusterOutcomeStatus.AMBIGUOUS
    assert reverse_outcomes["C1"].status is ClusterOutcomeStatus.AMBIGUOUS


@pytest.mark.usefixtures("clean_database")
async def test_batch_boundaries_converge_and_ambiguous_signal_stays_unassigned(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    batch_one_signals, batch_one_embedding = await _build_scenario(
        db_session,
        source,
        name="batch-one",
        base_time=datetime(2026, 7, 20, 1, 0, tzinfo=UTC),
    )
    batch_one = await ClusteringBatchProcessor(db_session).process(
        signal_ids=[signal.id for signal in batch_one_signals.values()],
        embedding_version=batch_one_embedding,
        actor="m3d-convergence",
        batch_size=1,
    )
    batch_one_partition = await _partition(db_session, batch_one_signals)

    batch_three_signals, batch_three_embedding = await _build_scenario(
        db_session,
        source,
        name="batch-three",
        base_time=datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
    )
    batch_three = await ClusteringBatchProcessor(db_session).process(
        signal_ids=[signal.id for signal in batch_three_signals.values()],
        embedding_version=batch_three_embedding,
        actor="m3d-convergence",
        batch_size=3,
    )
    batch_three_partition = await _partition(db_session, batch_three_signals)

    assert batch_one_partition == batch_three_partition == EXPECTED_PARTITION
    assert batch_one.ambiguous == 1
    assert batch_three.ambiguous == 1
