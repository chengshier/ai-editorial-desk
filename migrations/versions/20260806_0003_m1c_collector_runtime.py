# ruff: noqa: E501
"""Add M1-C sources, raw signals, budgets, and collector runtime fields.

Revision ID: 20260806_0003
Revises: 20260806_0002
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0003"
down_revision: str | None = "20260806_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)
JSON_OBJECT_DEFAULT = sa.text("'{}'::jsonb")
JSON_ARRAY_DEFAULT = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("mode", sa.String(length=100), nullable=False),
        sa.Column("scope_key", sa.String(length=500), nullable=False),
        sa.Column("external_ref", sa.String(length=2000)),
        sa.Column("config", JSONB, server_default=JSON_OBJECT_DEFAULT, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'active'"), nullable=False),
        sa.Column("last_collected_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=100)),
        sa.Column("updated_by", sa.String(length=255)),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], name="fk_sources_connector_instance_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("connector_instance_id", "mode", "scope_key", name="uq_sources_instance_mode_scope"),
    )
    op.create_index("ix_sources_connector_instance_id", "sources", ["connector_instance_id"])
    op.create_index("ix_sources_instance_enabled", "sources", ["connector_instance_id", "enabled", "status"])
    op.create_index("ix_sources_type_status", "sources", ["source_type", "status"])

    op.add_column("connector_runs", sa.Column("source_id", UUID))
    op.add_column("connector_runs", sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.create_foreign_key("fk_connector_runs_source_id", "connector_runs", "sources", ["source_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_connector_runs_failed_count_nonnegative", "connector_runs", "failed_count >= 0")
    op.create_index("ix_connector_runs_source_id", "connector_runs", ["source_id"])
    op.create_index("ix_connector_runs_source_created", "connector_runs", ["source_id", "created_at"])

    op.create_table(
        "raw_signals",
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("connector_run_id", UUID),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=500)),
        sa.Column("original_url", sa.String(length=4000), nullable=False),
        sa.Column("canonical_url", sa.String(length=4000), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("text", sa.Text()),
        sa.Column("author_id", sa.String(length=500)),
        sa.Column("author_name", sa.String(length=500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("metrics", JSONB, server_default=JSON_OBJECT_DEFAULT, nullable=False),
        sa.Column("media", JSONB, server_default=JSON_ARRAY_DEFAULT, nullable=False),
        sa.Column("raw_payload", JSONB, server_default=JSON_OBJECT_DEFAULT, nullable=False),
        sa.Column("language", sa.String(length=32)),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=1000), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_raw_signals_content_hash_sha256"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_raw_signals_source_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], name="fk_raw_signals_connector_instance_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["connector_run_id"], ["connector_runs.id"], name="fk_raw_signals_connector_run_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_raw_signals"),
        sa.UniqueConstraint("idempotency_key", name="uq_raw_signals_idempotency_key"),
    )
    op.create_index("ix_raw_signals_source_id", "raw_signals", ["source_id"])
    op.create_index("ix_raw_signals_connector_instance_id", "raw_signals", ["connector_instance_id"])
    op.create_index("ix_raw_signals_connector_run_id", "raw_signals", ["connector_run_id"])
    op.create_index("ix_raw_signals_source_published", "raw_signals", ["source_id", "published_at"])
    op.create_index("ix_raw_signals_platform_published", "raw_signals", ["platform", "published_at"])
    op.create_index("ix_raw_signals_run_created", "raw_signals", ["connector_run_id", "created_at"])

    op.create_table(
        "collection_budgets",
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("scope_key", sa.String(length=500), nullable=False),
        sa.Column("max_runs_per_day", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("max_items_per_run", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("max_items_per_day", sa.Integer(), server_default=sa.text("5000"), nullable=False),
        sa.Column("max_comments_per_run", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_comments_per_day", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default=sa.text("'Asia/Shanghai'"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_by", sa.String(length=255)),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("max_runs_per_day >= 1", name="ck_collection_budgets_max_runs_per_day_positive"),
        sa.CheckConstraint("max_items_per_run >= 1", name="ck_collection_budgets_max_items_per_run_positive"),
        sa.CheckConstraint("max_items_per_day >= 1", name="ck_collection_budgets_max_items_per_day_positive"),
        sa.CheckConstraint("max_comments_per_run >= 0", name="ck_collection_budgets_max_comments_per_run_nonnegative"),
        sa.CheckConstraint("max_comments_per_day >= 0", name="ck_collection_budgets_max_comments_per_day_nonnegative"),
        sa.CheckConstraint("max_concurrency >= 1", name="ck_collection_budgets_max_concurrency_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_collection_budgets"),
        sa.UniqueConstraint("scope_type", "scope_key", name="uq_collection_budgets_scope"),
    )
    op.create_index("ix_collection_budgets_enabled_scope", "collection_budgets", ["enabled", "scope_type"])

    op.create_table(
        "collection_budget_usage",
        sa.Column("budget_id", UUID, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("runs_reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("runs_completed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("comments_reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("comments_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("runs_reserved >= 0", name="ck_collection_budget_usage_runs_reserved_nonnegative"),
        sa.CheckConstraint("runs_completed >= 0", name="ck_collection_budget_usage_runs_completed_nonnegative"),
        sa.CheckConstraint("items_reserved >= 0", name="ck_collection_budget_usage_items_reserved_nonnegative"),
        sa.CheckConstraint("items_used >= 0", name="ck_collection_budget_usage_items_used_nonnegative"),
        sa.CheckConstraint("comments_reserved >= 0", name="ck_collection_budget_usage_comments_reserved_nonnegative"),
        sa.CheckConstraint("comments_used >= 0", name="ck_collection_budget_usage_comments_used_nonnegative"),
        sa.CheckConstraint("active_runs >= 0", name="ck_collection_budget_usage_active_runs_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_collection_budget_usage_budget_usage_version_positive"),
        sa.ForeignKeyConstraint(["budget_id"], ["collection_budgets.id"], name="fk_collection_budget_usage_budget_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_collection_budget_usage"),
        sa.UniqueConstraint("budget_id", "usage_date", name="uq_collection_budget_usage_day"),
    )
    op.create_index("ix_collection_budget_usage_budget_id", "collection_budget_usage", ["budget_id"])
    op.create_index("ix_collection_budget_usage_date", "collection_budget_usage", ["usage_date"])


def downgrade() -> None:
    op.drop_index("ix_collection_budget_usage_date", table_name="collection_budget_usage")
    op.drop_index("ix_collection_budget_usage_budget_id", table_name="collection_budget_usage")
    op.drop_table("collection_budget_usage")
    op.drop_index("ix_collection_budgets_enabled_scope", table_name="collection_budgets")
    op.drop_table("collection_budgets")
    for name in (
        "ix_raw_signals_run_created",
        "ix_raw_signals_platform_published",
        "ix_raw_signals_source_published",
        "ix_raw_signals_connector_run_id",
        "ix_raw_signals_connector_instance_id",
        "ix_raw_signals_source_id",
    ):
        op.drop_index(name, table_name="raw_signals")
    op.drop_table("raw_signals")
    op.drop_index("ix_connector_runs_source_created", table_name="connector_runs")
    op.drop_index("ix_connector_runs_source_id", table_name="connector_runs")
    op.drop_constraint("ck_connector_runs_failed_count_nonnegative", "connector_runs", type_="check")
    op.drop_constraint("fk_connector_runs_source_id", "connector_runs", type_="foreignkey")
    op.drop_column("connector_runs", "failed_count")
    op.drop_column("connector_runs", "source_id")
    op.drop_index("ix_sources_type_status", table_name="sources")
    op.drop_index("ix_sources_instance_enabled", table_name="sources")
    op.drop_index("ix_sources_connector_instance_id", table_name="sources")
    op.drop_table("sources")
