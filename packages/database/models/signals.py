from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from packages.database.types import SanitizedJSONB, UTCDateTime, utc_now

JSON_OBJECT_DEFAULT = sql_text("'{}'::jsonb")
JSON_ARRAY_DEFAULT = sql_text("'[]'::jsonb")


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable collection scope owned by one connector instance."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint(
            "connector_instance_id",
            "mode",
            "scope_key",
            name="uq_sources_instance_mode_scope",
        ),
        Index(
            "ix_sources_instance_enabled",
            "connector_instance_id",
            "enabled",
            "status",
        ),
        Index("ix_sources_type_status", "source_type", "status"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(500), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(2000))
    config: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(),
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default=sql_text("'active'"),
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class RawSignalRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable normalized signal produced by a connector."""

    __tablename__ = "raw_signals"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_raw_signals_idempotency_key",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="content_hash_sha256",
        ),
        Index("ix_raw_signals_source_published", "source_id", "published_at"),
        Index("ix_raw_signals_platform_published", "platform", "published_at"),
        Index("ix_raw_signals_run_created", "connector_run_id", "created_at"),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    connector_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("connector_runs.id", ondelete="SET NULL"),
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(500))
    original_url: Mapped[str] = mapped_column(String(4000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(4000), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str | None] = mapped_column(String(500))
    author_name: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    collected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=sql_text("CURRENT_TIMESTAMP"),
    )
    metrics: Mapped[dict[str, int | float]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    media: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=JSON_ARRAY_DEFAULT,
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(),
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    language: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(1000), nullable=False)


class RawSignalCommentRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One normalized comment bound to a persisted RawSignal."""

    __tablename__ = "raw_signal_comments"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_raw_signal_comments_idempotency_key",
        ),
        CheckConstraint(
            "char_length(idempotency_key) = 64",
            name="comment_idempotency_sha256",
        ),
        CheckConstraint(
            "like_count IS NULL OR like_count >= 0",
            name="comment_like_count_nonnegative",
        ),
        Index(
            "ix_raw_signal_comments_signal_published",
            "raw_signal_id",
            "published_at",
        ),
        Index(
            "ix_raw_signal_comments_platform_comment",
            "platform",
            "external_comment_id",
        ),
    )

    raw_signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    external_comment_id: Mapped[str | None] = mapped_column(String(500))
    author_id: Mapped[str | None] = mapped_column(String(500))
    author_name: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    like_count: Mapped[int | None] = mapped_column(Integer)
    parent_comment_id: Mapped[str | None] = mapped_column(String(500))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(),
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=sql_text("CURRENT_TIMESTAMP"),
    )


class CollectionBudget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Database-managed collection limits for one stable scope."""

    __tablename__ = "collection_budgets"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_key",
            name="uq_collection_budgets_scope",
        ),
        CheckConstraint(
            "max_runs_per_day >= 1",
            name="max_runs_per_day_positive",
        ),
        CheckConstraint(
            "max_items_per_run >= 1",
            name="max_items_per_run_positive",
        ),
        CheckConstraint(
            "max_items_per_day >= 1",
            name="max_items_per_day_positive",
        ),
        CheckConstraint(
            "max_comments_per_run >= 0",
            name="max_comments_per_run_nonnegative",
        ),
        CheckConstraint(
            "max_comments_per_day >= 0",
            name="max_comments_per_day_nonnegative",
        ),
        CheckConstraint(
            "max_concurrency >= 1",
            name="max_concurrency_positive",
        ),
        Index("ix_collection_budgets_enabled_scope", "enabled", "scope_type"),
    )

    scope_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(500), nullable=False)
    max_runs_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=sql_text("100"),
    )
    max_items_per_run: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=sql_text("100"),
    )
    max_items_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5000,
        server_default=sql_text("5000"),
    )
    max_comments_per_run: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    max_comments_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    max_concurrency: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Shanghai",
        server_default=sql_text("'Asia/Shanghai'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )
    updated_by: Mapped[str | None] = mapped_column(String(255))


class CollectionBudgetUsage(UUIDPrimaryKeyMixin, Base):
    """One locked daily usage row used for atomic budget reservation."""

    __tablename__ = "collection_budget_usage"
    __table_args__ = (
        UniqueConstraint(
            "budget_id",
            "usage_date",
            name="uq_collection_budget_usage_day",
        ),
        CheckConstraint("runs_reserved >= 0", name="runs_reserved_nonnegative"),
        CheckConstraint("runs_completed >= 0", name="runs_completed_nonnegative"),
        CheckConstraint("items_reserved >= 0", name="items_reserved_nonnegative"),
        CheckConstraint("items_used >= 0", name="items_used_nonnegative"),
        CheckConstraint(
            "comments_reserved >= 0",
            name="comments_reserved_nonnegative",
        ),
        CheckConstraint("comments_used >= 0", name="comments_used_nonnegative"),
        CheckConstraint("active_runs >= 0", name="active_runs_nonnegative"),
        CheckConstraint("version >= 1", name="budget_usage_version_positive"),
        Index("ix_collection_budget_usage_date", "usage_date"),
    )

    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection_budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    runs_reserved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    runs_completed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    items_reserved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    items_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    comments_reserved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    comments_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    active_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sql_text("1"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=sql_text("CURRENT_TIMESTAMP"),
        onupdate=utc_now,
    )
