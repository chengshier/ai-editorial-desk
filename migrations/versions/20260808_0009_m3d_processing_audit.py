# ruff: noqa: E501
"""Add M3-D clustering processing and assignment provenance audit.

Revision ID: 20260808_0009
Revises: 20260808_0008
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0009"
down_revision: str | None = "20260808_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "clustering_processing_runs",
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=9), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.String(length=100), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("counters", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("config_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('evaluate', 'dry_run', 'apply')",
            name="clustering_processing_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="clustering_processing_status",
        ),
        sa.CheckConstraint(
            "char_length(algorithm_version) > 0",
            name="processing_algorithm_version_nonempty",
        ),
        sa.CheckConstraint(
            "requested_count >= 0",
            name="processing_requested_count_nonnegative",
        ),
        sa.CheckConstraint(
            "processed_count >= 0",
            name="processing_processed_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clustering_processing_runs"),
    )
    op.create_index(
        "ix_clustering_processing_runs_algorithm_version",
        "clustering_processing_runs",
        ["algorithm_version"],
    )
    op.create_index(
        "ix_clustering_processing_runs_status_started",
        "clustering_processing_runs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_clustering_processing_runs_algorithm_started",
        "clustering_processing_runs",
        ["algorithm_version", "started_at"],
    )

    op.create_table(
        "event_assignment_records",
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("attached_by", sa.String(length=9), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("match_decision_id", UUID, nullable=True),
        sa.Column("processing_run_id", UUID, nullable=True),
        sa.Column("previous_event_id", UUID, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('create_event', 'attach', 'move', 'detach', 'conflict')",
            name="event_assignment_action",
        ),
        sa.CheckConstraint(
            "attached_by IN ('rule', 'embedding', 'llm', 'human')",
            name="event_assignment_attached_by",
        ),
        sa.CheckConstraint(
            "char_length(algorithm_version) > 0",
            name="assignment_algorithm_version_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["raw_signals.id"],
            name="fk_event_assignment_records_signal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_event_assignment_records_event_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_decision_id"],
            ["signal_match_decisions.id"],
            name="fk_event_assignment_records_match_decision_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["clustering_processing_runs.id"],
            name="fk_event_assignment_records_processing_run_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_event_id"],
            ["events.id"],
            name="fk_event_assignment_records_previous_event_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_assignment_records"),
    )
    op.create_index(
        "ix_event_assignment_records_signal_created",
        "event_assignment_records",
        ["signal_id", "created_at"],
    )
    op.create_index(
        "ix_event_assignment_records_event_created",
        "event_assignment_records",
        ["event_id", "created_at"],
    )
    op.create_index(
        "ix_event_assignment_records_algorithm_created",
        "event_assignment_records",
        ["algorithm_version", "created_at"],
    )
    op.create_index(
        "ix_event_assignment_records_run_created",
        "event_assignment_records",
        ["processing_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_assignment_records_run_created", table_name="event_assignment_records")
    op.drop_index("ix_event_assignment_records_algorithm_created", table_name="event_assignment_records")
    op.drop_index("ix_event_assignment_records_event_created", table_name="event_assignment_records")
    op.drop_index("ix_event_assignment_records_signal_created", table_name="event_assignment_records")
    op.drop_table("event_assignment_records")

    op.drop_index(
        "ix_clustering_processing_runs_algorithm_started",
        table_name="clustering_processing_runs",
    )
    op.drop_index(
        "ix_clustering_processing_runs_status_started",
        table_name="clustering_processing_runs",
    )
    op.drop_index(
        "ix_clustering_processing_runs_algorithm_version",
        table_name="clustering_processing_runs",
    )
    op.drop_table("clustering_processing_runs")
