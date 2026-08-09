from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.models.editorial import EditorialRecommendedFormat, EditorialRiskLevel
from packages.database.types import UTCDateTime, string_enum


class DraftType(StrEnum):
    SHORT_30S = "short_30s"
    STANDARD_90S = "standard_90s"
    DEEP_180S = "deep_180s"


class DraftSourceType(StrEnum):
    AI = "ai"
    HUMAN = "human"


class DraftStatus(StrEnum):
    GENERATED = "generated"
    EDITED = "edited"
    REVIEWED = "reviewed"
    ARCHIVED = "archived"


class DraftGenerationMode(StrEnum):
    PREVIEW = "preview"
    APPLY = "apply"


class DraftGenerationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DraftCitationUsage(StrEnum):
    FACT = "fact"
    ATTRIBUTED = "attributed"
    DISPUTED = "disputed"
    DEBUNKED = "debunked"


class EventCardRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable deterministic Event Card bound to exact evidence/editorial context."""

    __tablename__ = "event_cards"
    __table_args__ = (
        CheckConstraint(
            "char_length(evidence_snapshot_hash) = 64",
            name="event_card_evidence_hash_sha256",
        ),
        CheckConstraint("char_length(input_hash) = 64", name="event_card_input_hash_sha256"),
        Index(
            "uq_event_cards_idempotency",
            "event_id",
            "card_version",
            "input_hash",
            unique=True,
        ),
        Index("ix_event_cards_event_created", "event_id", "created_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    card_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trend_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_trend_snapshots.id", ondelete="RESTRICT"), index=True
    )
    editorial_score_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_scores.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    concise_summary: Mapped[str] = mapped_column(Text, nullable=False)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    confirmed_claim_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    investigating_claim_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    single_source_claim_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    disputed_claim_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    false_claim_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    unknown_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    effective_assessment: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    risk_level: Mapped[EditorialRiskLevel] = mapped_column(
        string_enum(EditorialRiskLevel, name="event_card_risk_level"), nullable=False
    )
    recommended_format: Mapped[EditorialRecommendedFormat] = mapped_column(
        string_enum(
            EditorialRecommendedFormat,
            name="event_card_recommended_format",
        ),
        nullable=False,
    )
    generated_by: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deterministic",
        server_default=text("'deterministic'"),
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EditorialPackRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable editor-facing material manifest derived from an Event Card."""

    __tablename__ = "editorial_packs"
    __table_args__ = (
        CheckConstraint("char_length(input_hash) = 64", name="editorial_pack_input_hash_sha256"),
        Index(
            "uq_editorial_packs_idempotency",
            "event_id",
            "event_card_id",
            "pack_version",
            "input_hash",
            unique=True,
        ),
        Index("ix_editorial_packs_event_created", "event_id", "created_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pack_version: Mapped[str] = mapped_column(String(100), nullable=False)
    recommended_format: Mapped[EditorialRecommendedFormat] = mapped_column(
        string_enum(
            EditorialRecommendedFormat,
            name="editorial_pack_recommended_format",
        ),
        nullable=False,
    )
    suggested_angles: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    source_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    timeline_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    material_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    unknown_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    claim_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )


class DraftGenerationRunRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Business execution linking draft input to one governed AI Invocation."""

    __tablename__ = "draft_generation_runs"
    __table_args__ = (
        CheckConstraint(
            "char_length(input_hash) = 64",
            name="draft_generation_run_input_hash_sha256",
        ),
        Index("ix_draft_generation_runs_event_created", "event_id", "created_at"),
        Index("ix_draft_generation_runs_invocation", "ai_invocation_id"),
        Index(
            "uq_draft_generation_runs_apply_input",
            "event_id",
            "event_card_id",
            "editorial_pack_id",
            "draft_type",
            "prompt_version",
            "schema_version",
            "input_hash",
            unique=True,
            postgresql_where=text("mode = 'apply'"),
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    editorial_pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_packs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    draft_type: Mapped[DraftType] = mapped_column(
        string_enum(DraftType, name="draft_generation_draft_type"), nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[DraftGenerationMode] = mapped_column(
        string_enum(DraftGenerationMode, name="draft_generation_mode"), nullable=False
    )
    status: Mapped[DraftGenerationStatus] = mapped_column(
        string_enum(DraftGenerationStatus, name="draft_generation_status"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EditorialDraftRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only draft/revision artifact. Human editing never overwrites AI originals."""

    __tablename__ = "editorial_drafts"
    __table_args__ = (
        CheckConstraint("draft_version > 0", name="editorial_draft_version_positive"),
        CheckConstraint(
            "duration_target_seconds IN (30,90,180)",
            name="editorial_draft_duration_allowed",
        ),
        CheckConstraint("char_length(btrim(body)) > 0", name="editorial_draft_body_nonempty"),
        CheckConstraint(
            "char_length(input_hash) = 64",
            name="editorial_draft_input_hash_sha256",
        ),
        CheckConstraint(
            "(source_type = 'ai' AND ai_invocation_id IS NOT NULL "
            "AND generation_run_id IS NOT NULL AND prompt_version IS NOT NULL "
            "AND schema_version IS NOT NULL) OR "
            "(source_type = 'human' AND ai_invocation_id IS NULL "
            "AND generation_run_id IS NULL AND created_by_actor IS NOT NULL "
            "AND char_length(btrim(created_by_actor)) > 0 AND change_note IS NOT NULL "
            "AND char_length(btrim(change_note)) > 0)",
            name="editorial_draft_source_provenance",
        ),
        Index(
            "uq_editorial_drafts_chain_version",
            "draft_chain_id",
            "draft_version",
            unique=True,
        ),
        Index(
            "uq_editorial_drafts_ai_input",
            "event_card_id",
            "editorial_pack_id",
            "draft_type",
            "prompt_version",
            "schema_version",
            "input_hash",
            unique=True,
            postgresql_where=text("source_type = 'ai'"),
        ),
        Index("ix_editorial_drafts_event_created", "event_id", "created_at"),
        Index("ix_editorial_drafts_chain", "draft_chain_id", "draft_version"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    editorial_pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_packs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    draft_chain_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    draft_type: Mapped[DraftType] = mapped_column(
        string_enum(DraftType, name="editorial_draft_type"), nullable=False
    )
    format_key: Mapped[EditorialRecommendedFormat] = mapped_column(
        string_enum(
            EditorialRecommendedFormat,
            name="editorial_draft_format",
        ),
        nullable=False,
    )
    duration_target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="zh-CN")
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_drafts.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[DraftSourceType] = mapped_column(
        string_enum(DraftSourceType, name="editorial_draft_source_type"), nullable=False
    )
    status: Mapped[DraftStatus] = mapped_column(
        string_enum(DraftStatus, name="editorial_draft_status"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(500))
    title_candidates: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    hook: Mapped[str | None] = mapped_column(Text)
    hook_candidates: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    cover_text_candidates: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    ending: Mapped[str | None] = mapped_column(Text)
    interaction_question: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    schema_version: Mapped[str | None] = mapped_column(String(100))
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    generation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("draft_generation_runs.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str | None] = mapped_column(String(255))
    change_note: Mapped[str | None] = mapped_column(Text)


class DraftClaimReferenceRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Formal section-level Draft -> Claim citation. Signal provenance remains on Claim."""

    __tablename__ = "draft_claim_references"
    __table_args__ = (
        Index(
            "uq_draft_claim_references_section_claim",
            "draft_id",
            "claim_id",
            "section_key",
            unique=True,
        ),
        Index("ix_draft_claim_references_claim", "claim_id"),
    )

    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_drafts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    usage: Mapped[DraftCitationUsage] = mapped_column(
        string_enum(DraftCitationUsage, name="draft_claim_reference_usage"), nullable=False
    )
