from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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
from packages.database.types import UTCDateTime, string_enum, utc_now

JSON_OBJECT_DEFAULT = text("'{}'::jsonb")


class ConnectorRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED_RISK = "paused_risk"
    PARTIAL = "partial"


class ConnectorRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One connector execution and its durable progress/error summary."""

    __tablename__ = "connector_runs"
    __table_args__ = (
        CheckConstraint("requested_limit >= 0", name="requested_limit_nonnegative"),
        CheckConstraint("collected_count >= 0", name="collected_count_nonnegative"),
        CheckConstraint("inserted_count >= 0", name="inserted_count_nonnegative"),
        CheckConstraint("duplicate_count >= 0", name="duplicate_count_nonnegative"),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        Index("ix_connector_runs_instance_created", "connector_instance_id", "created_at"),
        Index("ix_connector_runs_status_started", "status", "started_at"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ConnectorRunStatus] = mapped_column(
        string_enum(ConnectorRunStatus, name="connector_run_status"),
        nullable=False,
        default=ConnectorRunStatus.PENDING,
        server_default=text("'pending'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    requested_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    collected_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    inserted_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    checkpoint_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checkpoint_after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )


class ConnectorCheckpoint(UUIDPrimaryKeyMixin, Base):
    """Main-system checkpoint independent from MediaCrawler internal tables."""

    __tablename__ = "connector_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "connector_instance_id",
            "platform_account_id",
            "mode",
            "scope_key",
            name="uq_connector_checkpoints_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_connector_checkpoints_instance_updated", "connector_instance_id", "updated_at"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(500), nullable=False)
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    watermark: Mapped[str | None] = mapped_column(String(500))
    last_external_id: Mapped[str | None] = mapped_column(String(500))
    last_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    checkpoint_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=utc_now,
    )
