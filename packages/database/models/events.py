from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import UTCDateTime, string_enum, utc_now


class EventStatus(StrEnum):
    EMERGING = "emerging"
    GROWING = "growing"
    STABLE = "stable"
    DECLINING = "declining"
    RESOLVED = "resolved"


class EventSignalRelation(StrEnum):
    ORIGIN = "origin"
    REPORT = "report"
    REPOST = "repost"
    REACTION = "reaction"
    OFFICIAL_RESPONSE = "official_response"
    CORRECTION = "correction"


class EventSignalAttachedBy(StrEnum):
    RULE = "rule"
    EMBEDDING = "embedding"
    LLM = "llm"
    HUMAN = "human"


class EventRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Processing-layer event derived from explicit RawSignal relationships."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("source_count >= 0", name="source_count_nonnegative"),
        CheckConstraint("platform_count >= 0", name="platform_count_nonnegative"),
        Index("ix_events_status", "status"),
        Index("ix_events_first_seen_at", "first_seen_at"),
        Index("ix_events_last_updated_at", "last_updated_at"),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[EventStatus] = mapped_column(
        string_enum(EventStatus, name="event_status"),
        nullable=False,
        default=EventStatus.EMERGING,
        server_default=text("'emerging'"),
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    primary_language: Mapped[str | None] = mapped_column(String(32))
    entities: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    platform_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class EventSignalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Explicit provenance relationship from an Event to a RawSignal."""

    __tablename__ = "event_signals"
    __table_args__ = (
        UniqueConstraint("event_id", "signal_id", name="uq_event_signals_event_signal"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    relation: Mapped[EventSignalRelation] = mapped_column(
        string_enum(EventSignalRelation, name="event_signal_relation"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    attached_by: Mapped[EventSignalAttachedBy] = mapped_column(
        string_enum(EventSignalAttachedBy, name="event_signal_attached_by"), nullable=False
    )
