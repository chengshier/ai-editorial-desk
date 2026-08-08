# ruff: noqa: E501
"""Add M3-B versioned Signal Embedding foundation.

Revision ID: 20260808_0007
Revises: 20260808_0006
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0007"
down_revision: str | None = "20260808_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # The container image already exposes pgvector, but Alembic owns schema readiness.
    # Downgrade intentionally keeps the shared extension installed for future consumers.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "signal_embeddings",
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("input_schema_version", sa.String(length=100), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("dimensions > 0", name="dimensions_positive"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="input_hash_sha256"),
        sa.CheckConstraint("char_length(provider_key) > 0", name="provider_key_nonempty"),
        sa.CheckConstraint("char_length(model_name) > 0", name="model_name_nonempty"),
        sa.CheckConstraint("char_length(embedding_version) > 0", name="embedding_version_nonempty"),
        sa.CheckConstraint("char_length(input_schema_version) > 0", name="input_schema_version_nonempty"),
        sa.CheckConstraint("vector_dims(embedding) = dimensions", name="embedding_dimensions_match"),
        sa.CheckConstraint("vector_norm(embedding) > 0", name="embedding_nonzero"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["raw_signals.id"],
            name="fk_signal_embeddings_signal_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_embeddings"),
        sa.UniqueConstraint(
            "signal_id",
            "embedding_version",
            name="uq_signal_embeddings_signal_version",
        ),
    )
    op.create_index("ix_signal_embeddings_signal_id", "signal_embeddings", ["signal_id"])
    op.create_index(
        "ix_signal_embeddings_embedding_version",
        "signal_embeddings",
        ["embedding_version"],
    )
    op.create_index(
        "ix_signal_embeddings_version_dimensions",
        "signal_embeddings",
        ["embedding_version", "dimensions"],
    )
    op.create_index("ix_signal_embeddings_created_at", "signal_embeddings", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_signal_embeddings_created_at", table_name="signal_embeddings")
    op.drop_index(
        "ix_signal_embeddings_version_dimensions",
        table_name="signal_embeddings",
    )
    op.drop_index(
        "ix_signal_embeddings_embedding_version",
        table_name="signal_embeddings",
    )
    op.drop_index("ix_signal_embeddings_signal_id", table_name="signal_embeddings")
    op.drop_table("signal_embeddings")
    # Do not DROP EXTENSION vector: it is shared database capability, not table ownership.
