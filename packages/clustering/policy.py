from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from packages.clustering.fingerprints import SIGNAL_FINGERPRINT_VERSION

MATCHING_ALGORITHM_VERSION = "event-match-v1"


@dataclass(frozen=True, slots=True)
class ClusterPolicy:
    """Versioned conservative M3-C regression policy; M3-D will calibrate it."""

    algorithm_version: str = MATCHING_ALGORITHM_VERSION
    fingerprint_version: str = SIGNAL_FINGERPRINT_VERSION
    simhash_duplicate_max_distance: int = 4
    simhash_candidate_max_distance: int = 18
    embedding_same_event_threshold: float = 0.90
    embedding_distinct_threshold: float = 0.55
    same_event_score_threshold: float = 0.84
    distinct_score_threshold: float = 0.50
    ambiguous_margin: float = 0.04
    max_time_gap: timedelta = timedelta(hours=72)
    max_candidates: int = 20
    max_fingerprint_scan: int = 500
    max_batch_size: int = 100
    max_split_override_pairs: int = 5000

    def __post_init__(self) -> None:
        if not self.algorithm_version.strip() or not self.fingerprint_version.strip():
            raise ValueError("algorithm/fingerprint version must be non-empty")
        if not 0 <= self.simhash_duplicate_max_distance <= self.simhash_candidate_max_distance <= 64:
            raise ValueError("invalid SimHash distance policy")
        for value in (
            self.embedding_same_event_threshold,
            self.embedding_distinct_threshold,
            self.same_event_score_threshold,
            self.distinct_score_threshold,
        ):
            if not 0 <= value <= 1:
                raise ValueError("score thresholds must be in [0, 1]")
        if self.embedding_distinct_threshold >= self.embedding_same_event_threshold:
            raise ValueError("embedding distinct threshold must be lower than same-event threshold")
        if self.distinct_score_threshold >= self.same_event_score_threshold:
            raise ValueError("distinct score threshold must be lower than same-event threshold")
        if self.ambiguous_margin < 0 or self.ambiguous_margin >= 0.5:
            raise ValueError("ambiguous margin must be in [0, 0.5)")
        if self.same_event_score_threshold + self.ambiguous_margin > 1:
            raise ValueError("same-event threshold plus ambiguous margin cannot exceed 1")
        if self.max_time_gap.total_seconds() <= 0:
            raise ValueError("max_time_gap must be positive")
        if self.max_candidates < 1 or self.max_fingerprint_scan < self.max_candidates:
            raise ValueError("candidate bounds are invalid")
        if self.max_batch_size < 1 or self.max_split_override_pairs < 1:
            raise ValueError("batch/split bounds must be positive")


DEFAULT_CLUSTER_POLICY = ClusterPolicy()
