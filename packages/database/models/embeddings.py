from __future__ import annotations

from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class SignalEmbeddingRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable, versioned embedding artifact derived from one RawSignal."""

    __tablename__ = "signal_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "signal_id",
            "embedding_version",
            name="uq_signal_embeddings_signal_version",
        ),
        CheckConstraint("dimensions > 0", name="dimensions_positive"),
        CheckConstraint("char_length(input_hash) = 64", name="input_hash_sha256"),
        CheckConstraint("char_length(provider_key) > 0", name="provider_key_nonempty"),
        CheckConstraint("char_length(model_name) > 0", name="model_name_nonempty"),
        CheckConstraint(
            "char_length(embedding_version) > 0",
            name="embedding_version_nonempty",
        ),
        CheckConstraint(
            "char_length(input_schema_version) > 0",
            name="input_schema_version_nonempty",
        ),
        CheckConstraint(
            "vector_dims(embedding) = dimensions",
            name="embedding_dimensions_match",
        ),
        CheckConstraint("vector_norm(embedding) > 0", name="embedding_nonzero"),
        Index(
            "ix_signal_embeddings_version_dimensions",
            "embedding_version",
            "dimensions",
        ),
        Index("ix_signal_embeddings_created_at", "created_at"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
