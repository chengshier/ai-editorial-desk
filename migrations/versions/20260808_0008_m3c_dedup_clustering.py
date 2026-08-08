# ruff: noqa: E501
"""Add M3-C deterministic deduplication and event clustering foundation.

Revision ID: 20260808_0008
Revises: 20260808_0007
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0008"
down_revision: str | None = "20260808_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("events", sa.Column("merged_into_event_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_events_merged_into_event_id",
        "events",
        "events",
        ["merged_into_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "event_not_merged_into_self",
        "events",
        "merged_into_event_id IS NULL OR merged_into_event_id <> id",
    )
    op.create_index("ix_events_merged_into_event_id", "events", ["merged_into_event_id"])

    op.drop_constraint(
        "ck_event_signals_event_signal_relation",
        "event_signals",
        type_="check",
    )
    op.create_check_constraint(
        "event_signal_relation",
        "event_signals",
        "relation IN ('origin', 'report', 'repost', 'reaction', 'official_response', 'correction', 'related')",
    )

    op.create_table(
        "signal_fingerprints",
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("fingerprint_version", sa.String(length=100), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("simhash", sa.String(length=16), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(fingerprint_version) > 0", name="fingerprint_version_nonempty"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="fingerprint_input_hash_sha256"),
        sa.CheckConstraint("simhash ~ '^[0-9a-f]{16}$'", name="simhash_hex64"),
        sa.CheckConstraint("token_count > 0", name="fingerprint_token_count_positive"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["raw_signals.id"],
            name="fk_signal_fingerprints_signal_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_fingerprints"),
        sa.UniqueConstraint(
            "signal_id",
            "fingerprint_version",
            name="uq_signal_fingerprints_signal_version",
        ),
    )
    op.create_index("ix_signal_fingerprints_signal_id", "signal_fingerprints", ["signal_id"])
    op.create_index(
        "ix_signal_fingerprints_fingerprint_version",
        "signal_fingerprints",
        ["fingerprint_version"],
    )
    op.create_index(
        "ix_signal_fingerprints_version_created",
        "signal_fingerprints",
        ["fingerprint_version", "created_at"],
    )

    op.create_table(
        "signal_match_decisions",
        sa.Column("left_signal_id", UUID, nullable=False),
        sa.Column("right_signal_id", UUID, nullable=False),
        sa.Column("decision", sa.String(length=15), nullable=False),
        sa.Column("primary_method", sa.String(length=13), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("components", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("left_signal_id < right_signal_id", name="match_pair_canonical_order"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="match_score_range"),
        sa.CheckConstraint("char_length(algorithm_version) > 0", name="match_algorithm_version_nonempty"),
        sa.CheckConstraint(
            "decision IN ('exact_duplicate', 'near_duplicate', 'same_event', 'ambiguous', 'distinct')",
            name="signal_match_decision",
        ),
        sa.CheckConstraint(
            "primary_method IN ('canonical_url', 'content_hash', 'external_id', 'simhash', 'embedding', 'combined', 'human')",
            name="signal_match_primary_method",
        ),
        sa.ForeignKeyConstraint(
            ["left_signal_id"],
            ["raw_signals.id"],
            name="fk_signal_match_decisions_left_signal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_signal_id"],
            ["raw_signals.id"],
            name="fk_signal_match_decisions_right_signal_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_match_decisions"),
        sa.UniqueConstraint(
            "left_signal_id",
            "right_signal_id",
            "algorithm_version",
            name="uq_signal_match_decisions_pair_algorithm",
        ),
    )
    op.create_index("ix_signal_match_decisions_left", "signal_match_decisions", ["left_signal_id"])
    op.create_index("ix_signal_match_decisions_right", "signal_match_decisions", ["right_signal_id"])
    op.create_index("ix_signal_match_decisions_algorithm", "signal_match_decisions", ["algorithm_version"])
    op.create_index("ix_signal_match_decisions_decision", "signal_match_decisions", ["decision"])

    op.create_table(
        "signal_match_overrides",
        sa.Column("left_signal_id", UUID, nullable=False),
        sa.Column("right_signal_id", UUID, nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("left_signal_id < right_signal_id", name="override_pair_canonical_order"),
        sa.CheckConstraint("decision IN ('same_event', 'distinct')", name="signal_match_override_decision"),
        sa.CheckConstraint("char_length(actor) > 0", name="override_actor_nonempty"),
        sa.ForeignKeyConstraint(
            ["left_signal_id"],
            ["raw_signals.id"],
            name="fk_signal_match_overrides_left_signal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_signal_id"],
            ["raw_signals.id"],
            name="fk_signal_match_overrides_right_signal_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_match_overrides"),
        sa.UniqueConstraint(
            "left_signal_id", "right_signal_id", name="uq_signal_match_overrides_pair"
        ),
    )
    op.create_index("ix_signal_match_overrides_left", "signal_match_overrides", ["left_signal_id"])
    op.create_index("ix_signal_match_overrides_right", "signal_match_overrides", ["right_signal_id"])

    op.create_table(
        "signal_event_suppressions",
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(actor) > 0", name="suppression_actor_nonempty"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["raw_signals.id"],
            name="fk_signal_event_suppressions_signal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_signal_event_suppressions_event_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_event_suppressions"),
        sa.UniqueConstraint(
            "signal_id", "event_id", name="uq_signal_event_suppressions_signal_event"
        ),
    )
    op.create_index(
        "ix_signal_event_suppressions_signal_active",
        "signal_event_suppressions",
        ["signal_id", "active"],
    )
    op.create_index(
        "ix_signal_event_suppressions_event_active",
        "signal_event_suppressions",
        ["event_id", "active"],
    )


def downgrade() -> None:
    op.drop_index("ix_signal_event_suppressions_event_active", table_name="signal_event_suppressions")
    op.drop_index("ix_signal_event_suppressions_signal_active", table_name="signal_event_suppressions")
    op.drop_table("signal_event_suppressions")

    op.drop_index("ix_signal_match_overrides_right", table_name="signal_match_overrides")
    op.drop_index("ix_signal_match_overrides_left", table_name="signal_match_overrides")
    op.drop_table("signal_match_overrides")

    op.drop_index("ix_signal_match_decisions_decision", table_name="signal_match_decisions")
    op.drop_index("ix_signal_match_decisions_algorithm", table_name="signal_match_decisions")
    op.drop_index("ix_signal_match_decisions_right", table_name="signal_match_decisions")
    op.drop_index("ix_signal_match_decisions_left", table_name="signal_match_decisions")
    op.drop_table("signal_match_decisions")

    op.drop_index("ix_signal_fingerprints_version_created", table_name="signal_fingerprints")
    op.drop_index("ix_signal_fingerprints_fingerprint_version", table_name="signal_fingerprints")
    op.drop_index("ix_signal_fingerprints_signal_id", table_name="signal_fingerprints")
    op.drop_table("signal_fingerprints")

    op.drop_constraint(
        "ck_event_signals_event_signal_relation",
        "event_signals",
        type_="check",
    )
    op.create_check_constraint(
        "event_signal_relation",
        "event_signals",
        "relation IN ('origin', 'report', 'repost', 'reaction', 'official_response', 'correction')",
    )

    op.drop_index("ix_events_merged_into_event_id", table_name="events")
    op.drop_constraint("ck_events_event_not_merged_into_self", "events", type_="check")
    op.drop_constraint("fk_events_merged_into_event_id", "events", type_="foreignkey")
    op.drop_column("events", "merged_into_event_id")
