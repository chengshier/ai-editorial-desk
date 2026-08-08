from __future__ import annotations

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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import SanitizedJSONB, string_enum


class MatchDecisionType(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    SAME_EVENT = "same_event"
    AMBIGUOUS = "ambiguous"
    DISTINCT = "distinct"


class MatchPrimaryMethod(StrEnum):
    CANONICAL_URL = "canonical_url"
    CONTENT_HASH = "content_hash"
    EXTERNAL_ID = "external_id"
    SIMHASH = "simhash"
    EMBEDDING = "embedding"
    COMBINED = "combined"
    HUMAN = "human"


class MatchOverrideDecision(StrEnum):
    SAME_EVENT = "same_event"
    DISTINCT = "distinct"


class SignalFingerprintRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable deterministic fingerprint artifact derived from one RawSignal."""

    __tablename__ = "signal_fingerprints"
    __table_args__ = (
        UniqueConstraint(
            "signal_id",
            "fingerprint_version",
            name="uq_signal_fingerprints_signal_version",
        ),
        CheckConstraint(
            "char_length(fingerprint_version) > 0",
            name="fingerprint_version_nonempty",
        ),
        CheckConstraint("char_length(input_hash) = 64", name="fingerprint_input_hash_sha256"),
        CheckConstraint("simhash ~ '^[0-9a-f]{16}$'", name="simhash_hex64"),
        CheckConstraint("token_count > 0", name="fingerprint_token_count_positive"),
        Index("ix_signal_fingerprints_version_created", "fingerprint_version", "created_at"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simhash: Mapped[str] = mapped_column(String(16), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)


class SignalMatchDecisionRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable algorithm decision for one canonical RawSignal pair and algorithm version."""

    __tablename__ = "signal_match_decisions"
    __table_args__ = (
        UniqueConstraint(
            "left_signal_id",
            "right_signal_id",
            "algorithm_version",
            name="uq_signal_match_decisions_pair_algorithm",
        ),
        CheckConstraint("left_signal_id < right_signal_id", name="match_pair_canonical_order"),
        CheckConstraint("score >= 0 AND score <= 1", name="match_score_range"),
        CheckConstraint(
            "char_length(algorithm_version) > 0",
            name="match_algorithm_version_nonempty",
        ),
        Index("ix_signal_match_decisions_left", "left_signal_id"),
        Index("ix_signal_match_decisions_right", "right_signal_id"),
        Index("ix_signal_match_decisions_algorithm", "algorithm_version"),
        Index("ix_signal_match_decisions_decision", "decision"),
    )

    left_signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    right_signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[MatchDecisionType] = mapped_column(
        string_enum(MatchDecisionType, name="signal_match_decision"), nullable=False
    )
    primary_method: Mapped[MatchPrimaryMethod] = mapped_column(
        string_enum(MatchPrimaryMethod, name="signal_match_primary_method"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)


class SignalMatchOverrideRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Current human decision that supersedes automatic pair matching."""

    __tablename__ = "signal_match_overrides"
    __table_args__ = (
        UniqueConstraint(
            "left_signal_id", "right_signal_id", name="uq_signal_match_overrides_pair"
        ),
        CheckConstraint("left_signal_id < right_signal_id", name="override_pair_canonical_order"),
        CheckConstraint("char_length(actor) > 0", name="override_actor_nonempty"),
        Index("ix_signal_match_overrides_left", "left_signal_id"),
        Index("ix_signal_match_overrides_right", "right_signal_id"),
    )

    left_signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    right_signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[MatchOverrideDecision] = mapped_column(
        string_enum(MatchOverrideDecision, name="signal_match_override_decision"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)


class SignalEventSuppressionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Human event-level suppression preventing automatic re-assignment."""

    __tablename__ = "signal_event_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "signal_id", "event_id", name="uq_signal_event_suppressions_signal_event"
        ),
        CheckConstraint("char_length(actor) > 0", name="suppression_actor_nonempty"),
        Index("ix_signal_event_suppressions_signal_active", "signal_id", "active"),
        Index("ix_signal_event_suppressions_event_active", "event_id", "active"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
