import json
import time

from packages.clustering.services import ClusteringBatchProcessor
from packages.embeddings.services import SignalSimilarityService
from tests.m3c_helpers import add_test_embeddings, create_m3c_signal, create_source


async def test_exact_recall_and_clustering_engineering_performance_baseline(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    vectors = {
        0: (1.0, 0.0, 0.0, 0.0),
        1: (0.0, 1.0, 0.0, 0.0),
        2: (0.0, 0.0, 1.0, 0.0),
        3: (0.0, 0.0, 0.0, 1.0),
    }
    signals = []
    embedding_vectors = {}
    for index in range(20):
        group = index % 4
        signal = await create_m3c_signal(
            db_session,
            source,
            external_id=f"m3d-perf-{index}",
            title=f"性能基线事件 {group}",
            text=f"固定工程回归正文 group-{group}",
            url=f"https://example.com/m3d/perf/{index}",
        )
        signals.append(signal)
        embedding_vectors[signal.id] = vectors[group]
    embedding_version = "m3d-performance-fixed-4d-v1"
    await add_test_embeddings(
        db_session,
        embedding_version=embedding_version,
        vectors=embedding_vectors,
    )

    recall_query_count = 10
    candidate_top_k = 20
    recall_started = time.perf_counter()
    recall_counts = []
    recall_service = SignalSimilarityService(db_session)
    for signal in signals[:recall_query_count]:
        candidates = await recall_service.recall(
            signal_id=signal.id,
            embedding_version=embedding_version,
            top_k=candidate_top_k,
        )
        recall_counts.append(len(candidates))
    recall_elapsed_ms = (time.perf_counter() - recall_started) * 1000

    clustering_started = time.perf_counter()
    summary = await ClusteringBatchProcessor(db_session).process(
        signal_ids=[signal.id for signal in signals],
        embedding_version=embedding_version,
        actor="m3d-performance",
        batch_size=5,
    )
    clustering_elapsed_ms = (time.perf_counter() - clustering_started) * 1000

    baseline = {
        "kind": "OFFLINE_ENGINEERING_PERFORMANCE_BASELINE",
        "dataset_size": len(signals),
        "candidate_top_k": candidate_top_k,
        "dimensions": 4,
        "recall_query_count": recall_query_count,
        "recall_result_count_min": min(recall_counts),
        "recall_result_count_max": max(recall_counts),
        "recall_elapsed_ms": round(recall_elapsed_ms, 3),
        "clustering_processed_count": summary.processed,
        "clustering_elapsed_ms": round(clustering_elapsed_ms, 3),
        "strict_millisecond_sla": False,
    }
    print("M3_PERFORMANCE_BASELINE=" + json.dumps(baseline, sort_keys=True))

    assert all(count == len(signals) - 1 for count in recall_counts)
    assert summary.processed == len(signals)
    assert summary.failed == 0
