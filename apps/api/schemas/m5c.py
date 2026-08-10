from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.database.models import (
    DraftSourceType,
    EditorialDecisionType,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
)
from packages.database.models.publication import (
    PerformanceHorizon,
    PerformanceImportStatus,
    PerformanceSourceType,
    PublicationMode,
)


class PublicationCreateRequest(BaseModel):
    event_id: UUID
    draft_id: UUID | None = None
    publication_mode: PublicationMode = PublicationMode.WORKFLOW
    platform_key: str = Field(min_length=1, max_length=100)
    account_label: str | None = Field(default=None, max_length=255)
    external_post_id: str | None = Field(default=None, max_length=255)
    public_url: str = Field(min_length=1, max_length=2048)
    published_at: datetime
    title_snapshot: str | None = Field(default=None, max_length=500)
    cover_text_snapshot: str | None = Field(default=None, max_length=5000)
    body_snapshot: str | None = Field(default=None, max_length=200000)
    backfill_reason: str | None = Field(default=None, max_length=5000)


class PublicationCorrectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)
    account_label: str | None = Field(default=None, max_length=255)
    external_post_id: str | None = Field(default=None, max_length=255)
    public_url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None
    title_snapshot: str | None = Field(default=None, max_length=500)
    cover_text_snapshot: str | None = Field(default=None, max_length=5000)
    body_snapshot: str | None = Field(default=None, max_length=200000)


class PublicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    draft_id: UUID | None
    publication_mode: PublicationMode
    platform_key: str
    account_label: str | None
    external_post_id: str | None
    public_url: str
    published_at: datetime
    title_snapshot: str | None
    cover_text_snapshot: str | None
    body_snapshot: str | None
    publication_content_hash: str | None
    candidate_run_id: UUID | None
    candidate_id: UUID | None
    candidate_rank_snapshot: int | None
    editorial_decision_id: UUID | None
    editorial_decision_snapshot: EditorialDecisionType | None
    base_editorial_score_id: UUID | None
    editorial_score_snapshot: dict[str, Any] | None
    effective_traffic_total_snapshot: float | None
    risk_snapshot: EditorialRiskLevel | None
    recommended_format_snapshot: EditorialRecommendedFormat | None
    draft_chain_id: UUID | None
    draft_version_snapshot: int | None
    draft_source_type_snapshot: DraftSourceType | None
    draft_format_snapshot: EditorialRecommendedFormat | None
    draft_duration_seconds_snapshot: int | None
    actor: str
    backfill_reason: str | None
    record_version: str
    created_at: datetime
    updated_at: datetime


class PublicationCreateResponse(BaseModel):
    publication: PublicationResponse
    reused: bool


class PerformanceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    publication_id: UUID
    observed_at: datetime
    horizon: PerformanceHorizon
    source: PerformanceSourceType
    views: int | None
    completion_rate: float | None
    average_watch_seconds: float | None
    likes: int | None
    comments: int | None
    shares: int | None
    favorites: int | None
    follower_delta: int | None
    snapshot_hash: str
    supersedes_snapshot_id: UUID | None
    correction_reason: str | None
    actor: str
    import_run_id: UUID | None
    snapshot_version: str
    created_at: datetime


class LatestPerformanceResponse(BaseModel):
    snapshot: PerformanceSnapshotResponse
    engagement_rate: float | None
    engagement_rate_unavailable_reason: str | None


class PublicationListItemResponse(BaseModel):
    publication: PublicationResponse
    event_title: str
    latest_performance: LatestPerformanceResponse | None


class PublicationListResponse(BaseModel):
    items: list[PublicationListItemResponse]
    total: int
    page: int
    page_size: int


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    actor: str
    before_data: dict[str, Any]
    after_data: dict[str, Any]
    created_at: datetime


class PublicationDetailResponse(PublicationListItemResponse):
    audit_entries: list[AuditEntryResponse]


class ManualPerformanceRequest(BaseModel):
    observed_at: datetime
    horizon: PerformanceHorizon = PerformanceHorizon.CUSTOM
    views: int | None = Field(default=None, ge=0)
    completion_rate_percent: float | None = Field(default=None, ge=0, le=100)
    average_watch_seconds: float | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    follower_delta: int | None = None
    supersedes_snapshot_id: UUID | None = None
    correction_reason: str | None = Field(default=None, max_length=5000)


class PerformanceSnapshotCreateResponse(BaseModel):
    snapshot: PerformanceSnapshotResponse
    reused: bool


class PerformanceTimelineItemResponse(BaseModel):
    snapshot: PerformanceSnapshotResponse
    is_effective: bool
    engagement_rate: float | None
    engagement_rate_unavailable_reason: str | None
    deltas: dict[str, int | float | None]


class PerformanceImportPreviewRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=2_100_000)


class PerformanceImportApplyRequest(PerformanceImportPreviewRequest):
    file_name: str | None = Field(default=None, max_length=500)
    confirmation: bool = False


class PerformanceImportErrorResponse(BaseModel):
    row_number: int
    field: str
    code: str
    message: str


class PerformanceImportPreviewResponse(BaseModel):
    mapping_version: str
    file_sha256: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    normalized_rows: list[dict[str, Any]]
    errors: list[PerformanceImportErrorResponse]


class PerformanceImportRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: PerformanceSourceType
    mapping_version: str
    file_name: str | None
    file_sha256: str
    status: PerformanceImportStatus
    row_count: int
    valid_count: int
    inserted_count: int
    duplicate_count: int
    error_count: int
    error_summary: list[dict[str, Any]]
    actor: str
    created_at: datetime
    finished_at: datetime | None


class PerformanceImportApplyResponse(BaseModel):
    run: PerformanceImportRunResponse
    reused: bool


class PerformanceOverviewResponse(BaseModel):
    candidate_count: int
    candidate_run_id: str | None
    adopted_count: int
    published_count: int
    with_performance_count: int
    latest_observed_at: datetime | None
    platform_counts: dict[str, int]
    note: str
