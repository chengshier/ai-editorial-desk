from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import SanitizedJSONB, UTCDateTime, string_enum


class ScheduleType(StrEnum):
    INTERVAL = "interval"
    CRON = "cron"


class ScheduleTriggerStatus(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED_REVIEW = "paused_review"


class ConnectorValidationStatus(StrEnum):
    NOT_TESTED = "not_tested"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class CollectionSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable schedule configuration; PostgreSQL is the scheduling source of truth."""

    __tablename__ = "collection_schedules"
    __table_args__ = (
        UniqueConstraint("source_id", "name", name="uq_collection_schedules_source_name"),
        CheckConstraint("requested_limit >= 1", name="requested_limit_positive"),
        CheckConstraint(
            "interval_seconds IS NULL OR interval_seconds >= 300",
            name="interval_minimum_five_minutes",
        ),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_nonnegative"),
        Index("ix_collection_schedules_due", "enabled", "next_run_at"),
        Index("ix_collection_schedules_lease", "lease_expires_at"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    schedule_type: Mapped[ScheduleType] = mapped_column(
        string_enum(ScheduleType, name="collection_schedule_type"), nullable=False
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    cron_expression: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(
        String(100), nullable=False, default="UTC", server_default=text("'UTC'")
    )
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("connector_runs.id", ondelete="SET NULL"), index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    paused_reason: Mapped[str | None] = mapped_column(String(500))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class CollectionScheduleTrigger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One durable schedule time-slot; uniqueness prevents duplicate triggering."""

    __tablename__ = "collection_schedule_triggers"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "scheduled_for_at", name="uq_collection_schedule_triggers_slot"
        ),
        Index("ix_collection_schedule_triggers_lease", "status", "lease_expires_at"),
    )

    schedule_id: Mapped[UUID] = mapped_column(
        ForeignKey("collection_schedules.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scheduled_for_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[ScheduleTriggerStatus] = mapped_column(
        string_enum(ScheduleTriggerStatus, name="collection_schedule_trigger_status"),
        nullable=False,
        default=ScheduleTriggerStatus.CLAIMED,
        server_default=text("'claimed'"),
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("connector_runs.id", ondelete="SET NULL"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class SchedulerInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Scheduler heartbeat persisted for status/debugging without secrets."""

    __tablename__ = "scheduler_instances"
    __table_args__ = (
        UniqueConstraint("instance_key", name="uq_scheduler_instances_instance_key"),
        CheckConstraint(
            "recent_trigger_failures >= 0", name="recent_trigger_failures_nonnegative"
        ),
        Index("ix_scheduler_instances_heartbeat", "last_heartbeat"),
    )

    instance_key: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_heartbeat: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recent_trigger_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class ConnectorValidationRecord(UUIDPrimaryKeyMixin, Base):
    """Actor-recorded real smoke-test outcome; CI mocks never create PASSED records."""

    __tablename__ = "connector_validation_records"
    __table_args__ = (
        Index(
            "ix_connector_validation_lookup",
            "connector_type",
            "platform",
            "environment",
            "created_at",
        ),
    )

    connector_type: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    implementation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ConnectorValidationStatus] = mapped_column(
        string_enum(ConnectorValidationStatus, name="connector_validation_status"),
        nullable=False,
    )
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    validated_by: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    safe_evidence: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
