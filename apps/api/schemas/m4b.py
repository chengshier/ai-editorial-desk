from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.database.models import (
    EventUnknownSourceType,
    EventUnknownStatus,
    EvidenceClaimType,
    EvidenceCreatedByType,
    EvidenceExtractionRunMode,
    EvidenceExtractionRunStatus,
    EvidenceSourceRole,
    EvidenceVerificationState,
)


class EvidenceSourceAttach(BaseModel):
    signal_id: UUID
    role: EvidenceSourceRole


class HumanClaimCreate(BaseModel):
    claim_text: str = Field(min_length=1, max_length=5000)
    claim_type: EvidenceClaimType
    sources: list[EvidenceSourceAttach] = Field(min_length=1, max_length=100)
    editor_note: str | None = Field(default=None, max_length=5000)


class ClaimVerificationRequest(BaseModel):
    verification_state: EvidenceVerificationState
    reason: str = Field(min_length=1, max_length=5000)


class ClaimNoteUpdate(BaseModel):
    editor_note: str = Field(min_length=1, max_length=5000)


class EvidenceExtractionRequest(BaseModel):
    apply: bool = False
    signal_ids: list[UUID] | None = Field(default=None, max_length=100)
    max_signals: int = Field(default=30, ge=1, le=100)
    max_chars_per_signal: int = Field(default=4000, ge=1, le=20000)
    max_total_chars: int = Field(default=40000, ge=1, le=120000)


class EvidenceExtractionResponse(BaseModel):
    run_id: UUID
    ai_invocation_id: UUID | None
    mode: EvidenceExtractionRunMode
    status: EvidenceExtractionRunStatus
    claim_count: int
    unknown_count: int
    invalid_item_count: int
    invalid_codes: list[str]
    signal_count: int
    character_count: int
    truncated: bool
    truncated_signal_ids: list[UUID]


class EvidenceSourceResponse(BaseModel):
    signal_id: UUID
    role: EvidenceSourceRole
    title: str | None
    platform: str
    author_name: str | None
    published_at: datetime | None
    collected_at: datetime
    original_url: str
    canonical_url: str


class EvidenceClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    claim_text: str
    claim_type: EvidenceClaimType
    verification_state: EvidenceVerificationState
    extraction_confidence: float | None
    claim_fingerprint: str
    extraction_version: str
    extraction_run_id: UUID | None
    ai_invocation_id: UUID | None
    created_by_type: EvidenceCreatedByType
    created_by_actor: str | None
    editor_note: str | None
    created_at: datetime
    updated_at: datetime
    sources: list[EvidenceSourceResponse] = Field(default_factory=list)


class EventUnknownCreate(BaseModel):
    unknown_text: str = Field(min_length=1, max_length=5000)


class EventUnknownUpdate(BaseModel):
    status: EventUnknownStatus
    resolution_note: str | None = Field(default=None, max_length=5000)
    resolved_by_claim_id: UUID | None = None


class EventUnknownResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    unknown_text: str
    unknown_fingerprint: str
    status: EventUnknownStatus
    source_type: EventUnknownSourceType
    extraction_run_id: UUID | None
    ai_invocation_id: UUID | None
    resolved_by_claim_id: UUID | None
    resolution_note: str | None
    created_by_actor: str | None
    created_at: datetime
    updated_at: datetime


class EventEvidenceResponse(BaseModel):
    event_id: UUID
    claims: list[EvidenceClaimResponse]
    unknowns: list[EventUnknownResponse]
