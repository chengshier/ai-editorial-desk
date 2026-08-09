from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.database.models import (
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EditorialScoreSourceType,
    EditorialScoringMode,
    EditorialScoringStatus,
)


class TrendCalculateRequest(BaseModel):
    window_start_at: datetime
    window_end_at: datetime


class TrendSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    calculation_version: str
    window_start_at: datetime
    window_end_at: datetime
    signal_count: int
    new_signal_count: int
    source_count: int
    platform_count: int
    signal_velocity: float | None
    interaction_velocity: float | None
    cross_source: bool
    cross_platform: bool
    semantic_novelty: float | None
    cn_gap: float | None
    update_value: float | None
    feature_availability: dict[str, Any]
    component_metrics: dict[str, Any]
    input_hash: str
    created_at: datetime


class TrendCalculateResponse(BaseModel):
    snapshot: TrendSnapshotResponse
    created: bool


class EditorialScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    trend_snapshot_id: UUID | None
    score_template: str
    score_template_version: str
    scoring_version: str
    source_type: EditorialScoreSourceType
    emotion: int
    information_gap: int
    visual_value: int
    user_relevance: int
    discussion: int
    novelty: int
    extendability: int
    traffic_total: float
    risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    model_reason: str | None
    ai_invocation_id: UUID | None
    scoring_run_id: UUID | None
    input_hash: str
    created_by_actor: str
    source_reason: str | None
    created_at: datetime


class EditorialScoreRequest(BaseModel):
    trend_snapshot_id: UUID


class EditorialScoreRunResponse(BaseModel):
    run_id: UUID | None
    ai_invocation_id: UUID | None
    mode: EditorialScoringMode
    status: EditorialScoringStatus
    score: EditorialScoreResponse | None
    emotion: int
    information_gap: int
    visual_value: int
    user_relevance: int
    discussion: int
    novelty: int
    extendability: int
    traffic_total: float
    risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    model_reason: str
    reused: bool


class ManualEditorialScoreRequest(BaseModel):
    trend_snapshot_id: UUID | None = None
    emotion: int = Field(ge=0, le=100)
    information_gap: int = Field(ge=0, le=100)
    visual_value: int = Field(ge=0, le=100)
    user_relevance: int = Field(ge=0, le=100)
    discussion: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    extendability: int = Field(ge=0, le=100)
    risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    reason: str = Field(min_length=1, max_length=5000)
    model_reason: str | None = Field(default=None, max_length=2000)


class EditorialOverrideRequest(BaseModel):
    emotion: int | None = Field(default=None, ge=0, le=100)
    information_gap: int | None = Field(default=None, ge=0, le=100)
    visual_value: int | None = Field(default=None, ge=0, le=100)
    user_relevance: int | None = Field(default=None, ge=0, le=100)
    discussion: int | None = Field(default=None, ge=0, le=100)
    novelty: int | None = Field(default=None, ge=0, le=100)
    extendability: int | None = Field(default=None, ge=0, le=100)
    risk_level: EditorialRiskLevel | None = None
    recommended_format: EditorialRecommendedFormat | None = None
    reason: str = Field(min_length=1, max_length=5000)


class EditorialOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    editorial_score_id: UUID
    overridden_fields: dict[str, Any]
    reason: str
    actor: str
    created_at: datetime


class EffectiveEditorialResponse(BaseModel):
    event_id: UUID
    latest_ai_score: EditorialScoreResponse | None
    latest_human_score: EditorialScoreResponse | None
    effective_base_score_id: UUID | None
    effective_values: dict[str, Any] | None
    applied_overrides: list[EditorialOverrideResponse]
