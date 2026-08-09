from pathlib import Path

from packages.clustering.evaluation import (
    ClusteringEvaluationService,
    EvaluationPairLabel,
    PairPrediction,
    load_evaluation_dataset,
    normalized_cluster_partition,
    threshold_sweep,
)
from packages.clustering.policy import DEFAULT_CLUSTER_POLICY

DATASET = Path("tests/evaluation/m3_clustering_eval_v1.jsonl")


def test_m3_evaluation_dataset_is_versioned_deterministic_and_covers_required_cases() -> None:
    signals = load_evaluation_dataset(DATASET)
    assert len(signals) == 20
    tags = {tag for signal in signals for tag in signal.tags}
    required = {
        "exact_duplicate",
        "canonical_url_duplicate",
        "same_content_cross_platform",
        "light_rewrite",
        "same_event_media",
        "eyewitness",
        "official_response",
        "correction",
        "different_city_similar_event",
        "same_keywords_far_date",
        "high_embedding_similarity_distinct",
        "low_lexical_overlap",
        "chinese",
        "english",
        "short_text",
        "empty_text",
        "multiple_candidate_event",
        "intentionally_ambiguous",
        "human_merge",
        "human_split",
    }
    assert required <= tags
    assert all(signal.embedding is None or len(signal.embedding) == 4 for signal in signals)


def test_pair_metrics_treat_ambiguous_as_abstention_not_false_negative() -> None:
    predictions = [
        PairPrediction(
            left_fixture_id="a",
            right_fixture_id="b",
            truth=EvaluationPairLabel.SAME_EVENT,
            prediction=EvaluationPairLabel.SAME_EVENT,
            score=1.0,
            method="test",
        ),
        PairPrediction(
            left_fixture_id="a",
            right_fixture_id="c",
            truth=EvaluationPairLabel.SAME_EVENT,
            prediction=EvaluationPairLabel.AMBIGUOUS,
            score=0.7,
            method="test",
        ),
        PairPrediction(
            left_fixture_id="a",
            right_fixture_id="d",
            truth=EvaluationPairLabel.DISTINCT,
            prediction=EvaluationPairLabel.DISTINCT,
            score=0.0,
            method="test",
        ),
    ]
    metrics = ClusteringEvaluationService._pair_metrics(predictions)
    assert metrics.true_positive == 1
    assert metrics.false_negative == 0
    assert metrics.true_negative == 1
    assert metrics.ambiguous_count == 1
    assert metrics.coverage == 2 / 3
    assert metrics.abstention_rate == 1 / 3


def test_cluster_pairwise_metrics_use_normalized_partition_not_event_uuid() -> None:
    signals = load_evaluation_dataset(DATASET)
    selected = tuple(
        signal
        for signal in signals
        if signal.fixture_id
        in {"metro_news_rss", "metro_news_weibo", "stadium_city_a"}
    )
    metrics = ClusteringEvaluationService._cluster_metrics(
        selected,
        (("metro_news_rss", "metro_news_weibo"), ("stadium_city_a",)),
    )
    assert metrics.pairwise_precision == 1.0
    assert metrics.pairwise_recall == 1.0
    assert metrics.pairwise_f1 == 1.0
    assert metrics.overmerge_count == 0
    assert metrics.fragmentation_count == 0


def test_offline_evaluation_is_repeatable_and_human_overrides_are_hard_priority() -> None:
    signals = load_evaluation_dataset(DATASET)
    first = ClusteringEvaluationService().evaluate(signals)
    second = ClusteringEvaluationService().evaluate(signals)
    assert first.dataset_version == "m3-clustering-eval-v1"
    assert first.algorithm_version == "event-match-v1"
    assert first.predictions == second.predictions
    assert first.partition == second.partition
    assert first.pair_metrics == second.pair_metrics
    assert first.cluster_metrics == second.cluster_metrics
    assert first.human_override_total == 3
    assert first.human_override_respected_count == 3
    assert first.human_override_respect_rate == 1.0
    assert 0.0 <= first.pair_metrics.coverage <= 1.0
    assert 0.0 <= first.pair_metrics.abstention_rate <= 1.0


def test_threshold_sweep_is_bounded_and_does_not_change_default_policy() -> None:
    signals = load_evaluation_dataset(DATASET)
    before = DEFAULT_CLUSTER_POLICY
    candidates = threshold_sweep(signals)
    assert len(candidates) == 11
    assert candidates[0].name == "baseline"
    assert all(item.policy["algorithm_version"] == "event-match-v1" for item in candidates)
    assert DEFAULT_CLUSTER_POLICY == before
    assert DEFAULT_CLUSTER_POLICY.algorithm_version == "event-match-v1"
    assert DEFAULT_CLUSTER_POLICY.embedding_same_event_threshold == 0.90


def test_normalized_cluster_partition_ignores_event_uuid_identity() -> None:
    first = normalized_cluster_partition(
        {"a1": "event-x", "a2": "event-x", "b1": "event-y", "c1": None}
    )
    second = normalized_cluster_partition(
        {"a1": "different-1", "a2": "different-1", "b1": "different-2", "c1": None}
    )
    assert first == second
