from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.database.models import (
    DraftCitationUsage,
    DraftGenerationMode,
    DraftGenerationStatus,
    DraftSourceType,
    DraftStatus,
    DraftType,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
)


class EventCardCreateRequest(BaseModel):
    trend_snapshot_id: UUID | None = None


class EventCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    card_version: str
    evidence_snapshot_hash: str
    trend_snapshot_id: UUID | None
    editorial_score_id: UUID
    title: str
    concise_summary: str
    timeline: list[dict[str, Any]]
    confirmed_claim_ids: list[str]
    investigating_claim_ids: list[str]
    single_source_claim_ids: list[str]
    disputed_claim_ids: list[str]
    false_claim_ids: list[str]
    unknown_ids: list[str]
    source_summary: dict[str, Any]
    effective_assessment: dict[str, Any]
    risk_level: EditorialRiskLevel
    recommended_format: EditorialRecommendedFormat
    generated_by: str
    ai_invocation_id: UUID | None
    input_hash: str
    created_at: datetime


class EventCardCreateResponse(BaseModel):
    card: EventCardResponse
    created: bool


class EditorialPackCreateRequest(BaseModel):
    event_card_id: UUID


class EditorialPackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_card_id: UUID
    pack_version: str
    recommended_format: EditorialRecommendedFormat
    suggested_angles: list[dict[str, Any]]
    source_items: list[dict[str, Any]]
    timeline_items: list[dict[str, Any]]
    material_items: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    unknown_items: list[dict[str, Any]]
    claim_references: list[dict[str, Any]]
    input_hash: str
    ai_invocation_id: UUID | None
    created_at: datetime


class EditorialPackCreateResponse(BaseModel):
    pack: EditorialPackResponse
    created: bool


class DraftGenerateRequest(BaseModel):
    event_card_id: UUID
    editorial_pack_id: UUID
    draft_type: DraftType
    risk_approval_reason: str | None = Field(default=None, max_length=2000)


class DraftReferenceRequest(BaseModel):
    claim_id: UUID
    section_key: str = Field(min_length=1, max_length=100)
    usage: DraftCitationUsage


class DraftReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    draft_id: UUID
    claim_id: UUID
    section_key: str
    usage: DraftCitationUsage
    created_at: datetime


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_card_id: UUID
    editorial_pack_id: UUID
    draft_chain_id: UUID
    draft_type: DraftType
    format_key: EditorialRecommendedFormat
    duration_target_seconds: int
    language: str
    draft_version: int
    parent_draft_id: UUID | None
    source_type: DraftSourceType
    status: DraftStatus
    title: str | None
    title_candidates: list[str]
    hook: str | None
    hook_candidates: list[str]
    cover_text_candidates: list[str]
    sections: list[dict[str, Any]]
    body: str
    ending: str | None
    interaction_question: str | None
    prompt_version: str | None
    schema_version: str | None
    ai_invocation_id: UUID | None
    generation_run_id: UUID | None
    input_hash: str
    created_by_actor: str | None
    change_note: str | None
    created_at: datetime


class DraftDetailResponse(BaseModel):
    draft: DraftResponse
    claim_references: list[DraftReferenceResponse]
    version_chain: list[DraftResponse]


class DraftPreviewCandidateResponse(BaseModel):
    draft_type: DraftType
    format_key: EditorialRecommendedFormat
    title_candidates: list[str]
    hook_candidates: list[str]
    cover_text_candidates: list[str]
    sections: list[dict[str, Any]]
    ending: str | None
    interaction_question: str | None


class DraftGenerationResponse(BaseModel):
    run_id: UUID | None
    ai_invocation_id: UUID | None
    mode: DraftGenerationMode
    status: DraftGenerationStatus
    draft: DraftResponse | None
    candidate: DraftPreviewCandidateResponse | None
    reused: bool


class HumanDraftRequest(BaseModel):
    event_card_id: UUID
    editorial_pack_id: UUID
    draft_type: DraftType
    reason: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=10000)
    references: list[DraftReferenceRequest] = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=500)
    hook: str | None = Field(default=None, max_length=2000)
    ending: str | None = Field(default=None, max_length=2000)
    interaction_question: str | None = Field(default=None, max_length=1000)


class DraftRevisionRequest(BaseModel):
    change_note: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=10000)
    references: list[DraftReferenceRequest] = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=500)
    hook: str | None = Field(default=None, max_length=2000)
    ending: str | None = Field(default=None, max_length=2000)
    interaction_question: str | None = Field(default=None, max_length=1000)
