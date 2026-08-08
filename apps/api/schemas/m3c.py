from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from packages.clustering.services import ClusterOutcomeStatus
from packages.database.models import MatchDecisionType, MatchPrimaryMethod


class ClusteringPreviewRequest(BaseModel):
    signal_id: UUID
    embedding_version: str | None = Field(default=None, min_length=1, max_length=100)


class FingerprintPreviewResponse(BaseModel):
    fingerprint_version: str
    input_hash: str
    simhash: str
    token_count: int


class MatchDecisionResponse(BaseModel):
    candidate_signal_id: UUID
    decision: MatchDecisionType
    primary_method: MatchPrimaryMethod
    score: float
    components: dict[str, object]
    algorithm_version: str


class ClusteringPreviewResponse(BaseModel):
    signal_id: UUID
    fingerprint: FingerprintPreviewResponse | None
    decisions: list[MatchDecisionResponse]


class ClusterSignalRequest(BaseModel):
    embedding_version: str | None = Field(default=None, min_length=1, max_length=100)


class ClusterOutcomeResponse(BaseModel):
    signal_id: UUID
    status: ClusterOutcomeStatus
    code: str
    event_id: UUID | None = None
    candidate_event_ids: list[UUID] = Field(default_factory=list)


class ClusterBatchRequest(BaseModel):
    signal_ids: list[UUID] = Field(min_length=1, max_length=100)
    embedding_version: str | None = Field(default=None, min_length=1, max_length=100)
    batch_size: int = Field(default=25, ge=1, le=100)


class ClusterBatchResponse(BaseModel):
    requested: int
    processed: int
    attached: int
    created_event: int
    ambiguous: int
    skipped: int
    failed: int
    outcomes: list[ClusterOutcomeResponse]


class EventMergeRequest(BaseModel):
    source_event_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class EventSplitRequest(BaseModel):
    signal_ids: list[UUID] = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
