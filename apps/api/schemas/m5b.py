from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.database.models import (
    CandidateGroup,
    CandidateRunMode,
    CandidateRunStatus,
    EditorialDecisionType,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EventStatus,
)


class CandidateGenerationRequestBody(BaseModel):
    business_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    as_of_at: datetime | None = None
    lookback_hours: int = Field(default=24, ge=1, le=168)
    requested_limit: int = Field(default=20, ge=1, le=100)
    include_resolved: bool = False
    include_archived: bool = False


class CandidateApplyRequestBody(CandidateGenerationRequestBody):
    confirmation: bool = False


class CandidateRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    business_date: date
    timezone: str
    as_of_at: datetime
    window_start_at: datetime
    window_end_at: datetime
    ranking_version: str
    requested_limit: int
    status: CandidateRunStatus
    input_hash: str
    scanned_event_count: int
    eligible_event_count: int
    candidate_count: int
    skipped_event_count: int
    skip_summary: dict[str, Any]
    mode: CandidateRunMode
    actor: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class CandidateSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    run_id: UUID | None = None
    event_id: UUID
    rank: int
    candidate_group: CandidateGroup
    event_title_snapshot: str
    category_snapshot: str | None
    event_status_snapshot: EventStatus
    event_last_updated_at_snapshot: datetime
    source_count_snapshot: int
    platform_count_snapshot: int
    trend_snapshot_id: UUID | None
    base_editorial_score_id: UUID
    effective_assessment_hash: str
    effective_traffic_total: float
    effective_risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    open_unknown_count: int
    evidence_summary: dict[str, Any]
    ranking_components: dict[str, Any]
    card_exists_snapshot: bool
    draft_exists_snapshot: bool
    candidate_context_hash: str
    created_at: datetime | None = None


class CandidatePoolPreviewResponse(BaseModel):
    business_date: date
    timezone: str
    as_of_at: datetime
    window_start_at: datetime
    window_end_at: datetime
    ranking_version: str
    requested_limit: int
    input_hash: str
    scanned_event_count: int
    eligible_event_count: int
    candidate_count: int
    skipped_event_count: int
    skip_summary: dict[str, int]
    candidates: list[CandidateSnapshotResponse]


class CandidateApplyResponse(BaseModel):
    run: CandidateRunResponse
    candidates: list[CandidateSnapshotResponse]
    reused: bool


class EditorialDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    candidate_id: UUID | None
    decision: EditorialDecisionType
    previous_decision_id: UUID | None
    candidate_context_hash: str | None
    risk_acknowledged: bool
    risk_level_snapshot: EditorialRiskLevel | None
    effective_traffic_total_snapshot: float | None
    reason: str
    actor: str
    created_at: datetime


class CandidateListItemResponse(BaseModel):
    candidate: CandidateSnapshotResponse
    current_event_status: EventStatus | None
    merged_into_event_id: UUID | None
    current_editorial_decision: EditorialDecisionResponse | None
    stale_indicator: bool | None


class CandidateListResponse(BaseModel):
    run: CandidateRunResponse
    items: list[CandidateListItemResponse]
    total: int
    top_n: int


class EditorialDecisionRequestBody(BaseModel):
    candidate_id: UUID | None = None
    decision: EditorialDecisionType
    expected_previous_decision_id: UUID | None = None
    risk_acknowledged: bool = False
    reason: str = Field(min_length=1, max_length=5000)
    confirmation: bool = False


class EditorialDecisionApplyResponse(BaseModel):
    decision: EditorialDecisionResponse
    reused: bool


class EditorialDecisionHistoryItemResponse(BaseModel):
    decision: EditorialDecisionResponse
    candidate_rank: int | None
    candidate_run_id: UUID | None
    candidate_business_date: date | None
    candidate_as_of_at: datetime | None


class EventWorkflowSummaryResponse(BaseModel):
    current_editorial_decision: EditorialDecisionResponse | None
    latest_candidate: CandidateSnapshotResponse | None
    latest_candidate_run: CandidateRunResponse | None
