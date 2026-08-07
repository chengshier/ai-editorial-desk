# ruff: noqa: E501
"""Add M1-D scheduler, validation, run debug, and checkpoint source fields.

Revision ID: 20260807_0004
Revises: 20260806_0003
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0004"
down_revision: str | None = "20260806_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("connector_runs", sa.Column("parent_run_id", UUID))
    op.add_column(
        "connector_runs",
        sa.Column("trigger_type", sa.String(length=9), server_default=sa.text("'manual'"), nullable=False),
    )
    op.add_column("connector_runs", sa.Column("progress_updated_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_connector_runs_parent_run_id",
        "connector_runs",
        "connector_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_connector_runs_connector_run_trigger_type",
        "connector_runs",
        "trigger_type IN ('manual', 'test', 'scheduled', 'retry')",
    )
    op.create_index("ix_connector_runs_parent", "connector_runs", ["parent_run_id"])

    op.add_column("connector_checkpoints", sa.Column("source_id", UUID))
    op.create_foreign_key(
        "fk_connector_checkpoints_source_id",
        "connector_checkpoints",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_connector_checkpoints_source_id", "connector_checkpoints", ["source_id"])
    op.create_index(
        "ix_connector_checkpoints_source_updated",
        "connector_checkpoints",
        ["source_id", "updated_at"],
    )

    op.create_table(
        "collection_schedules",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("platform_account_id", UUID),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("schedule_type", sa.String(length=8), nullable=False),
        sa.Column("interval_seconds", sa.Integer()),
        sa.Column("cron_expression", sa.String(length=200)),
        sa.Column("timezone", sa.String(length=100), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_id", UUID),
        sa.Column("lease_owner", sa.String(length=255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("paused_reason", sa.String(length=500)),
        sa.Column("updated_by", sa.String(length=255)),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("schedule_type IN ('interval', 'cron')", name="ck_collection_schedules_collection_schedule_type"),
        sa.CheckConstraint("requested_limit >= 1", name="ck_collection_schedules_requested_limit_positive"),
        sa.CheckConstraint("interval_seconds IS NULL OR interval_seconds >= 300", name="ck_collection_schedules_interval_minimum_five_minutes"),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_collection_schedules_consecutive_failures_nonnegative"),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], name="fk_collection_schedules_connector_instance_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_collection_schedules_source_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"], name="fk_collection_schedules_platform_account_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_run_id"], ["connector_runs.id"], name="fk_collection_schedules_last_run_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_collection_schedules"),
        sa.UniqueConstraint("source_id", "name", name="uq_collection_schedules_source_name"),
    )
    op.create_index("ix_collection_schedules_connector_instance_id", "collection_schedules", ["connector_instance_id"])
    op.create_index("ix_collection_schedules_source_id", "collection_schedules", ["source_id"])
    op.create_index("ix_collection_schedules_platform_account_id", "collection_schedules", ["platform_account_id"])
    op.create_index("ix_collection_schedules_last_run_id", "collection_schedules", ["last_run_id"])
    op.create_index("ix_collection_schedules_due", "collection_schedules", ["enabled", "next_run_at"])
    op.create_index("ix_collection_schedules_lease", "collection_schedules", ["lease_expires_at"])

    op.create_table(
        "collection_schedule_triggers",
        sa.Column("schedule_id", UUID, nullable=False),
        sa.Column("scheduled_for_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=13), server_default=sa.text("'claimed'"), nullable=False),
        sa.Column("lease_owner", sa.String(length=255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("run_id", UUID),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('claimed', 'running', 'succeeded', 'failed', 'paused_review')", name="ck_collection_schedule_triggers_collection_schedule_trigger_status"),
        sa.ForeignKeyConstraint(["schedule_id"], ["collection_schedules.id"], name="fk_collection_schedule_triggers_schedule_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["connector_runs.id"], name="fk_collection_schedule_triggers_run_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_collection_schedule_triggers"),
        sa.UniqueConstraint("schedule_id", "scheduled_for_at", name="uq_collection_schedule_triggers_slot"),
    )
    op.create_index("ix_collection_schedule_triggers_schedule_id", "collection_schedule_triggers", ["schedule_id"])
    op.create_index("ix_collection_schedule_triggers_run_id", "collection_schedule_triggers", ["run_id"])
    op.create_index("ix_collection_schedule_triggers_lease", "collection_schedule_triggers", ["status", "lease_expires_at"])

    op.create_table(
        "scheduler_instances",
        sa.Column("instance_key", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recent_trigger_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("recent_trigger_failures >= 0", name="ck_scheduler_instances_recent_trigger_failures_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_scheduler_instances"),
        sa.UniqueConstraint("instance_key", name="uq_scheduler_instances_instance_key"),
    )
    op.create_index("ix_scheduler_instances_heartbeat", "scheduler_instances", ["last_heartbeat"])

    op.create_table(
        "connector_validation_records",
        sa.Column("connector_type", sa.String(length=100), nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("implementation_version", sa.String(length=100), nullable=False),
        sa.Column("environment", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("validated_by", sa.String(length=255)),
        sa.Column("notes", sa.Text()),
        sa.Column("safe_evidence", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('not_tested', 'passed', 'failed', 'expired')", name="ck_connector_validation_records_connector_validation_status"),
        sa.PrimaryKeyConstraint("id", name="pk_connector_validation_records"),
    )
    op.create_index(
        "ix_connector_validation_lookup",
        "connector_validation_records",
        ["connector_type", "platform", "environment", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_validation_lookup", table_name="connector_validation_records")
    op.drop_table("connector_validation_records")
    op.drop_index("ix_scheduler_instances_heartbeat", table_name="scheduler_instances")
    op.drop_table("scheduler_instances")
    op.drop_index("ix_collection_schedule_triggers_lease", table_name="collection_schedule_triggers")
    op.drop_index("ix_collection_schedule_triggers_run_id", table_name="collection_schedule_triggers")
    op.drop_index("ix_collection_schedule_triggers_schedule_id", table_name="collection_schedule_triggers")
    op.drop_table("collection_schedule_triggers")
    op.drop_index("ix_collection_schedules_lease", table_name="collection_schedules")
    op.drop_index("ix_collection_schedules_due", table_name="collection_schedules")
    op.drop_index("ix_collection_schedules_last_run_id", table_name="collection_schedules")
    op.drop_index("ix_collection_schedules_platform_account_id", table_name="collection_schedules")
    op.drop_index("ix_collection_schedules_source_id", table_name="collection_schedules")
    op.drop_index("ix_collection_schedules_connector_instance_id", table_name="collection_schedules")
    op.drop_table("collection_schedules")
    op.drop_index("ix_connector_checkpoints_source_updated", table_name="connector_checkpoints")
    op.drop_index("ix_connector_checkpoints_source_id", table_name="connector_checkpoints")
    op.drop_constraint("fk_connector_checkpoints_source_id", "connector_checkpoints", type_="foreignkey")
    op.drop_column("connector_checkpoints", "source_id")
    op.drop_index("ix_connector_runs_parent", table_name="connector_runs")
    op.drop_constraint("ck_connector_runs_connector_run_trigger_type", "connector_runs", type_="check")
    op.drop_constraint("fk_connector_runs_parent_run_id", "connector_runs", type_="foreignkey")
    op.drop_column("connector_runs", "progress_updated_at")
    op.drop_column("connector_runs", "trigger_type")
    op.drop_column("connector_runs", "parent_run_id")
