# ruff: noqa: E501
"""Add M3-A Event and EventSignal foundation.

Revision ID: 20260808_0006
Revises: 20260807_0005
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0006"
down_revision: str | None = "20260807_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.String(length=100)),
        sa.Column("status", sa.String(length=9), server_default=sa.text("'emerging'"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("primary_language", sa.String(length=32)),
        sa.Column("entities", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("keywords", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("platform_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('emerging', 'growing', 'stable', 'declining', 'resolved')", name="event_status"),
        sa.CheckConstraint("source_count >= 0", name="source_count_nonnegative"),
        sa.CheckConstraint("platform_count >= 0", name="platform_count_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
    )
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_events_first_seen_at", "events", ["first_seen_at"])
    op.create_index("ix_events_last_updated_at", "events", ["last_updated_at"])

    op.create_table(
        "event_signals",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("relation", sa.String(length=17), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("attached_by", sa.String(length=9), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("relation IN ('origin', 'report', 'repost', 'reaction', 'official_response', 'correction')", name="event_signal_relation"),
        sa.CheckConstraint("attached_by IN ('rule', 'embedding', 'llm', 'human')", name="event_signal_attached_by"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_event_signals_event_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signal_id"], ["raw_signals.id"], name="fk_event_signals_signal_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_signals"),
        sa.UniqueConstraint("event_id", "signal_id", name="uq_event_signals_event_signal"),
    )
    op.create_index("ix_event_signals_event_id", "event_signals", ["event_id"])
    op.create_index("ix_event_signals_signal_id", "event_signals", ["signal_id"])


def downgrade() -> None:
    op.drop_index("ix_event_signals_signal_id", table_name="event_signals")
    op.drop_index("ix_event_signals_event_id", table_name="event_signals")
    op.drop_table("event_signals")
    op.drop_index("ix_events_last_updated_at", table_name="events")
    op.drop_index("ix_events_first_seen_at", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_table("events")
