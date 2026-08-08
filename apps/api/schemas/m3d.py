from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from packages.clustering.reprocessing import ReprocessAction


class ClusteringEvaluationRequest(BaseModel):
    dataset_version: str = Field(default="m3-clustering-eval-v1", min_length=1, max_length=100)
    algorithm_version: str = Field(default="event-match-v1", min_length=1, max_length=100)
    threshold_sweep: bool = True


class ClusteringEvaluationResponse(BaseModel):
    evaluation_kind: str
    dataset_version: str
    algorithm_version: str
    fingerprint_version: str
    pair_metrics: dict[str, int | float]
    cluster_metrics: dict[str, int | float]
    human_override_respected_count: int
    human_override_total: int
    human_override_respect_rate: float
    performance: dict[str, int | float]
    threshold_sweep: list[dict[str, object]]
    threshold_sweep_read_only: bool = True
    production_policy_modified: bool = False


class ClusteringReprocessBaseRequest(BaseModel):
    signal_ids: list[UUID] | None = Field(default=None, max_length=100)
    time_from: datetime | None = None
    time_to: datetime | None = None
    algorithm_version: str = Field(min_length=1, max_length=100)
    embedding_version: str | None = Field(default=None, min_length=1, max_length=100)
    max_items: int = Field(default=100, ge=1, le=100)


class ClusteringReprocessApplyRequest(ClusteringReprocessBaseRequest):
    confirmation: bool = False


class ReprocessOutcomeResponse(BaseModel):
    signal_id: UUID
    action: ReprocessAction
    code: str
    current_event_id: UUID | None = None
    target_event_id: UUID | None = None
    candidate_signal_id: UUID | None = None
    decision: str | None = None
    score: float | None = None
    attached_by: str | None = None


class ClusteringReprocessResponse(BaseModel):
    processing_run_id: UUID | None
    algorithm_version: str
    dry_run: bool
    scanned: int
    would_attach: int
    would_create_event: int
    would_move: int
    would_detach: int
    ambiguous: int
    skipped_human: int
    suppressed: int
    unchanged: int
    failed: int
    outcomes: list[ReprocessOutcomeResponse]
