from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.types import UTCDateTime, string_enum


class EditorialScoreSourceType(StrEnum):
    AI = "ai"
    HUMAN = "human"


class EditorialScoringMode(StrEnum):
    PREVIEW = "preview"
    APPLY = "apply"


class EditorialScoringStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EditorialRiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class EditorialRecommendedFormat(StrEnum):
    DAILY_COMPILATION = "daily_compilation"
    QUICK_EXPLAINER = "quick_explainer"
    FACT_CHECK = "fact_check"
    DEEP_DIVE = "deep_dive"
    ENTERTAINMENT = "entertainment"
    CONSUMER_SAFETY = "consumer_safety"


class EventTrendSnapshotRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable deterministic trend artifact for one Event/window/input."""

    __tablename__ = "event_trend_snapshots"
    __table_args__ = (
        CheckConstraint("window_end_at > window_start_at", name="trend_window_valid"),
        CheckConstraint("signal_count >= 0", name="trend_signal_count_nonnegative"),
        CheckConstraint("new_signal_count >= 0", name="trend_new_signal_count_nonnegative"),
        CheckConstraint("source_count >= 0", name="trend_source_count_nonnegative"),
        CheckConstraint("platform_count >= 0", name="trend_platform_count_nonnegative"),
        CheckConstraint(
            "signal_velocity IS NULL OR signal_velocity >= 0",
            name="trend_signal_velocity_nonnegative",
        ),
        CheckConstraint(
            "interaction_velocity IS NULL OR interaction_velocity >= 0",
            name="trend_interaction_velocity_nonnegative",
        ),
        CheckConstraint(
            "semantic_novelty IS NULL OR "
            "(semantic_novelty >= 0 AND semantic_novelty <= 1)",
            name="trend_semantic_novelty_range",
        ),
        CheckConstraint(
            "cn_gap IS NULL OR (cn_gap >= -1 AND cn_gap <= 1)",
            name="trend_cn_gap_range",
        ),
        CheckConstraint(
            "update_value IS NULL OR (update_value >= 0 AND update_value <= 100)",
            name="trend_update_value_range",
        ),
        CheckConstraint("char_length(input_hash) = 64", name="trend_input_hash_sha256"),
        Index(
            "uq_event_trend_snapshots_idempotency",
            "event_id",
            "calculation_version",
            "window_start_at",
            "window_end_at",
            "input_hash",
            unique=True,
        ),
        Index("ix_event_trend_snapshots_event_created", "event_id", "created_at"),
        Index("ix_event_trend_snapshots_event_window", "event_id", "window_end_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    calculation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    window_start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    new_signal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_velocity: Mapped[float | None] = mapped_column(Float)
    interaction_velocity: Mapped[float | None] = mapped_column(Float)
    cross_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cross_platform: Mapped[bool] = mapped_column(Boolean, nullable=False)
    semantic_novelty: Mapped[float | None] = mapped_column(Float)
    cn_gap: Mapped[float | None] = mapped_column(Float)
    update_value: Mapped[float | None] = mapped_column(Float)
    feature_availability: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    component_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EditorialScoringRunRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Business execution record linking scoring input to an AI Invocation."""

    __tablename__ = "editorial_scoring_runs"
    __table_args__ = (
        CheckConstraint(
            "char_length(input_hash) = 64",
            name="editorial_scoring_run_input_hash_sha256",
        ),
        Index("ix_editorial_scoring_runs_event_created", "event_id", "created_at"),
        Index("ix_editorial_scoring_runs_invocation", "ai_invocation_id"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trend_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_trend_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    score_template: Mapped[str] = mapped_column(String(100), nullable=False)
    score_template_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[EditorialScoringMode] = mapped_column(
        string_enum(EditorialScoringMode, name="editorial_scoring_mode"),
        nullable=False,
    )
    status: Mapped[EditorialScoringStatus] = mapped_column(
        string_enum(EditorialScoringStatus, name="editorial_scoring_status"),
        nullable=False,
        default=EditorialScoringStatus.RUNNING,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EditorialScoreRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable seven-dimension editorial assessment artifact."""

    __tablename__ = "editorial_scores"
    __table_args__ = (
        CheckConstraint(
            "emotion >= 0 AND emotion <= 100", name="editorial_score_emotion_range"
        ),
        CheckConstraint(
            "information_gap >= 0 AND information_gap <= 100",
            name="editorial_score_information_gap_range",
        ),
        CheckConstraint(
            "visual_value >= 0 AND visual_value <= 100",
            name="editorial_score_visual_value_range",
        ),
        CheckConstraint(
            "user_relevance >= 0 AND user_relevance <= 100",
            name="editorial_score_user_relevance_range",
        ),
        CheckConstraint(
            "discussion >= 0 AND discussion <= 100",
            name="editorial_score_discussion_range",
        ),
        CheckConstraint(
            "novelty >= 0 AND novelty <= 100",
            name="editorial_score_novelty_range",
        ),
        CheckConstraint(
            "extendability >= 0 AND extendability <= 100",
            name="editorial_score_extendability_range",
        ),
        CheckConstraint(
            "traffic_total >= 0 AND traffic_total <= 100",
            name="editorial_score_traffic_total_range",
        ),
        CheckConstraint(
            "char_length(input_hash) = 64", name="editorial_score_input_hash_sha256"
        ),
        CheckConstraint(
            "(source_type = 'ai' AND ai_invocation_id IS NOT NULL "
            "AND scoring_run_id IS NOT NULL) OR "
            "(source_type = 'human' AND ai_invocation_id IS NULL "
            "AND scoring_run_id IS NULL AND source_reason IS NOT NULL "
            "AND char_length(btrim(source_reason)) > 0)",
            name="editorial_score_source_provenance",
        ),
        Index("ix_editorial_scores_event_created", "event_id", "created_at"),
        Index("ix_editorial_scores_trend_snapshot", "trend_snapshot_id"),
        Index("ix_editorial_scores_ai_invocation", "ai_invocation_id"),
        Index(
            "uq_editorial_scores_ai_idempotency",
            "event_id",
            "score_template",
            "score_template_version",
            "scoring_version",
            "input_hash",
            unique=True,
            postgresql_where=text("source_type = 'ai'"),
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trend_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_trend_snapshots.id", ondelete="RESTRICT"), index=True
    )
    score_template: Mapped[str] = mapped_column(String(100), nullable=False)
    score_template_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[EditorialScoreSourceType] = mapped_column(
        string_enum(EditorialScoreSourceType, name="editorial_score_source_type"),
        nullable=False,
    )
    emotion: Mapped[int] = mapped_column(Integer, nullable=False)
    information_gap: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_value: Mapped[int] = mapped_column(Integer, nullable=False)
    user_relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    discussion: Mapped[int] = mapped_column(Integer, nullable=False)
    novelty: Mapped[int] = mapped_column(Integer, nullable=False)
    extendability: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_total: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[EditorialRiskLevel] = mapped_column(
        string_enum(EditorialRiskLevel, name="editorial_risk_level"), nullable=False
    )
    recommended_format: Mapped[EditorialRecommendedFormat] = mapped_column(
        string_enum(
            EditorialRecommendedFormat,
            name="editorial_recommended_format",
        ),
        nullable=False,
    )
    model_reason: Mapped[str | None] = mapped_column(Text)
    ai_invocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"), index=True
    )
    scoring_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_scoring_runs.id", ondelete="RESTRICT"), unique=True
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    source_reason: Mapped[str | None] = mapped_column(Text)


class EditorialScoreOverrideRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only human patch that remains visible across later AI reruns."""

    __tablename__ = "editorial_score_overrides"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(actor)) > 0",
            name="editorial_score_override_actor_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(reason)) > 0",
            name="editorial_score_override_reason_nonempty",
        ),
        Index(
            "ix_editorial_score_overrides_score_created",
            "editorial_score_id",
            "created_at",
        ),
    )

    editorial_score_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_scores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    overridden_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
