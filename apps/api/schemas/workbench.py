from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.schemas.m3a import EventResponse
from apps.api.schemas.m4c import EditorialScoreResponse, TrendSnapshotResponse
from apps.api.schemas.m4d import EditorialPackResponse, EventCardResponse
from apps.api.schemas.m5b import (
    CandidateRunResponse,
    CandidateSnapshotResponse,
    EditorialDecisionResponse,
)
from packages.database.models import EventSignalAttachedBy, EventSignalRelation


class WorkbenchEvidenceCounts(BaseModel):
    confirmed: int = 0
    investigating: int = 0
    single_source: int = 0
    disputed: int = 0
    false: int = 0


class WorkbenchEffectiveEditorial(BaseModel):
    emotion: int
    information_gap: int
    visual_value: int
    user_relevance: int
    discussion: int
    novelty: int
    extendability: int
    traffic_total: float
    risk_level: str
    recommended_format: str
    model_reason: str | None = None
    base_score_id: str
    base_source_type: str


class WorkbenchEventItem(BaseModel):
    event: EventResponse
    latest_trend: TrendSnapshotResponse | None
    latest_ai_score: EditorialScoreResponse | None
    latest_human_score: EditorialScoreResponse | None
    effective_editorial: WorkbenchEffectiveEditorial | None
    human_override_applied: bool
    applied_override_count: int
    evidence_counts: WorkbenchEvidenceCounts
    evidence_total: int
    open_unknown_count: int
    card_count: int
    latest_card: EventCardResponse | None
    latest_card_id: UUID | None
    latest_pack: EditorialPackResponse | None
    draft_count: int
    latest_draft_id: UUID | None
    current_editorial_decision: EditorialDecisionResponse | None = None
    latest_candidate: CandidateSnapshotResponse | None = None
    latest_candidate_run: CandidateRunResponse | None = None


class WorkbenchEventPageResponse(BaseModel):
    items: list[WorkbenchEventItem]
    page: int
    page_size: int
    total: int
    has_next: bool


class WorkbenchSignalSummary(BaseModel):
    total: int
    by_relation: dict[str, int]


class WorkbenchDraftSummary(BaseModel):
    draft_count: int
    chain_count: int
    latest_draft_id: UUID | None


class WorkbenchEventDetailResponse(WorkbenchEventItem):
    signal_summary: WorkbenchSignalSummary
    draft_summary: WorkbenchDraftSummary


class WorkbenchSignalItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_signal_id: UUID
    signal_id: UUID
    relation: EventSignalRelation
    confidence: float
    attached_by: EventSignalAttachedBy
    platform: str
    source_id: UUID
    source_name: str
    source_type: str
    author_name: str | None
    published_at: datetime | None
    collected_at: datetime
    effective_at: datetime
    title: str | None
    original_url: str
    canonical_url: str


class WorkbenchSignalPageResponse(BaseModel):
    items: list[WorkbenchSignalItem]
    page: int
    page_size: int
    total: int
    has_next: bool


class WorkbenchArtifactCounts(BaseModel):
    trend_snapshots: int
    editorial_scores: int
    event_cards: int
    editorial_packs: int
    drafts: int


class WorkbenchCollectionHealth(BaseModel):
    failed_runs_24h: int
    paused_risk_runs_24h: int
    open_risk_events: int
    paused_accounts: int
    checkpoint_count: int


class WorkbenchCandidateWorkflow(BaseModel):
    business_date: date
    timezone: str
    run_exists: bool
    latest_run: CandidateRunResponse | None
    current_decision_counts: dict[str, int]


class WorkbenchOverviewResponse(BaseModel):
    generated_at: datetime
    active_event_count: int
    lifecycle_counts: dict[str, int]
    recent_new_event_count_24h: int
    recent_updated_event_count_24h: int
    events_with_evidence_count: int
    open_unknown_count: int
    high_risk_event_count: int
    artifact_counts: WorkbenchArtifactCounts
    collection_health: WorkbenchCollectionHealth
    candidate_workflow: WorkbenchCandidateWorkflow | None = None
    production_ai_provider_validation: str = Field(pattern="^NOT_TESTED$")
