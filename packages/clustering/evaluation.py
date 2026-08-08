from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from packages.clustering.fingerprints import FingerprintInputBuilder, hamming_distance
from packages.clustering.policy import DEFAULT_CLUSTER_POLICY, ClusterPolicy
from packages.database.models import RawSignalRecord

M3_EVALUATION_DATASET_VERSION = "m3-clustering-eval-v1"


class EvaluationPairLabel(StrEnum):
    SAME_EVENT = "same_event"
    DISTINCT = "distinct"
    AMBIGUOUS = "ambiguous"


class EvaluationExpectedOutcome(StrEnum):
    CLUSTERED = "clustered"
    AMBIGUOUS = "ambiguous"
    UNASSIGNED = "unassigned"


@dataclass(frozen=True, slots=True)
class EvaluationSignal:
    fixture_id: str
    expected_event_key: str | None
    expected_outcome: EvaluationExpectedOutcome
    title: str | None
    text: str | None
    platform: str
    canonical_url: str
    external_id: str | None
    published_at: datetime
    language: str | None
    embedding: tuple[float, ...] | None
    tags: tuple[str, ...]
    pair_labels: dict[str, EvaluationPairLabel]
    human_overrides: dict[str, EvaluationPairLabel]

    @property
    def signal_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"m3-eval:{self.fixture_id}")


@dataclass(frozen=True, slots=True)
class PairPrediction:
    left_fixture_id: str
    right_fixture_id: str
    truth: EvaluationPairLabel
    prediction: EvaluationPairLabel
    score: float
    method: str


@dataclass(frozen=True, slots=True)
class PairMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float
    recall: float
    f1: float
    ambiguous_count: int
    ground_truth_ambiguous_count: int
    coverage: float
    abstention_rate: float


@dataclass(frozen=True, slots=True)
class ClusterMetrics:
    pairwise_precision: float
    pairwise_recall: float
    pairwise_f1: float
    overmerge_count: int
    fragmentation_count: int
    unassigned_count: int
    auto_created_event_count: int
    auto_attached_count: int


@dataclass(frozen=True, slots=True)
class EvaluationPerformance:
    dataset_size: int
    pair_query_count: int
    embedding_dimensions: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    dataset_version: str
    algorithm_version: str
    fingerprint_version: str
    pair_metrics: PairMetrics
    cluster_metrics: ClusterMetrics
    human_override_respected_count: int
    human_override_total: int
    human_override_respect_rate: float
    partition: tuple[tuple[str, ...], ...]
    predictions: tuple[PairPrediction, ...]
    performance: EvaluationPerformance

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["partition"] = [list(cluster) for cluster in self.partition]
        return payload


@dataclass(frozen=True, slots=True)
class ThresholdSweepCandidate:
    name: str
    policy: dict[str, object]
    pair_metrics: PairMetrics
    cluster_metrics: ClusterMetrics


@dataclass(slots=True)
class _EvaluationSignalView:
    id: UUID
    title: str | None
    text: str | None


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _content_hash(signal: EvaluationSignal) -> str | None:
    title = _normalize_text(signal.title)
    body = _normalize_text(signal.text)
    if not title and not body:
        return None
    payload = f"{title}\n{body}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("evaluation embeddings must share one non-zero dimension")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("evaluation embeddings must be non-zero")
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _explicit_pair_label(
    left: EvaluationSignal,
    right: EvaluationSignal,
) -> EvaluationPairLabel | None:
    return left.pair_labels.get(right.fixture_id) or right.pair_labels.get(left.fixture_id)


def _human_override(
    left: EvaluationSignal,
    right: EvaluationSignal,
) -> EvaluationPairLabel | None:
    return left.human_overrides.get(right.fixture_id) or right.human_overrides.get(
        left.fixture_id
    )


def _ground_truth(left: EvaluationSignal, right: EvaluationSignal) -> EvaluationPairLabel:
    explicit = _explicit_pair_label(left, right)
    if explicit is not None:
        return explicit
    if (
        left.expected_outcome is EvaluationExpectedOutcome.AMBIGUOUS
        or right.expected_outcome is EvaluationExpectedOutcome.AMBIGUOUS
    ):
        return EvaluationPairLabel.AMBIGUOUS
    if (
        left.expected_event_key is not None
        and left.expected_event_key == right.expected_event_key
    ):
        return EvaluationPairLabel.SAME_EVENT
    return EvaluationPairLabel.DISTINCT


def _fingerprint(signal: EvaluationSignal, builder: FingerprintInputBuilder) -> str | None:
    view = _EvaluationSignalView(id=signal.signal_id, title=signal.title, text=signal.text)
    result = builder.fingerprint(cast(RawSignalRecord, view))
    return result.simhash if result is not None else None


def _policy_dict(policy: ClusterPolicy) -> dict[str, object]:
    return {
        "algorithm_version": policy.algorithm_version,
        "fingerprint_version": policy.fingerprint_version,
        "simhash_duplicate_max_distance": policy.simhash_duplicate_max_distance,
        "simhash_candidate_max_distance": policy.simhash_candidate_max_distance,
        "embedding_same_event_threshold": policy.embedding_same_event_threshold,
        "embedding_distinct_threshold": policy.embedding_distinct_threshold,
        "same_event_score_threshold": policy.same_event_score_threshold,
        "distinct_score_threshold": policy.distinct_score_threshold,
        "ambiguous_margin": policy.ambiguous_margin,
        "max_time_gap_seconds": int(policy.max_time_gap.total_seconds()),
    }


def load_evaluation_dataset(path: Path) -> tuple[EvaluationSignal, ...]:
    signals: list[EvaluationSignal] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if payload.get("dataset_version") != M3_EVALUATION_DATASET_VERSION:
            raise ValueError(f"line {line_number}: unexpected dataset_version")
        fixture_id = str(payload["fixture_id"]).strip()
        if not fixture_id or fixture_id in seen:
            raise ValueError(f"line {line_number}: duplicate or empty fixture_id")
        seen.add(fixture_id)
        published_at = datetime.fromisoformat(
            str(payload["published_at"]).replace("Z", "+00:00")
        )
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError(f"line {line_number}: published_at must be timezone-aware")
        embedding_payload = payload.get("embedding")
        embedding = (
            tuple(float(value) for value in embedding_payload)
            if embedding_payload is not None
            else None
        )
        signals.append(
            EvaluationSignal(
                fixture_id=fixture_id,
                expected_event_key=payload.get("expected_event_key"),
                expected_outcome=EvaluationExpectedOutcome(
                    payload.get("expected_outcome", "clustered")
                ),
                title=payload.get("title"),
                text=payload.get("text"),
                platform=str(payload["platform"]),
                canonical_url=str(payload.get("canonical_url") or ""),
                external_id=payload.get("external_id"),
                published_at=published_at.astimezone(UTC),
                language=payload.get("language"),
                embedding=embedding,
                tags=tuple(str(value) for value in payload.get("tags", [])),
                pair_labels={
                    str(key): EvaluationPairLabel(value)
                    for key, value in payload.get("pair_labels", {}).items()
                },
                human_overrides={
                    str(key): EvaluationPairLabel(value)
                    for key, value in payload.get("human_overrides", {}).items()
                },
            )
        )
    if len(signals) < 2:
        raise ValueError("evaluation dataset must contain at least two signals")
    dimensions = {len(signal.embedding) for signal in signals if signal.embedding is not None}
    if len(dimensions) > 1:
        raise ValueError("evaluation embeddings must use one fixed dimension")
    return tuple(signals)


class ClusteringEvaluationService:
    """Deterministic offline engineering evaluation over manually-authored fixtures."""

    def __init__(self, *, policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY) -> None:
        self.policy = policy
        self.fingerprint_builder = FingerprintInputBuilder()

    def evaluate(self, signals: tuple[EvaluationSignal, ...]) -> EvaluationResult:
        started = time.perf_counter()
        predictions: list[PairPrediction] = []
        human_total = 0
        human_respected = 0
        for index, left in enumerate(signals):
            for right in signals[index + 1 :]:
                truth = _ground_truth(left, right)
                override = _human_override(left, right)
                prediction, score, method = self._predict_pair(left, right, override=override)
                if override is not None:
                    human_total += 1
                    if prediction is override:
                        human_respected += 1
                predictions.append(
                    PairPrediction(
                        left_fixture_id=left.fixture_id,
                        right_fixture_id=right.fixture_id,
                        truth=truth,
                        prediction=prediction,
                        score=score,
                        method=method,
                    )
                )
        pair_metrics = self._pair_metrics(predictions)
        partition = self._partition(signals, predictions)
        cluster_metrics = self._cluster_metrics(signals, partition)
        dimensions = next(
            (len(signal.embedding) for signal in signals if signal.embedding is not None),
            0,
        )
        performance = EvaluationPerformance(
            dataset_size=len(signals),
            pair_query_count=len(predictions),
            embedding_dimensions=dimensions,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return EvaluationResult(
            dataset_version=M3_EVALUATION_DATASET_VERSION,
            algorithm_version=self.policy.algorithm_version,
            fingerprint_version=self.policy.fingerprint_version,
            pair_metrics=pair_metrics,
            cluster_metrics=cluster_metrics,
            human_override_respected_count=human_respected,
            human_override_total=human_total,
            human_override_respect_rate=_safe_ratio(human_respected, human_total),
            partition=partition,
            predictions=tuple(predictions),
            performance=performance,
        )

    def _predict_pair(
        self,
        left: EvaluationSignal,
        right: EvaluationSignal,
        *,
        override: EvaluationPairLabel | None,
    ) -> tuple[EvaluationPairLabel, float, str]:
        if override is not None:
            return (
                override,
                1.0 if override is EvaluationPairLabel.SAME_EVENT else 0.0,
                "human",
            )
        exact_method = self._exact_method(left, right)
        if exact_method is not None:
            return EvaluationPairLabel.SAME_EVENT, 1.0, exact_method
        time_gap = abs((left.published_at - right.published_at).total_seconds())
        within_window = time_gap <= self.policy.max_time_gap.total_seconds()
        left_simhash = _fingerprint(left, self.fingerprint_builder)
        right_simhash = _fingerprint(right, self.fingerprint_builder)
        simhash_distance: int | None = None
        if within_window and left_simhash is not None and right_simhash is not None:
            distance = hamming_distance(left_simhash, right_simhash)
            if distance <= self.policy.simhash_candidate_max_distance:
                simhash_distance = distance
        embedding_similarity: float | None = None
        if within_window and left.embedding is not None and right.embedding is not None:
            embedding_similarity = _cosine(left.embedding, right.embedding)
        if simhash_distance is None and embedding_similarity is None:
            return EvaluationPairLabel.DISTINCT, 0.0, "no_candidate"
        if (
            simhash_distance is not None
            and simhash_distance <= self.policy.simhash_duplicate_max_distance
        ):
            score = min(
                1.0,
                0.96
                + 0.01
                * (self.policy.simhash_duplicate_max_distance - simhash_distance),
            )
            return EvaluationPairLabel.SAME_EVENT, score, "simhash"
        simhash_component = 0.0
        if simhash_distance is not None:
            simhash_component = max(
                0.0,
                min(
                    1.0,
                    1.0 - simhash_distance / self.policy.simhash_candidate_max_distance,
                ),
            )
        time_component = max(
            0.0,
            min(1.0, 1.0 - time_gap / self.policy.max_time_gap.total_seconds()),
        )
        if embedding_similarity is not None:
            embedding_component = max(
                0.0,
                min(1.0, (embedding_similarity + 1.0) / 2.0),
            )
            score = (
                0.75 * embedding_component
                + 0.15 * simhash_component
                + 0.10 * time_component
            )
            method = "combined"
        else:
            score = 0.70 * simhash_component + 0.30 * time_component
            method = "simhash"
        score = max(0.0, min(1.0, score))
        high_boundary = self.policy.same_event_score_threshold + self.policy.ambiguous_margin
        distinct_boundary = max(
            0.0,
            self.policy.distinct_score_threshold - self.policy.ambiguous_margin,
        )
        if (
            embedding_similarity is not None
            and embedding_similarity >= self.policy.embedding_same_event_threshold
            and score >= high_boundary
        ):
            return EvaluationPairLabel.SAME_EVENT, score, method
        if (
            embedding_similarity is not None
            and embedding_similarity <= self.policy.embedding_distinct_threshold
            and simhash_component == 0
        ) or score <= distinct_boundary:
            return EvaluationPairLabel.DISTINCT, score, method
        return EvaluationPairLabel.AMBIGUOUS, score, method

    def _exact_method(
        self, left: EvaluationSignal, right: EvaluationSignal
    ) -> str | None:
        if (
            left.external_id
            and right.external_id
            and left.platform == right.platform
            and left.external_id.strip() == right.external_id.strip()
        ):
            return "external_id"
        if left.canonical_url and left.canonical_url == right.canonical_url:
            return "canonical_url"
        left_hash = _content_hash(left)
        right_hash = _content_hash(right)
        if left_hash is not None and left_hash == right_hash:
            return "content_hash"
        return None

    @staticmethod
    def _pair_metrics(predictions: list[PairPrediction]) -> PairMetrics:
        tp = fp = fn = tn = ambiguous = truth_ambiguous = 0
        resolvable = 0
        covered = 0
        for item in predictions:
            if item.truth is EvaluationPairLabel.AMBIGUOUS:
                truth_ambiguous += 1
                if item.prediction is EvaluationPairLabel.AMBIGUOUS:
                    ambiguous += 1
                continue
            resolvable += 1
            if item.prediction is EvaluationPairLabel.AMBIGUOUS:
                ambiguous += 1
                continue
            covered += 1
            if item.truth is EvaluationPairLabel.SAME_EVENT:
                if item.prediction is EvaluationPairLabel.SAME_EVENT:
                    tp += 1
                else:
                    fn += 1
            elif item.prediction is EvaluationPairLabel.SAME_EVENT:
                fp += 1
            else:
                tn += 1
        precision = _safe_ratio(tp, tp + fp)
        recall = _safe_ratio(tp, tp + fn)
        return PairMetrics(
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            true_negative=tn,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
            ambiguous_count=ambiguous,
            ground_truth_ambiguous_count=truth_ambiguous,
            coverage=_safe_ratio(covered, resolvable),
            abstention_rate=_safe_ratio(resolvable - covered, resolvable),
        )

    @staticmethod
    def _partition(
        signals: tuple[EvaluationSignal, ...],
        predictions: list[PairPrediction],
    ) -> tuple[tuple[str, ...], ...]:
        parent = {signal.fixture_id: signal.fixture_id for signal in signals}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root == right_root:
                return
            smaller, larger = sorted((left_root, right_root))
            parent[larger] = smaller

        for item in predictions:
            if item.prediction is EvaluationPairLabel.SAME_EVENT:
                union(item.left_fixture_id, item.right_fixture_id)
        groups: dict[str, list[str]] = {}
        for fixture_id in parent:
            groups.setdefault(find(fixture_id), []).append(fixture_id)
        normalized = [tuple(sorted(values)) for values in groups.values()]
        normalized.sort()
        return tuple(normalized)

    @staticmethod
    def _cluster_metrics(
        signals: tuple[EvaluationSignal, ...],
        partition: tuple[tuple[str, ...], ...],
    ) -> ClusterMetrics:
        by_id = {signal.fixture_id: signal for signal in signals}
        predicted_pairs: set[tuple[str, str]] = set()
        for cluster in partition:
            for index, left in enumerate(cluster):
                for right in cluster[index + 1 :]:
                    predicted_pairs.add(_pair_key(left, right))
        truth_pairs: set[tuple[str, str]] = set()
        truth_groups: dict[str, list[str]] = {}
        for signal in signals:
            if signal.expected_event_key is None:
                continue
            truth_groups.setdefault(signal.expected_event_key, []).append(signal.fixture_id)
        for fixtures in truth_groups.values():
            for index, left in enumerate(fixtures):
                for right in fixtures[index + 1 :]:
                    truth_pairs.add(_pair_key(left, right))
        tp = len(predicted_pairs & truth_pairs)
        precision = _safe_ratio(tp, len(predicted_pairs))
        recall = _safe_ratio(tp, len(truth_pairs))
        overmerge = 0
        for cluster in partition:
            keys = {
                by_id[fixture_id].expected_event_key
                for fixture_id in cluster
                if by_id[fixture_id].expected_event_key is not None
            }
            if len(keys) > 1:
                overmerge += 1
        cluster_by_fixture = {
            fixture_id: index
            for index, cluster in enumerate(partition)
            for fixture_id in cluster
        }
        fragmentation = sum(
            len({cluster_by_fixture[fixture_id] for fixture_id in fixtures}) > 1
            for fixtures in truth_groups.values()
        )
        clustered_partition = [
            cluster
            for cluster in partition
            if any(
                by_id[fixture_id].expected_outcome is EvaluationExpectedOutcome.CLUSTERED
                for fixture_id in cluster
            )
        ]
        auto_attached = sum(max(0, len(cluster) - 1) for cluster in clustered_partition)
        return ClusterMetrics(
            pairwise_precision=precision,
            pairwise_recall=recall,
            pairwise_f1=_f1(precision, recall),
            overmerge_count=overmerge,
            fragmentation_count=fragmentation,
            unassigned_count=sum(
                signal.expected_outcome is EvaluationExpectedOutcome.UNASSIGNED
                for signal in signals
            ),
            auto_created_event_count=len(clustered_partition),
            auto_attached_count=auto_attached,
        )


def threshold_sweep(
    signals: tuple[EvaluationSignal, ...],
    *,
    baseline: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
) -> tuple[ThresholdSweepCandidate, ...]:
    candidates: list[tuple[str, ClusterPolicy]] = [("baseline", baseline)]
    for value in (4, 8):
        candidates.append(
            (
                f"simhash_duplicate_max_distance={value}",
                replace(baseline, simhash_duplicate_max_distance=value),
            )
        )
    for value in (0.88, 0.92):
        candidates.append(
            (
                f"embedding_same_event_threshold={value}",
                replace(baseline, embedding_same_event_threshold=value),
            )
        )
    for value in (0.50, 0.60):
        candidates.append(
            (
                f"embedding_distinct_threshold={value}",
                replace(baseline, embedding_distinct_threshold=value),
            )
        )
    for value in (0.02, 0.06):
        candidates.append(
            (
                f"ambiguous_margin={value}",
                replace(baseline, ambiguous_margin=value),
            )
        )
    for hours in (48, 96):
        candidates.append(
            (
                f"max_time_gap_hours={hours}",
                replace(baseline, max_time_gap=timedelta(hours=hours)),
            )
        )
    results: list[ThresholdSweepCandidate] = []
    for name, policy in candidates:
        result = ClusteringEvaluationService(policy=policy).evaluate(signals)
        results.append(
            ThresholdSweepCandidate(
                name=name,
                policy=_policy_dict(policy),
                pair_metrics=result.pair_metrics,
                cluster_metrics=result.cluster_metrics,
            )
        )
    return tuple(results)


def normalized_cluster_partition(
    memberships: dict[str, str | None],
) -> frozenset[frozenset[str]]:
    groups: dict[str, set[str]] = {}
    for signal_id, event_id in memberships.items():
        key = event_id if event_id is not None else f"__unassigned__:{signal_id}"
        groups.setdefault(key, set()).add(signal_id)
    return frozenset(frozenset(values) for values in groups.values())
