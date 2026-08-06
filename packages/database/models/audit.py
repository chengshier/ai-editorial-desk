from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.types import SanitizedJSONB

JSON_OBJECT_DEFAULT = text("'{}'::jsonb")


class ConfigurationChangeLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Lightweight, immutable audit trail for configuration mutations."""

    __tablename__ = "configuration_change_logs"
    __table_args__ = (
        Index(
            "ix_configuration_change_logs_entity_created",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index("ix_configuration_change_logs_actor_created", "actor", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    before_data: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    after_data: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
