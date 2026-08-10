from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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

from packages.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.models.candidates import EditorialDecisionType
from packages.database.models.drafts import DraftSourceType
from packages.database.models.editorial import EditorialRecommendedFormat, EditorialRiskLevel
from packages.database.types import UTCDateTime, string_enum


class PublicationMode(StrEnum):
    WORKFLOW = "workflow"
    MANUAL_BACKFILL = "manual_backfill"


class PerformanceHorizon(StrEnum):
    H1 = "h1"
    H24 = "h24"
    D7 = "d7"
    CUSTOM = "custom"


class PerformanceSourceType(StrEnum):
    MANUAL = "manual"
    CSV = "csv"


class PerformanceImportStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PublicationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real platform publication with frozen editorial provenance."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(platform_key)) > 0",
            name="publication_platform_key_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(actor)) > 0",
            name="publication_actor_nonempty",
        ),
        CheckConstraint(
            "public_url LIKE 'http://%' OR public_url LIKE 'https://%'",
            name="publication_public_url_http",
        ),
        CheckConstraint(
            "publication_mode != 'workflow' OR "
            "(draft_id IS NOT NULL AND editorial_decision_id IS NOT NULL)",
            name="publication_workflow_provenance",
        ),
        CheckConstraint(
            "publication_mode != 'manual_backfill' OR "
            "(backfill_reason IS NOT NULL AND char_length(btrim(backfill_reason)) > 0)",
            name="publication_backfill_reason",
        ),
        CheckConstraint(
            "candidate_rank_snapshot IS NULL OR candidate_rank_snapshot > 0",
            name="publication_candidate_rank_positive",
        ),
        CheckConstraint(
            "effective_traffic_total_snapshot IS NULL OR "
            "(effective_traffic_total_snapshot >= 0 AND "
            "effective_traffic_total_snapshot <= 100)",
            name="publication_traffic_range",
        ),
        CheckConstraint(
            "draft_version_snapshot IS NULL OR draft_version_snapshot > 0",
            name="publication_draft_version_positive",
        ),
        CheckConstraint(
            "draft_duration_seconds_snapshot IS NULL OR "
            "draft_duration_seconds_snapshot >= 0",
            name="publication_draft_duration_nonnegative",
        ),
        CheckConstraint(
            "publication_content_hash IS NULL OR "
            "char_length(publication_content_hash) = 64",
            name="publication_content_hash_sha256",
        ),
        CheckConstraint(
            "char_length(btrim(record_version)) > 0",
            name="publication_record_version_nonempty",
        ),
        Index(
            "uq_publications_platform_external_post",
            "platform_key",
            "external_post_id",
            unique=True,
            postgresql_where=text("external_post_id IS NOT NULL"),
        ),
        Index(
            "uq_publications_platform_public_url",
            "platform_key",
            "public_url",
            unique=True,
        ),
        Index("ix_publications_event_published", "event_id", "published_at"),
        Index("ix_publications_platform_published", "platform_key", "published_at"),
        Index("ix_publications_mode_published", "publication_mode", "published_at"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_drafts.id", ondelete="RESTRICT"), index=True
    )
    publication_mode: Mapped[PublicationMode] = mapped_column(
        string_enum(PublicationMode, name="publication_mode"), nullable=False
    )
    platform_key: Mapped[str] = mapped_column(String(100), nullable=False)
    account_label: Mapped[str | None] = mapped_column(String(255))
    external_post_id: Mapped[str | None] = mapped_column(String(255))
    public_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    title_snapshot: Mapped[str | None] = mapped_column(String(500))
    cover_text_snapshot: Mapped[str | None] = mapped_column(Text)
    body_snapshot: Mapped[str | None] = mapped_column(Text)
    publication_content_hash: Mapped[str | None] = mapped_column(String(64))

    candidate_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_candidate_runs.id", ondelete="RESTRICT"), index=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_candidates.id", ondelete="RESTRICT"), index=True
    )
    candidate_rank_snapshot: Mapped[int | None] = mapped_column(Integer)
    editorial_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_decisions.id", ondelete="RESTRICT"), index=True
    )
    editorial_decision_snapshot: Mapped[EditorialDecisionType | None] = mapped_column(
        string_enum(EditorialDecisionType, name="publication_editorial_decision")
    )
    base_editorial_score_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_scores.id", ondelete="RESTRICT"), index=True
    )
    editorial_score_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    effective_traffic_total_snapshot: Mapped[float | None] = mapped_column(Float)
    risk_snapshot: Mapped[EditorialRiskLevel | None] = mapped_column(
        string_enum(EditorialRiskLevel, name="publication_risk_level")
    )
    recommended_format_snapshot: Mapped[EditorialRecommendedFormat | None] = mapped_column(
        string_enum(
            EditorialRecommendedFormat,
            name="publication_recommended_format",
        )
    )

    draft_chain_id: Mapped[UUID | None] = mapped_column(index=True)
    draft_version_snapshot: Mapped[int | None] = mapped_column(Integer)
    draft_source_type_snapshot: Mapped[DraftSourceType | None] = mapped_column(
        string_enum(DraftSourceType, name="publication_draft_source_type")
    )
    draft_format_snapshot: Mapped[EditorialRecommendedFormat | None] = mapped_column(
        string_enum(EditorialRecommendedFormat, name="publication_draft_format")
    )
    draft_duration_seconds_snapshot: Mapped[int | None] = mapped_column(Integer)

    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    backfill_reason: Mapped[str | None] = mapped_column(Text)
    record_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="publication-record-v1"
    )


class PerformanceImportRunRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Auditable canonical CSV apply run. Preview never creates this record."""

    __tablename__ = "performance_import_runs"
    __table_args__ = (
        CheckConstraint(
            "char_length(file_sha256) = 64",
            name="performance_import_file_hash_sha256",
        ),
        CheckConstraint(
            "char_length(btrim(mapping_version)) > 0",
            name="performance_import_mapping_version_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(actor)) > 0",
            name="performance_import_actor_nonempty",
        ),
        CheckConstraint("row_count >= 0", name="performance_import_row_nonnegative"),
        CheckConstraint("valid_count >= 0", name="performance_import_valid_nonnegative"),
        CheckConstraint(
            "inserted_count >= 0", name="performance_import_inserted_nonnegative"
        ),
        CheckConstraint(
            "duplicate_count >= 0", name="performance_import_duplicate_nonnegative"
        ),
        CheckConstraint("error_count >= 0", name="performance_import_error_nonnegative"),
        Index(
            "uq_performance_import_success_file",
            "file_sha256",
            "mapping_version",
            unique=True,
            postgresql_where=text("status IN ('running','succeeded')"),
        ),
        Index("ix_performance_import_created", "created_at"),
    )

    source_type: Mapped[PerformanceSourceType] = mapped_column(
        string_enum(PerformanceSourceType, name="performance_import_source"),
        nullable=False,
    )
    mapping_version: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PerformanceImportStatus] = mapped_column(
        string_enum(PerformanceImportStatus, name="performance_import_status"),
        nullable=False,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PublicationPerformanceSnapshotRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only observation of real publication metrics at observed_at."""

    __tablename__ = "publication_performance_snapshots"
    __table_args__ = (
        CheckConstraint("views IS NULL OR views >= 0", name="performance_views_nonnegative"),
        CheckConstraint(
            "completion_rate IS NULL OR (completion_rate >= 0 AND completion_rate <= 1)",
            name="performance_completion_range",
        ),
        CheckConstraint(
            "average_watch_seconds IS NULL OR average_watch_seconds >= 0",
            name="performance_average_watch_nonnegative",
        ),
        CheckConstraint("likes IS NULL OR likes >= 0", name="performance_likes_nonnegative"),
        CheckConstraint(
            "comments IS NULL OR comments >= 0", name="performance_comments_nonnegative"
        ),
        CheckConstraint("shares IS NULL OR shares >= 0", name="performance_shares_nonnegative"),
        CheckConstraint(
            "favorites IS NULL OR favorites >= 0", name="performance_favorites_nonnegative"
        ),
        CheckConstraint(
            "views IS NOT NULL OR completion_rate IS NOT NULL OR "
            "average_watch_seconds IS NOT NULL OR likes IS NOT NULL OR "
            "comments IS NOT NULL OR shares IS NOT NULL OR favorites IS NOT NULL OR "
            "follower_delta IS NOT NULL",
            name="performance_at_least_one_metric",
        ),
        CheckConstraint(
            "char_length(snapshot_hash) = 64",
            name="performance_snapshot_hash_sha256",
        ),
        CheckConstraint(
            "char_length(btrim(actor)) > 0",
            name="performance_snapshot_actor_nonempty",
        ),
        CheckConstraint(
            "supersedes_snapshot_id IS NULL OR "
            "(correction_reason IS NOT NULL AND char_length(btrim(correction_reason)) > 0)",
            name="performance_correction_reason",
        ),
        CheckConstraint(
            "char_length(btrim(snapshot_version)) > 0",
            name="performance_snapshot_version_nonempty",
        ),
        Index("uq_performance_snapshot_hash", "snapshot_hash", unique=True),
        Index(
            "ix_performance_snapshot_publication_observed",
            "publication_id",
            "observed_at",
        ),
        Index("ix_performance_snapshot_import_run", "import_run_id"),
    )

    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    horizon: Mapped[PerformanceHorizon] = mapped_column(
        string_enum(PerformanceHorizon, name="performance_horizon"), nullable=False
    )
    source: Mapped[PerformanceSourceType] = mapped_column(
        string_enum(PerformanceSourceType, name="performance_source"), nullable=False
    )
    views: Mapped[int | None] = mapped_column(BigInteger)
    completion_rate: Mapped[float | None] = mapped_column(Float)
    average_watch_seconds: Mapped[float | None] = mapped_column(Float)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    favorites: Mapped[int | None] = mapped_column(BigInteger)
    follower_delta: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("publication_performance_snapshots.id", ondelete="RESTRICT"),
        index=True,
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    import_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("performance_import_runs.id", ondelete="RESTRICT"), index=True
    )
    snapshot_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="performance-snapshot-v1"
    )
