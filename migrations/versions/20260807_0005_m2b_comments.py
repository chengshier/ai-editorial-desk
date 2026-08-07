# ruff: noqa: E501
"""Add M2-B idempotent RawSignal comment persistence.

Revision ID: 20260807_0005
Revises: 20260807_0004
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0005"
down_revision: str | None = "20260807_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "raw_signal_comments",
        sa.Column("raw_signal_id", UUID, nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("external_comment_id", sa.String(length=500)),
        sa.Column("author_id", sa.String(length=500)),
        sa.Column("author_name", sa.String(length=500)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("like_count", sa.Integer()),
        sa.Column("parent_comment_id", sa.String(length=500)),
        sa.Column("raw_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("char_length(idempotency_key) = 64", name="ck_raw_signal_comments_comment_idempotency_sha256"),
        sa.CheckConstraint("like_count IS NULL OR like_count >= 0", name="ck_raw_signal_comments_comment_like_count_nonnegative"),
        sa.ForeignKeyConstraint(["raw_signal_id"], ["raw_signals.id"], name="fk_raw_signal_comments_raw_signal_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_raw_signal_comments"),
        sa.UniqueConstraint("idempotency_key", name="uq_raw_signal_comments_idempotency_key"),
    )
    op.create_index("ix_raw_signal_comments_raw_signal_id", "raw_signal_comments", ["raw_signal_id"])
    op.create_index("ix_raw_signal_comments_signal_published", "raw_signal_comments", ["raw_signal_id", "published_at"])
    op.create_index("ix_raw_signal_comments_platform_comment", "raw_signal_comments", ["platform", "external_comment_id"])


def downgrade() -> None:
    op.drop_index("ix_raw_signal_comments_platform_comment", table_name="raw_signal_comments")
    op.drop_index("ix_raw_signal_comments_signal_published", table_name="raw_signal_comments")
    op.drop_index("ix_raw_signal_comments_raw_signal_id", table_name="raw_signal_comments")
    op.drop_table("raw_signal_comments")
