from __future__ import annotations

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import UTCDateTime, string_enum
from packages.risk_guard.models import AccountStatus

JSON_OBJECT_DEFAULT = text("'{}'::jsonb")


class ConnectorDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered connector implementation and its schema-driven capabilities."""

    __tablename__ = "connector_definitions"
    __table_args__ = (
        UniqueConstraint(
            "connector_type",
            "platform",
            name="uq_connector_definitions_type_platform",
        ),
        Index("ix_connector_definitions_enabled", "is_enabled"),
    )

    connector_type: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    config_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    ui_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    implementation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    instances: Mapped[list[ConnectorInstance]] = relationship(back_populates="definition")


class ConnectorInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user-managed connector configuration without plaintext credentials."""

    __tablename__ = "connector_instances"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "name",
            name="uq_connector_instances_definition_name",
        ),
        CheckConstraint("config_version >= 1", name="config_version_positive"),
        Index("ix_connector_instances_enabled_status", "enabled", "status"),
    )

    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="configured",
        server_default=text("'configured'"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    schedule_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    config_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(255))

    definition: Mapped[ConnectorDefinition] = relationship(back_populates="instances")
    accounts: Mapped[list[PlatformAccount]] = relationship(back_populates="connector_instance")


class PlatformAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A collection account and its shared Risk Guard state."""

    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint(
            "connector_instance_id",
            "platform",
            "account_identifier",
            name="uq_platform_accounts_instance_platform_identifier",
        ),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_nonnegative"),
        CheckConstraint("daily_request_count >= 0", name="daily_request_count_nonnegative"),
        CheckConstraint("daily_item_count >= 0", name="daily_item_count_nonnegative"),
        CheckConstraint("daily_comment_count >= 0", name="daily_comment_count_nonnegative"),
        Index("ix_platform_accounts_platform_status", "platform", "status"),
        Index("ix_platform_accounts_review", "manual_review_required", "cooldown_until"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    browser_profile_ref: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[AccountStatus] = mapped_column(
        string_enum(AccountStatus, name="account_status"),
        nullable=False,
        default=AccountStatus.HEALTHY,
        server_default=text("'healthy'"),
    )
    risk_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="unknown",
        server_default=text("'unknown'"),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_warning_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_warning_code: Mapped[str | None] = mapped_column(String(100))
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    daily_request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    daily_item_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    daily_comment_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    connector_instance: Mapped[ConnectorInstance] = relationship(back_populates="accounts")
