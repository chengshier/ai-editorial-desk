from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from packages.database.types import SanitizedJSONB, UTCDateTime, string_enum, utc_now
from packages.risk_guard.models import RiskAction

JSON_OBJECT_DEFAULT = text("'{}'::jsonb")


class PlatformRiskEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A security-relevant platform event, separate from ordinary run errors."""

    __tablename__ = "platform_risk_events"
    __table_args__ = (
        Index("ix_platform_risk_events_account_occurred", "platform_account_id", "occurred_at"),
        Index("ix_platform_risk_events_platform_level", "platform", "risk_level"),
        Index("ix_platform_risk_events_unresolved", "resolved_at", "manual_review_required"),
    )

    connector_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("connector_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    connector_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("connector_runs.id", ondelete="SET NULL"),
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_type: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_error_code: Mapped[str | None] = mapped_column(String(100))
    standard_error_code: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[RiskAction] = mapped_column(
        string_enum(RiskAction, name="risk_action"),
        nullable=False,
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    request_context: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(),
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    response_context: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(),
        nullable=False,
        default=dict,
        server_default=JSON_OBJECT_DEFAULT,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    manual_review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
