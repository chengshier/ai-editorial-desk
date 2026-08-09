# ruff: noqa: E501
"""Add M4-A AI gateway, routing, invocation audit and budget governance.

Revision ID: 20260809_0010
Revises: 20260808_0009
Create Date: 2026-08-09
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0010"
down_revision: str | None = "20260808_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
MONEY = sa.Numeric(18, 8)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_providers",
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("provider_type", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("credential_ref", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("validation_status", sa.String(20), server_default=sa.text("'NOT_TESTED'"), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default=sa.text("4"), nullable=False),
        sa.Column("retry_limit", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("id", UUID, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("timeout_seconds > 0", name="ai_provider_timeout_positive"),
        sa.CheckConstraint("max_concurrency > 0", name="ai_provider_concurrency_positive"),
        sa.CheckConstraint("retry_limit >= 0", name="ai_provider_retry_nonnegative"),
        sa.CheckConstraint("validation_status IN ('NOT_TESTED','PASSED','FAILED')", name="ai_provider_validation_status_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_providers"),
        sa.UniqueConstraint("provider_key", name="uq_ai_providers_provider_key"),
    )
    op.create_index("ix_ai_providers_enabled", "ai_providers", ["enabled"])

    op.create_table(
        "ai_models",
        sa.Column("provider_id", UUID, nullable=False),
        sa.Column("model_key", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("capabilities", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("input_price_per_million", MONEY, nullable=True),
        sa.Column("output_price_per_million", MONEY, nullable=True),
        sa.Column("embedding_price_per_million", MONEY, nullable=True),
        sa.Column("pricing_version", sa.String(100), server_default=sa.text("'unpriced-v1'"), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("id", UUID, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("context_window IS NULL OR context_window > 0", name="ai_model_context_positive"),
        sa.CheckConstraint("dimensions IS NULL OR dimensions > 0", name="ai_model_dimensions_positive"),
        sa.CheckConstraint("input_price_per_million IS NULL OR input_price_per_million >= 0", name="ai_model_input_price_nonnegative"),
        sa.CheckConstraint("output_price_per_million IS NULL OR output_price_per_million >= 0", name="ai_model_output_price_nonnegative"),
        sa.CheckConstraint("embedding_price_per_million IS NULL OR embedding_price_per_million >= 0", name="ai_model_embedding_price_nonnegative"),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_providers.id"], name="fk_ai_models_provider_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_models"),
        sa.UniqueConstraint("provider_id", "model_key", name="uq_ai_models_provider_model_key"),
    )
    op.create_index("ix_ai_models_provider_id", "ai_models", ["provider_id"])
    op.create_index("ix_ai_models_provider_enabled", "ai_models", ["provider_id", "enabled"])

    op.create_table(
        "ai_task_routes",
        sa.Column("task_key", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("primary_model_id", UUID, nullable=True),
        sa.Column("fallback_model_ids", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("retry_limit", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("budget_policy", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("id", UUID, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("version >= 1", name="ai_route_version_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ai_route_timeout_positive"),
        sa.CheckConstraint("retry_limit >= 0", name="ai_route_retry_nonnegative"),
        sa.ForeignKeyConstraint(["primary_model_id"], ["ai_models.id"], name="fk_ai_task_routes_primary_model_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_task_routes"),
        sa.UniqueConstraint("task_key", "version", name="uq_ai_task_routes_task_version"),
    )
    op.create_index("ix_ai_task_routes_primary_model_id", "ai_task_routes", ["primary_model_id"])
    op.create_index("ix_ai_task_routes_enabled", "ai_task_routes", ["enabled", "task_key"])
    op.create_index(
        "uq_ai_task_routes_active_task",
        "ai_task_routes",
        ["task_key"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "ai_budgets",
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("daily_cost_limit", MONEY, nullable=True),
        sa.Column("monthly_cost_limit", MONEY, nullable=True),
        sa.Column("daily_token_limit", sa.Integer(), nullable=True),
        sa.Column("unknown_usage_policy", sa.String(20), server_default=sa.text("'block'"), nullable=False),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("id", UUID, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("scope_type IN ('global','task','provider')", name="ai_budget_scope_valid"),
        sa.CheckConstraint("daily_cost_limit IS NULL OR daily_cost_limit >= 0", name="ai_budget_daily_cost_nonnegative"),
        sa.CheckConstraint("monthly_cost_limit IS NULL OR monthly_cost_limit >= 0", name="ai_budget_monthly_cost_nonnegative"),
        sa.CheckConstraint("daily_token_limit IS NULL OR daily_token_limit >= 0", name="ai_budget_daily_tokens_nonnegative"),
        sa.CheckConstraint("unknown_usage_policy IN ('block','allow_once')", name="ai_budget_unknown_policy_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_budgets"),
        sa.UniqueConstraint("scope_type", "scope_key", name="uq_ai_budgets_scope"),
    )
    op.create_index("ix_ai_budgets_enabled_scope", "ai_budgets", ["enabled", "scope_type"])

    op.create_table(
        "ai_budget_usages",
        sa.Column("budget_id", UUID, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("reserved_cost", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("settled_cost", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("settled_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unknown_usage_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_reservations", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("reserved_cost >= 0", name="ai_budget_usage_reserved_cost_nonnegative"),
        sa.CheckConstraint("settled_cost >= 0", name="ai_budget_usage_settled_cost_nonnegative"),
        sa.CheckConstraint("reserved_tokens >= 0", name="ai_budget_usage_reserved_tokens_nonnegative"),
        sa.CheckConstraint("settled_tokens >= 0", name="ai_budget_usage_settled_tokens_nonnegative"),
        sa.CheckConstraint("unknown_usage_count >= 0", name="ai_budget_usage_unknown_nonnegative"),
        sa.CheckConstraint("active_reservations >= 0", name="ai_budget_usage_active_nonnegative"),
        sa.CheckConstraint("version >= 0", name="ai_budget_usage_version_nonnegative"),
        sa.ForeignKeyConstraint(["budget_id"], ["ai_budgets.id"], name="fk_ai_budget_usages_budget_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_budget_usages"),
        sa.UniqueConstraint("budget_id", "usage_date", name="uq_ai_budget_usages_budget_date"),
    )
    op.create_index("ix_ai_budget_usages_budget_id", "ai_budget_usages", ["budget_id"])
    op.create_index("ix_ai_budget_usages_date", "ai_budget_usages", ["usage_date"])

    op.create_table(
        "ai_invocations",
        sa.Column("task_key", sa.String(100), nullable=False),
        sa.Column("route_id", UUID, nullable=True),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("schema_version", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", MONEY, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fallback_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("subject_type", sa.String(100), nullable=True),
        sa.Column("subject_id", sa.String(255), nullable=True),
        sa.Column("pricing_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("route_version >= 1", name="ai_invocation_route_version_positive"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ai_invocation_input_tokens_nonnegative"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ai_invocation_output_tokens_nonnegative"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ai_invocation_total_tokens_nonnegative"),
        sa.CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ai_invocation_cost_nonnegative"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ai_invocation_latency_nonnegative"),
        sa.CheckConstraint("retry_count >= 0", name="ai_invocation_retry_nonnegative"),
        sa.CheckConstraint("fallback_index >= 0", name="ai_invocation_fallback_nonnegative"),
        sa.ForeignKeyConstraint(["route_id"], ["ai_task_routes.id"], name="fk_ai_invocations_route_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_invocations"),
    )
    op.create_index("ix_ai_invocations_route_id", "ai_invocations", ["route_id"])
    op.create_index("ix_ai_invocations_task_started", "ai_invocations", ["task_key", "started_at"])
    op.create_index("ix_ai_invocations_status_started", "ai_invocations", ["status", "started_at"])

    op.create_table(
        "ai_invocation_attempts",
        sa.Column("invocation_id", UUID, nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("retry_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fallback_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", MONEY, nullable=True),
        sa.Column("pricing_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("attempt_no >= 1", name="ai_attempt_no_positive"),
        sa.CheckConstraint("retry_index >= 0", name="ai_attempt_retry_nonnegative"),
        sa.CheckConstraint("fallback_index >= 0", name="ai_attempt_fallback_nonnegative"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ai_attempt_input_tokens_nonnegative"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ai_attempt_output_tokens_nonnegative"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ai_attempt_total_tokens_nonnegative"),
        sa.CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ai_attempt_cost_nonnegative"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ai_attempt_latency_nonnegative"),
        sa.ForeignKeyConstraint(["invocation_id"], ["ai_invocations.id"], name="fk_ai_invocation_attempts_invocation_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_invocation_attempts"),
        sa.UniqueConstraint("invocation_id", "attempt_no", name="uq_ai_invocation_attempts_no"),
    )
    op.create_index("ix_ai_invocation_attempts_invocation_id", "ai_invocation_attempts", ["invocation_id"])
    op.create_index("ix_ai_invocation_attempts_invocation", "ai_invocation_attempts", ["invocation_id", "attempt_no"])

    route_table = sa.table(
        "ai_task_routes",
        sa.column("id", UUID),
        sa.column("task_key", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("fallback_model_ids", JSONB),
        sa.column("timeout_seconds", sa.Integer()),
        sa.column("retry_limit", sa.Integer()),
        sa.column("budget_policy", JSONB),
        sa.column("config", JSONB),
        sa.column("enabled", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by", sa.String()),
    )
    for task_key in (
        "embedding",
        "event_boundary_review",
        "evidence_extraction",
        "editorial_scoring",
        "draft_generation",
        "final_review",
    ):
        op.bulk_insert(
            route_table,
            [{
                "id": uuid4(),
                "task_key": task_key,
                "version": 1,
                "fallback_model_ids": [],
                "timeout_seconds": 30,
                "retry_limit": 1,
                "budget_policy": {},
                "config": {},
                "enabled": False,
                "is_active": True,
                "created_by": "migration:m4a",
            }],
        )


def downgrade() -> None:
    op.drop_index("ix_ai_invocation_attempts_invocation", table_name="ai_invocation_attempts")
    op.drop_index("ix_ai_invocation_attempts_invocation_id", table_name="ai_invocation_attempts")
    op.drop_table("ai_invocation_attempts")
    op.drop_index("ix_ai_invocations_status_started", table_name="ai_invocations")
    op.drop_index("ix_ai_invocations_task_started", table_name="ai_invocations")
    op.drop_index("ix_ai_invocations_route_id", table_name="ai_invocations")
    op.drop_table("ai_invocations")
    op.drop_index("ix_ai_budget_usages_date", table_name="ai_budget_usages")
    op.drop_index("ix_ai_budget_usages_budget_id", table_name="ai_budget_usages")
    op.drop_table("ai_budget_usages")
    op.drop_index("ix_ai_budgets_enabled_scope", table_name="ai_budgets")
    op.drop_table("ai_budgets")
    op.drop_index("uq_ai_task_routes_active_task", table_name="ai_task_routes")
    op.drop_index("ix_ai_task_routes_enabled", table_name="ai_task_routes")
    op.drop_index("ix_ai_task_routes_primary_model_id", table_name="ai_task_routes")
    op.drop_table("ai_task_routes")
    op.drop_index("ix_ai_models_provider_enabled", table_name="ai_models")
    op.drop_index("ix_ai_models_provider_id", table_name="ai_models")
    op.drop_table("ai_models")
    op.drop_index("ix_ai_providers_enabled", table_name="ai_providers")
    op.drop_table("ai_providers")
