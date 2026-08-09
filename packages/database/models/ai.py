from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from packages.database.types import SanitizedJSONB, UTCDateTime

JSON_OBJECT_DEFAULT = text("'{}'::jsonb")
JSON_ARRAY_DEFAULT = text("'[]'::jsonb")


class AIProviderRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Administrator-managed provider endpoint with an opaque credential reference."""

    __tablename__ = "ai_providers"
    __table_args__ = (
        UniqueConstraint("provider_key", name="uq_ai_providers_provider_key"),
        CheckConstraint("timeout_seconds > 0", name="ai_provider_timeout_positive"),
        CheckConstraint("max_concurrency > 0", name="ai_provider_concurrency_positive"),
        CheckConstraint("retry_limit >= 0", name="ai_provider_retry_nonnegative"),
        CheckConstraint(
            "validation_status IN ('NOT_TESTED','PASSED','FAILED')",
            name="ai_provider_validation_status_valid",
        ),
        Index("ix_ai_providers_enabled", "enabled"),
    )

    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NOT_TESTED", server_default=text("'NOT_TESTED'")
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    max_concurrency: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4, server_default=text("4")
    )
    retry_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class AIModelRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stable internal model key mapped to a provider's concrete model name."""

    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_key", name="uq_ai_models_provider_model_key"),
        CheckConstraint(
            "context_window IS NULL OR context_window > 0", name="ai_model_context_positive"
        ),
        CheckConstraint(
            "dimensions IS NULL OR dimensions > 0", name="ai_model_dimensions_positive"
        ),
        CheckConstraint(
            "input_price_per_million IS NULL OR input_price_per_million >= 0",
            name="ai_model_input_price_nonnegative",
        ),
        CheckConstraint(
            "output_price_per_million IS NULL OR output_price_per_million >= 0",
            name="ai_model_output_price_nonnegative",
        ),
        CheckConstraint(
            "embedding_price_per_million IS NULL OR embedding_price_per_million >= 0",
            name="ai_model_embedding_price_nonnegative",
        ),
        Index("ix_ai_models_provider_enabled", "provider_id", "enabled"),
    )

    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=JSON_ARRAY_DEFAULT
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    context_window: Mapped[int | None] = mapped_column(Integer)
    input_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    output_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    embedding_price_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    pricing_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="unpriced-v1", server_default=text("'unpriced-v1'")
    )
    dimensions: Mapped[int | None] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))


class AITaskRouteRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Versioned task route; prior rows remain addressable by historical invocations."""

    __tablename__ = "ai_task_routes"
    __table_args__ = (
        UniqueConstraint("task_key", "version", name="uq_ai_task_routes_task_version"),
        CheckConstraint("version >= 1", name="ai_route_version_positive"),
        CheckConstraint("timeout_seconds > 0", name="ai_route_timeout_positive"),
        CheckConstraint("retry_limit >= 0", name="ai_route_retry_nonnegative"),
        Index(
            "uq_ai_task_routes_active_task",
            "task_key",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_ai_task_routes_enabled", "enabled", "task_key"),
    )

    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    primary_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="RESTRICT"), index=True
    )
    fallback_model_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=JSON_ARRAY_DEFAULT
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    retry_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    budget_policy: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_by: Mapped[str | None] = mapped_column(String(255))


class AIBudgetRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI-specific cost/token budget; CollectionBudget semantics are not overloaded."""

    __tablename__ = "ai_budgets"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", name="uq_ai_budgets_scope"),
        CheckConstraint("scope_type IN ('global','task','provider')", name="ai_budget_scope_valid"),
        CheckConstraint(
            "daily_cost_limit IS NULL OR daily_cost_limit >= 0",
            name="ai_budget_daily_cost_nonnegative",
        ),
        CheckConstraint(
            "monthly_cost_limit IS NULL OR monthly_cost_limit >= 0",
            name="ai_budget_monthly_cost_nonnegative",
        ),
        CheckConstraint(
            "daily_token_limit IS NULL OR daily_token_limit >= 0",
            name="ai_budget_daily_tokens_nonnegative",
        ),
        CheckConstraint(
            "unknown_usage_policy IN ('block','allow_once')",
            name="ai_budget_unknown_policy_valid",
        ),
        Index("ix_ai_budgets_enabled_scope", "enabled", "scope_type"),
    )

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    daily_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    monthly_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    daily_token_limit: Mapped[int | None] = mapped_column(Integer)
    unknown_usage_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="block", server_default=text("'block'")
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    updated_by: Mapped[str | None] = mapped_column(String(255))


class AIBudgetUsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Daily reservation/settlement row; budget row locks serialize monthly checks."""

    __tablename__ = "ai_budget_usages"
    __table_args__ = (
        UniqueConstraint("budget_id", "usage_date", name="uq_ai_budget_usages_budget_date"),
        CheckConstraint("reserved_cost >= 0", name="ai_budget_usage_reserved_cost_nonnegative"),
        CheckConstraint("settled_cost >= 0", name="ai_budget_usage_settled_cost_nonnegative"),
        CheckConstraint(
            "reserved_tokens >= 0", name="ai_budget_usage_reserved_tokens_nonnegative"
        ),
        CheckConstraint(
            "settled_tokens >= 0", name="ai_budget_usage_settled_tokens_nonnegative"
        ),
        CheckConstraint(
            "unknown_usage_count >= 0", name="ai_budget_usage_unknown_nonnegative"
        ),
        CheckConstraint(
            "active_reservations >= 0", name="ai_budget_usage_active_nonnegative"
        ),
        CheckConstraint("version >= 0", name="ai_budget_usage_version_nonnegative"),
        Index("ix_ai_budget_usages_date", "usage_date"),
    )

    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usage_date: Mapped[date] = mapped_column(nullable=False)
    reserved_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    settled_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    reserved_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    settled_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    unknown_usage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    active_reservations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class AIInvocationRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One logical AI call; prompt/body and credentials are intentionally absent."""

    __tablename__ = "ai_invocations"
    __table_args__ = (
        CheckConstraint("route_version >= 1", name="ai_invocation_route_version_positive"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ai_invocation_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ai_invocation_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ai_invocation_total_tokens_nonnegative",
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ai_invocation_cost_nonnegative",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ai_invocation_latency_nonnegative"
        ),
        CheckConstraint("retry_count >= 0", name="ai_invocation_retry_nonnegative"),
        CheckConstraint("fallback_index >= 0", name="ai_invocation_fallback_nonnegative"),
        Index("ix_ai_invocations_task_started", "task_key", "started_at"),
        Index("ix_ai_invocations_status_started", "status", "started_at"),
    )

    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    route_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_task_routes.id", ondelete="RESTRICT"), index=True
    )
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(255))
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    schema_version: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    fallback_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    subject_type: Mapped[str | None] = mapped_column(String(100))
    subject_id: Mapped[str | None] = mapped_column(String(255))
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(String(100))


class AIInvocationAttemptRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only provider attempt, including retry and fallback positions."""

    __tablename__ = "ai_invocation_attempts"
    __table_args__ = (
        UniqueConstraint("invocation_id", "attempt_no", name="uq_ai_invocation_attempts_no"),
        CheckConstraint("attempt_no >= 1", name="ai_attempt_no_positive"),
        CheckConstraint("retry_index >= 0", name="ai_attempt_retry_nonnegative"),
        CheckConstraint("fallback_index >= 0", name="ai_attempt_fallback_nonnegative"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ai_attempt_input_tokens_nonnegative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ai_attempt_output_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="ai_attempt_total_tokens_nonnegative"
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0", name="ai_attempt_cost_nonnegative"
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ai_attempt_latency_nonnegative"),
        Index("ix_ai_invocation_attempts_invocation", "invocation_id", "attempt_no"),
    )

    invocation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_invocations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    fallback_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(
        SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", SanitizedJSONB(), nullable=False, default=dict, server_default=JSON_OBJECT_DEFAULT
    )
