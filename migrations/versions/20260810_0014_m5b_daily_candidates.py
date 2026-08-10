# ruff: noqa: E501
"""Add M5-B daily candidate snapshots and editorial decision history.

Revision ID: 20260810_0014
Revises: 20260809_0013
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0014"
down_revision: str | None = "20260809_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
FORMATS = "'daily_compilation','quick_explainer','fact_check','deep_dive','entertainment','consumer_safety'"
LIFECYCLE = "'emerging','growing','stable','declining','resolved'"
RISKS = "'R0','R1','R2','R3','R4'"


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "daily_candidate_runs",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ranking_version", sa.String(100), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("scanned_event_count", sa.Integer(), nullable=False),
        sa.Column("eligible_event_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("skipped_event_count", sa.Integer(), nullable=False),
        sa.Column("skip_summary", JSONB, nullable=False),
        sa.Column("mode", sa.String(5), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("window_end_at > window_start_at", name="candidate_run_window_valid"),
        sa.CheckConstraint("requested_limit > 0", name="candidate_run_limit_positive"),
        sa.CheckConstraint("scanned_event_count >= 0", name="candidate_run_scanned_nonnegative"),
        sa.CheckConstraint("eligible_event_count >= 0", name="candidate_run_eligible_nonnegative"),
        sa.CheckConstraint("candidate_count >= 0", name="candidate_run_candidate_nonnegative"),
        sa.CheckConstraint("skipped_event_count >= 0", name="candidate_run_skipped_nonnegative"),
        sa.CheckConstraint("char_length(btrim(timezone)) > 0", name="candidate_run_timezone_nonempty"),
        sa.CheckConstraint("char_length(btrim(ranking_version)) > 0", name="candidate_run_ranking_nonempty"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="candidate_run_input_hash_sha256"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="candidate_run_actor_nonempty"),
        sa.CheckConstraint("status IN ('succeeded','failed')", name="candidate_run_status"),
        sa.CheckConstraint("mode = 'apply'", name="candidate_run_mode"),
        sa.PrimaryKeyConstraint("id", name="pk_daily_candidate_runs"),
    )
    op.create_index("ix_daily_candidate_runs_business_asof", "daily_candidate_runs", ["business_date", "timezone", "as_of_at"])
    op.create_index("ix_daily_candidate_runs_status_created", "daily_candidate_runs", ["status", "created_at"])
    op.create_index(
        "uq_daily_candidate_runs_success_input",
        "daily_candidate_runs",
        ["input_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "daily_candidates",
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("candidate_group", sa.String(15), nullable=False),
        sa.Column("event_title_snapshot", sa.String(500), nullable=False),
        sa.Column("category_snapshot", sa.String(100), nullable=True),
        sa.Column("event_status_snapshot", sa.String(9), nullable=False),
        sa.Column("event_last_updated_at_snapshot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_count_snapshot", sa.Integer(), nullable=False),
        sa.Column("platform_count_snapshot", sa.Integer(), nullable=False),
        sa.Column("trend_snapshot_id", UUID, nullable=True),
        sa.Column("base_editorial_score_id", UUID, nullable=False),
        sa.Column("effective_assessment_hash", sa.String(64), nullable=False),
        sa.Column("effective_traffic_total", sa.Float(), nullable=False),
        sa.Column("effective_risk_level", sa.String(2), nullable=False),
        sa.Column("recommended_format", sa.String(32), nullable=False),
        sa.Column("open_unknown_count", sa.Integer(), nullable=False),
        sa.Column("evidence_summary", JSONB, nullable=False),
        sa.Column("ranking_components", JSONB, nullable=False),
        sa.Column("card_exists_snapshot", sa.Boolean(), nullable=False),
        sa.Column("draft_exists_snapshot", sa.Boolean(), nullable=False),
        sa.Column("candidate_context_hash", sa.String(64), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("rank > 0", name="daily_candidate_rank_positive"),
        sa.CheckConstraint("candidate_group IN ('normal','review_required')", name="daily_candidate_group"),
        sa.CheckConstraint(f"event_status_snapshot IN ({LIFECYCLE})", name="daily_candidate_event_status"),
        sa.CheckConstraint("effective_traffic_total >= 0 AND effective_traffic_total <= 100", name="daily_candidate_traffic_range"),
        sa.CheckConstraint(f"effective_risk_level IN ({RISKS})", name="daily_candidate_risk_level"),
        sa.CheckConstraint(f"recommended_format IN ({FORMATS})", name="daily_candidate_recommended_format"),
        sa.CheckConstraint("open_unknown_count >= 0", name="daily_candidate_unknown_nonnegative"),
        sa.CheckConstraint("source_count_snapshot >= 0", name="daily_candidate_source_nonnegative"),
        sa.CheckConstraint("platform_count_snapshot >= 0", name="daily_candidate_platform_nonnegative"),
        sa.CheckConstraint("char_length(effective_assessment_hash) = 64", name="daily_candidate_assessment_hash_sha256"),
        sa.CheckConstraint("char_length(candidate_context_hash) = 64", name="daily_candidate_context_hash_sha256"),
        sa.ForeignKeyConstraint(["run_id"], ["daily_candidate_runs.id"], name="fk_daily_candidates_run_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_daily_candidates_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trend_snapshot_id"], ["event_trend_snapshots.id"], name="fk_daily_candidates_trend_snapshot_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_editorial_score_id"], ["editorial_scores.id"], name="fk_daily_candidates_base_editorial_score_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_daily_candidates"),
        sa.UniqueConstraint("run_id", "event_id", name="uq_daily_candidates_run_event"),
        sa.UniqueConstraint("run_id", "rank", name="uq_daily_candidates_run_rank"),
    )
    op.create_index("ix_daily_candidates_run_id", "daily_candidates", ["run_id"])
    op.create_index("ix_daily_candidates_event_id", "daily_candidates", ["event_id"])
    op.create_index("ix_daily_candidates_trend_snapshot_id", "daily_candidates", ["trend_snapshot_id"])
    op.create_index("ix_daily_candidates_base_editorial_score_id", "daily_candidates", ["base_editorial_score_id"])
    op.create_index("ix_daily_candidates_event_created", "daily_candidates", ["event_id", "created_at"])
    op.create_index("ix_daily_candidates_run_group_rank", "daily_candidates", ["run_id", "candidate_group", "rank"])

    op.create_table(
        "editorial_decisions",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("candidate_id", UUID, nullable=True),
        sa.Column("decision", sa.String(7), nullable=False),
        sa.Column("previous_decision_id", UUID, nullable=True),
        sa.Column("candidate_context_hash", sa.String(64), nullable=True),
        sa.Column("risk_acknowledged", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("risk_level_snapshot", sa.String(2), nullable=True),
        sa.Column("effective_traffic_total_snapshot", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("decision IN ('adopt','watch','drop','archive')", name="editorial_decision_type"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="editorial_decision_actor_nonempty"),
        sa.CheckConstraint("char_length(btrim(reason)) > 0", name="editorial_decision_reason_nonempty"),
        sa.CheckConstraint("candidate_context_hash IS NULL OR char_length(candidate_context_hash) = 64", name="editorial_decision_context_hash_sha256"),
        sa.CheckConstraint(f"risk_level_snapshot IS NULL OR risk_level_snapshot IN ({RISKS})", name="editorial_decision_risk_level"),
        sa.CheckConstraint("effective_traffic_total_snapshot IS NULL OR (effective_traffic_total_snapshot >= 0 AND effective_traffic_total_snapshot <= 100)", name="editorial_decision_traffic_range"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_editorial_decisions_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_id"], ["daily_candidates.id"], name="fk_editorial_decisions_candidate_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_decision_id"], ["editorial_decisions.id"], name="fk_editorial_decisions_previous_decision_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_decisions"),
    )
    op.create_index("ix_editorial_decisions_event_id", "editorial_decisions", ["event_id"])
    op.create_index("ix_editorial_decisions_candidate_id", "editorial_decisions", ["candidate_id"])
    op.create_index("ix_editorial_decisions_previous_decision_id", "editorial_decisions", ["previous_decision_id"])
    op.create_index("ix_editorial_decisions_event_created", "editorial_decisions", ["event_id", "created_at"])
    op.create_index("ix_editorial_decisions_decision_created", "editorial_decisions", ["decision", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_editorial_decisions_decision_created", table_name="editorial_decisions")
    op.drop_index("ix_editorial_decisions_event_created", table_name="editorial_decisions")
    op.drop_index("ix_editorial_decisions_previous_decision_id", table_name="editorial_decisions")
    op.drop_index("ix_editorial_decisions_candidate_id", table_name="editorial_decisions")
    op.drop_index("ix_editorial_decisions_event_id", table_name="editorial_decisions")
    op.drop_table("editorial_decisions")

    op.drop_index("ix_daily_candidates_run_group_rank", table_name="daily_candidates")
    op.drop_index("ix_daily_candidates_event_created", table_name="daily_candidates")
    op.drop_index("ix_daily_candidates_base_editorial_score_id", table_name="daily_candidates")
    op.drop_index("ix_daily_candidates_trend_snapshot_id", table_name="daily_candidates")
    op.drop_index("ix_daily_candidates_event_id", table_name="daily_candidates")
    op.drop_index("ix_daily_candidates_run_id", table_name="daily_candidates")
    op.drop_table("daily_candidates")

    op.drop_index("uq_daily_candidate_runs_success_input", table_name="daily_candidate_runs")
    op.drop_index("ix_daily_candidate_runs_status_created", table_name="daily_candidate_runs")
    op.drop_index("ix_daily_candidate_runs_business_asof", table_name="daily_candidate_runs")
    op.drop_table("daily_candidate_runs")
