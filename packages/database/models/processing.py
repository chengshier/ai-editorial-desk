from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.models.events import EventSignalAttachedBy
from packages.database.types import SanitizedJSONB, UTCDateTime, string_enum, utc_now


class ClusteringProcessingMode(StrEnum):
    EVALUATE = "evaluate"
    DRY_RUN = "dry_run"
    APPLY = "apply"


class ClusteringProcessingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventAssignmentAction(StrEnum):
    CREATE_EVENT = "create_event"
    ATTACH = "attach"
    MOVE = "move"
    DETACH = "detach"
    CONFLICT = "conflict"


class ClusteringProcessingRunRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Processing-layer audit record for evaluation and bounded reprocessing."""

    __tablename__ = "clustering_processing_runs"
    __table_args__ = (
        CheckConstraint(
            "char_length(algorithm_version) > 0",
            name="processing_algorithm_version_nonempty",
        ),
        CheckConstraint("requested_count >= 0", name="processing_requested_count_nonnegative"),
        CheckConstraint("processed_count >= 0", name="processing_processed_count_nonnegative"),
        Index("ix_clustering_processing_runs_status_started", "status", "started_at"),
        Index(
            "ix_clustering_processing_runs_algorithm_started",
            "algorithm_version",
            "started_at",
        ),
    )

    mode: Mapped[ClusteringProcessingMode] = mapped_column(
        string_enum(ClusteringProcessingMode, name="clustering_processing_mode"),
        nullable=False,
    )
    status: Mapped[ClusteringProcessingStatus] = mapped_column(
        string_enum(ClusteringProcessingStatus, name="clustering_processing_status"),
        nullable=False,
        default=ClusteringProcessingStatus.PENDING,
        server_default=text("'pending'"),
    )
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dataset_version: Mapped[str | None] = mapped_column(String(100))
    actor: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    requested_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    processed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    counters: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_summary: Mapped[str | None] = mapped_column(Text)


class EventAssignmentRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable provenance for automatic Event membership changes."""

    __tablename__ = "event_assignment_records"
    __table_args__ = (
        CheckConstraint(
            "char_length(algorithm_version) > 0",
            name="assignment_algorithm_version_nonempty",
        ),
        Index("ix_event_assignment_records_signal_created", "signal_id", "created_at"),
        Index("ix_event_assignment_records_event_created", "event_id", "created_at"),
        Index(
            "ix_event_assignment_records_algorithm_created",
            "algorithm_version",
            "created_at",
        ),
        Index(
            "ix_event_assignment_records_run_created",
            "processing_run_id",
            "created_at",
        ),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[EventAssignmentAction] = mapped_column(
        string_enum(EventAssignmentAction, name="event_assignment_action"), nullable=False
    )
    attached_by: Mapped[EventSignalAttachedBy] = mapped_column(
        string_enum(EventSignalAttachedBy, name="event_assignment_attached_by"), nullable=False
    )
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    match_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("signal_match_decisions.id", ondelete="SET NULL")
    )
    processing_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("clustering_processing_runs.id", ondelete="SET NULL")
    )
    previous_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL")
    )
