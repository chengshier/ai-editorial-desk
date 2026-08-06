"""Create M1-A connector persistence and risk tables.

Revision ID: 20260806_0001
Revises:
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
UUID = postgresql.UUID(as_uuid=True)
JSON_OBJECT_DEFAULT = sa.text("'{}'::jsonb")

ACCOUNT_STATUS = sa.Enum(
    "healthy",
    "warning",
    "cooldown",
    "review_required",
    "restricted",
    "disabled",
    name="account_status",
    native_enum=False,
    create_constraint=True,
    length=15,
)
RUN_STATUS = sa.Enum(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "paused_risk",
    "partial",
    name="connector_run_status",
    native_enum=False,
    create_constraint=True,
    length=11,
)
RISK_ACTION = sa.Enum(
    "retry",
    "stop_task",
    "pause_account",
    "pause_platform",
    "require_review",
    name="risk_action",
    native_enum=False,
    create_constraint=True,
    length=14,
)


def uuid_primary_key() -> sa.Column[object]:
    return sa.Column("id", UUID, nullable=False)


def created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def updated_at() -> sa.Column[object]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def json_object(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(
        name,
        JSONB,
        server_default=None if nullable else JSON_OBJECT_DEFAULT,
        nullable=nullable,
    )


def create_index(table: str, name: str, *columns: str) -> None:
    op.create_index(name, table, list(columns), unique=False)


def upgrade() -> None:
    op.create_table(
        "connector_definitions",
        sa.Column("connector_type", sa.String(100), nullable=False),
        sa.Column("platform", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        json_object("capabilities"),
        json_object("config_schema"),
        json_object("ui_schema"),
        sa.Column("implementation_version", sa.String(64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        uuid_primary_key(),
        created_at(),
        updated_at(),
        sa.PrimaryKeyConstraint("id", name="pk_connector_definitions"),
        sa.UniqueConstraint(
            "connector_type",
            "platform",
            name="uq_connector_definitions_type_platform",
        ),
    )
    create_index("connector_definitions", "ix_connector_definitions_enabled", "is_enabled")

    op.create_table(
        "connector_instances",
        sa.Column("definition_id", UUID, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            server_default=sa.text("'configured'"),
            nullable=False,
        ),
        json_object("config"),
        json_object("schedule_config"),
        sa.Column("credential_ref", sa.String(500), nullable=True),
        sa.Column("config_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        uuid_primary_key(),
        created_at(),
        updated_at(),
        sa.CheckConstraint(
            "config_version >= 1",
            name="ck_connector_instances_config_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["connector_definitions.id"],
            name="fk_connector_instances_definition_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connector_instances"),
        sa.UniqueConstraint(
            "definition_id",
            "name",
            name="uq_connector_instances_definition_name",
        ),
    )
    create_index(
        "connector_instances",
        "ix_connector_instances_definition_id",
        "definition_id",
    )
    create_index(
        "connector_instances",
        "ix_connector_instances_enabled_status",
        "enabled",
        "status",
    )

    op.create_table(
        "platform_accounts",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("platform", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("account_identifier", sa.String(255), nullable=False),
        sa.Column("credential_ref", sa.String(500), nullable=True),
        sa.Column("browser_profile_ref", sa.String(500), nullable=True),
        sa.Column(
            "status",
            ACCOUNT_STATUS,
            server_default=sa.text("'healthy'"),
            nullable=False,
        ),
        sa.Column(
            "risk_level",
            sa.String(50),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_warning_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_warning_code", sa.String(100), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "manual_review_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "daily_request_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "daily_item_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "daily_comment_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        uuid_primary_key(),
        created_at(),
        updated_at(),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_platform_accounts_consecutive_failures_nonnegative",
        ),
        sa.CheckConstraint(
            "daily_request_count >= 0",
            name="ck_platform_accounts_daily_request_count_nonnegative",
        ),
        sa.CheckConstraint(
            "daily_item_count >= 0",
            name="ck_platform_accounts_daily_item_count_nonnegative",
        ),
        sa.CheckConstraint(
            "daily_comment_count >= 0",
            name="ck_platform_accounts_daily_comment_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["connector_instance_id"],
            ["connector_instances.id"],
            name="fk_platform_accounts_connector_instance_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_accounts"),
        sa.UniqueConstraint(
            "connector_instance_id",
            "platform",
            "account_identifier",
            name="uq_platform_accounts_instance_platform_identifier",
        ),
    )
    create_index(
        "platform_accounts",
        "ix_platform_accounts_connector_instance_id",
        "connector_instance_id",
    )
    create_index(
        "platform_accounts",
        "ix_platform_accounts_platform_status",
        "platform",
        "status",
    )
    create_index(
        "platform_accounts",
        "ix_platform_accounts_review",
        "manual_review_required",
        "cooldown_until",
    )

    op.create_table(
        "connector_runs",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("platform_account_id", UUID, nullable=True),
        sa.Column("mode", sa.String(100), nullable=False),
        sa.Column("status", RUN_STATUS, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_limit", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("collected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("inserted_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        json_object("checkpoint_before", nullable=True),
        json_object("checkpoint_after", nullable=True),
        json_object("metadata"),
        uuid_primary_key(),
        created_at(),
        sa.CheckConstraint(
            "requested_limit >= 0",
            name="ck_connector_runs_requested_limit_nonnegative",
        ),
        sa.CheckConstraint(
            "collected_count >= 0",
            name="ck_connector_runs_collected_count_nonnegative",
        ),
        sa.CheckConstraint(
            "inserted_count >= 0",
            name="ck_connector_runs_inserted_count_nonnegative",
        ),
        sa.CheckConstraint(
            "duplicate_count >= 0",
            name="ck_connector_runs_duplicate_count_nonnegative",
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name="ck_connector_runs_retry_count_nonnegative",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_connector_runs_finished_after_started",
        ),
        sa.ForeignKeyConstraint(
            ["connector_instance_id"],
            ["connector_instances.id"],
            name="fk_connector_runs_connector_instance_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_account_id"],
            ["platform_accounts.id"],
            name="fk_connector_runs_platform_account_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connector_runs"),
    )
    create_index(
        "connector_runs",
        "ix_connector_runs_connector_instance_id",
        "connector_instance_id",
    )
    create_index(
        "connector_runs",
        "ix_connector_runs_platform_account_id",
        "platform_account_id",
    )
    create_index(
        "connector_runs",
        "ix_connector_runs_instance_created",
        "connector_instance_id",
        "created_at",
    )
    create_index(
        "connector_runs",
        "ix_connector_runs_status_started",
        "status",
        "started_at",
    )

    op.create_table(
        "connector_checkpoints",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("platform_account_id", UUID, nullable=True),
        sa.Column("mode", sa.String(100), nullable=False),
        sa.Column("scope_key", sa.String(500), nullable=False),
        json_object("cursor", nullable=True),
        sa.Column("watermark", sa.String(500), nullable=True),
        sa.Column("last_external_id", sa.String(500), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        json_object("checkpoint_data"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        uuid_primary_key(),
        updated_at(),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_connector_checkpoints_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["connector_instance_id"],
            ["connector_instances.id"],
            name="fk_connector_checkpoints_connector_instance_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_account_id"],
            ["platform_accounts.id"],
            name="fk_connector_checkpoints_platform_account_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connector_checkpoints"),
        sa.UniqueConstraint(
            "connector_instance_id",
            "platform_account_id",
            "mode",
            "scope_key",
            name="uq_connector_checkpoints_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )
    create_index(
        "connector_checkpoints",
        "ix_connector_checkpoints_connector_instance_id",
        "connector_instance_id",
    )
    create_index(
        "connector_checkpoints",
        "ix_connector_checkpoints_platform_account_id",
        "platform_account_id",
    )
    create_index(
        "connector_checkpoints",
        "ix_connector_checkpoints_instance_updated",
        "connector_instance_id",
        "updated_at",
    )

    op.create_table(
        "platform_risk_events",
        sa.Column("connector_instance_id", UUID, nullable=False),
        sa.Column("platform_account_id", UUID, nullable=True),
        sa.Column("connector_run_id", UUID, nullable=True),
        sa.Column("platform", sa.String(100), nullable=False),
        sa.Column("risk_type", sa.String(100), nullable=False),
        sa.Column("risk_level", sa.String(50), nullable=False),
        sa.Column("raw_error_code", sa.String(100), nullable=True),
        sa.Column("standard_error_code", sa.String(100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("action_taken", RISK_ACTION, nullable=False),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        json_object("request_context"),
        json_object("response_context"),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "manual_review_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        uuid_primary_key(),
        created_at(),
        sa.ForeignKeyConstraint(
            ["connector_instance_id"],
            ["connector_instances.id"],
            name="fk_platform_risk_events_connector_instance_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_account_id"],
            ["platform_accounts.id"],
            name="fk_platform_risk_events_platform_account_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connector_run_id"],
            ["connector_runs.id"],
            name="fk_platform_risk_events_connector_run_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_risk_events"),
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_connector_instance_id",
        "connector_instance_id",
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_platform_account_id",
        "platform_account_id",
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_connector_run_id",
        "connector_run_id",
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_account_occurred",
        "platform_account_id",
        "occurred_at",
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_platform_level",
        "platform",
        "risk_level",
    )
    create_index(
        "platform_risk_events",
        "ix_platform_risk_events_unresolved",
        "resolved_at",
        "manual_review_required",
    )


def downgrade() -> None:
    op.drop_table("platform_risk_events")
    op.drop_table("connector_checkpoints")
    op.drop_table("connector_runs")
    op.drop_table("platform_accounts")
    op.drop_table("connector_instances")
    op.drop_table("connector_definitions")
