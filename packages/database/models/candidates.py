from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.models.editorial import EditorialRecommendedFormat, EditorialRiskLevel
from packages.database.models.events import EventStatus
from packages.database.types import UTCDateTime, string_enum


class CandidateRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CandidateRunMode(StrEnum):
    APPLY = "apply"


class CandidateGroup(StrEnum):
    NORMAL = "normal"
    REVIEW_REQUIRED = "review_required"


class EditorialDecisionType(StrEnum):
    ADOPT = "adopt"
    WATCH = "watch"
    DROP = "drop"
    ARCHIVE = "archive"


class DailyCandidateRunRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable persisted snapshot of one deterministic daily candidate ranking run."""

    __tablename__ = "daily_candidate_runs"
    __table_args__ = (
        CheckConstraint("window_end_at > window_start_at", name="candidate_run_window_valid"),
        CheckConstraint("requested_limit > 0", name="candidate_run_limit_positive"),
        CheckConstraint("scanned_event_count >= 0", name="candidate_run_scanned_nonnegative"),
        CheckConstraint("eligible_event_count >= 0", name="candidate_run_eligible_nonnegative"),
        CheckConstraint("candidate_count >= 0", name="candidate_run_candidate_nonnegative"),
        CheckConstraint("skipped_event_count >= 0", name="candidate_run_skipped_nonnegative"),
        CheckConstraint("char_length(btrim(timezone)) > 0", name="candidate_run_timezone_nonempty"),
        CheckConstraint("char_length(btrim(ranking_version)) > 0", name="candidate_run_ranking_nonempty"),
        CheckConstraint("char_length(input_hash) = 64", name="candidate_run_input_hash_sha256"),
        CheckConstraint("char_length(btrim(actor)) > 0", name="candidate_run_actor_nonempty"),
        Index(
            "ix_daily_candidate_runs_business_asof",
            "business_date",
            "timezone",
            "as_of_at",
        ),
        Index("ix_daily_candidate_runs_status_created", "status", "created_at"),
        Index(
            "uq_daily_candidate_runs_success_input",
            "input_hash",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
    )

    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    as_of_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CandidateRunStatus] = mapped_column(
        string_enum(CandidateRunStatus, name="candidate_run_status"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scanned_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skip_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    mode: Mapped[CandidateRunMode] = mapped_column(
        string_enum(CandidateRunMode, name="candidate_run_mode"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DailyCandidateRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable rank and editorial context snapshot within one DailyCandidateRun."""

    __tablename__ = "daily_candidates"
    __table_args__ = (
        CheckConstraint("rank > 0", name="daily_candidate_rank_positive"),
        CheckConstraint(
            "effective_traffic_total >= 0 AND effective_traffic_total <= 100",
            name="daily_candidate_traffic_range",
        ),
        CheckConstraint("open_unknown_count >= 0", name="daily_candidate_unknown_nonnegative"),
        CheckConstraint("source_count_snapshot >= 0", name="daily_candidate_source_nonnegative"),
        CheckConstraint("platform_count_snapshot >= 0", name="daily_candidate_platform_nonnegative"),
        CheckConstraint(
            "char_length(effective_assessment_hash) = 64",
            name="daily_candidate_assessment_hash_sha256",
        ),
        CheckConstraint(
            "char_length(candidate_context_hash) = 64",
            name="daily_candidate_context_hash_sha256",
        ),
        UniqueConstraint("run_id", "event_id", name="uq_daily_candidates_run_event"),
        UniqueConstraint("run_id", "rank", name="uq_daily_candidates_run_rank"),
        Index("ix_daily_candidates_event_created", "event_id", "created_at"),
        Index("ix_daily_candidates_run_group_rank", "run_id", "candidate_group", "rank"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("daily_candidate_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_group: Mapped[CandidateGroup] = mapped_column(
        string_enum(CandidateGroup, name="candidate_group"), nullable=False
    )
    event_title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    category_snapshot: Mapped[str | None] = mapped_column(String(100))
    event_status_snapshot: Mapped[EventStatus] = mapped_column(
        string_enum(EventStatus, name="candidate_event_status"), nullable=False
    )
    event_last_updated_at_snapshot: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    source_count_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_count_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    trend_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_trend_snapshots.id", ondelete="RESTRICT"), index=True
    )
    base_editorial_score_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_scores.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    effective_assessment_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_traffic_total: Mapped[float] = mapped_column(Float, nullable=False)
    effective_risk_level: Mapped[EditorialRiskLevel] = mapped_column(
        string_enum(EditorialRiskLevel, name="candidate_effective_risk_level"), nullable=False
    )
    recommended_format: Mapped[EditorialRecommendedFormat] = mapped_column(
        string_enum(EditorialRecommendedFormat, name="candidate_recommended_format"), nullable=False
    )
    open_unknown_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ranking_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    card_exists_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    draft_exists_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    candidate_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EditorialDecisionRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only human editorial decision, independent from Event lifecycle and candidate rank."""

    __tablename__ = "editorial_decisions"
    __table_args__ = (
        CheckConstraint("char_length(btrim(actor)) > 0", name="editorial_decision_actor_nonempty"),
        CheckConstraint("char_length(btrim(reason)) > 0", name="editorial_decision_reason_nonempty"),
        CheckConstraint(
            "candidate_context_hash IS NULL OR char_length(candidate_context_hash) = 64",
            name="editorial_decision_context_hash_sha256",
        ),
        CheckConstraint(
            "effective_traffic_total_snapshot IS NULL OR "
            "(effective_traffic_total_snapshot >= 0 AND effective_traffic_total_snapshot <= 100)",
            name="editorial_decision_traffic_range",
        ),
        Index("ix_editorial_decisions_event_created", "event_id", "created_at"),
        Index("ix_editorial_decisions_decision_created", "decision", "created_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_candidates.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[EditorialDecisionType] = mapped_column(
        string_enum(EditorialDecisionType, name="editorial_decision_type"), nullable=False
    )
    previous_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_decisions.id", ondelete="RESTRICT"), index=True
    )
    candidate_context_hash: Mapped[str | None] = mapped_column(String(64))
    risk_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_level_snapshot: Mapped[EditorialRiskLevel | None] = mapped_column(
        string_enum(EditorialRiskLevel, name="editorial_decision_risk_level")
    )
    effective_traffic_total_snapshot: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
