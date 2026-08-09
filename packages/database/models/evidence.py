from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import UTCDateTime, string_enum


class EvidenceClaimType(StrEnum):
    FACT = "fact"
    ALLEGATION = "allegation"
    OPINION = "opinion"
    FORECAST = "forecast"


class EvidenceVerificationState(StrEnum):
    CONFIRMED = "confirmed"
    INVESTIGATING = "investigating"
    SINGLE_SOURCE = "single_source"
    DISPUTED = "disputed"
    FALSE = "false"


class EvidenceSourceRole(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"


class EvidenceCreatedByType(StrEnum):
    AI = "ai"
    HUMAN = "human"


class EvidenceExtractionRunMode(StrEnum):
    PREVIEW = "preview"
    APPLY = "apply"


class EvidenceExtractionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class EventUnknownStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EventUnknownSourceType(StrEnum):
    AI = "ai"
    HUMAN = "human"


class EvidenceExtractionRunRecord(UUIDPrimaryKeyMixin, Base):
    """Business-level evidence extraction execution linked to one AI Invocation."""

    __tablename__ = "evidence_extraction_runs"
    __table_args__ = (
        CheckConstraint("requested_signal_count >= 0", name="evidence_run_signal_count_nonnegative"),
        CheckConstraint("claim_count >= 0", name="evidence_run_claim_count_nonnegative"),
        CheckConstraint("unknown_count >= 0", name="evidence_run_unknown_count_nonnegative"),
        CheckConstraint("invalid_item_count >= 0", name="evidence_run_invalid_count_nonnegative"),
        CheckConstraint("character_count >= 0", name="evidence_run_character_count_nonnegative"),
        CheckConstraint("char_length(input_hash) = 64", name="evidence_run_input_hash_sha256"),
        Index("ix_evidence_extraction_runs_event_created", "event_id", "created_at"),
        Index("ix_evidence_extraction_runs_invocation", "ai_invocation_id"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    extraction_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[EvidenceExtractionRunMode] = mapped_column(
        string_enum(EvidenceExtractionRunMode, name="evidence_extraction_run_mode"), nullable=False
    )
    status: Mapped[EvidenceExtractionRunStatus] = mapped_column(
        string_enum(EvidenceExtractionRunStatus, name="evidence_extraction_run_status"), nullable=False
    )
    requested_signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    truncated: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("false"))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EvidenceClaimRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A traceable claim candidate; AI output is never automatically confirmed or false."""

    __tablename__ = "evidence_claims"
    __table_args__ = (
        UniqueConstraint("event_id", "claim_fingerprint", name="uq_evidence_claims_event_fingerprint"),
        CheckConstraint("char_length(btrim(claim_text)) > 0", name="evidence_claim_text_nonempty"),
        CheckConstraint("char_length(claim_fingerprint) = 64", name="evidence_claim_fingerprint_sha256"),
        CheckConstraint(
            "extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="evidence_claim_confidence_range",
        ),
        Index("ix_evidence_claims_event_state", "event_id", "verification_state"),
        Index("ix_evidence_claims_invocation", "ai_invocation_id"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[EvidenceClaimType] = mapped_column(
        string_enum(EvidenceClaimType, name="evidence_claim_type"), nullable=False
    )
    verification_state: Mapped[EvidenceVerificationState] = mapped_column(
        string_enum(EvidenceVerificationState, name="evidence_verification_state"), nullable=False
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    claim_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(100), nullable=False)
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    created_by_type: Mapped[EvidenceCreatedByType] = mapped_column(
        string_enum(EvidenceCreatedByType, name="evidence_created_by_type"), nullable=False
    )
    created_by_actor: Mapped[str | None] = mapped_column(String(255))
    editor_note: Mapped[str | None] = mapped_column(Text)


class EvidenceClaimSourceRecord(UUIDPrimaryKeyMixin, Base):
    """One explicit supporting or contradicting RawSignal link for a Claim."""

    __tablename__ = "evidence_claim_sources"
    __table_args__ = (
        UniqueConstraint("claim_id", "signal_id", name="uq_evidence_claim_sources_claim_signal"),
        Index("ix_evidence_claim_sources_signal", "signal_id"),
    )

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[EvidenceSourceRole] = mapped_column(
        string_enum(EvidenceSourceRole, name="evidence_source_role"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class EventUnknownRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """First-class unresolved question about an Event, separate from factual claims."""

    __tablename__ = "event_unknowns"
    __table_args__ = (
        UniqueConstraint("event_id", "unknown_fingerprint", name="uq_event_unknowns_event_fingerprint"),
        CheckConstraint("char_length(btrim(unknown_text)) > 0", name="event_unknown_text_nonempty"),
        CheckConstraint("char_length(unknown_fingerprint) = 64", name="event_unknown_fingerprint_sha256"),
        Index("ix_event_unknowns_event_status", "event_id", "status"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unknown_text: Mapped[str] = mapped_column(Text, nullable=False)
    unknown_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[EventUnknownStatus] = mapped_column(
        string_enum(EventUnknownStatus, name="event_unknown_status"), nullable=False
    )
    source_type: Mapped[EventUnknownSourceType] = mapped_column(
        string_enum(EventUnknownSourceType, name="event_unknown_source_type"), nullable=False
    )
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    resolved_by_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_by_actor: Mapped[str | None] = mapped_column(String(255))
