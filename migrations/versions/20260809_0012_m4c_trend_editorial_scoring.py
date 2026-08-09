# ruff: noqa: E501
"""Add M4-C trend snapshots, editorial scoring, risk and human overrides.

Revision ID: 20260809_0012
Revises: 20260809_0011
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0012"
down_revision: str | None = "20260809_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "event_trend_snapshots",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("calculation_version", sa.String(100), nullable=False),
        sa.Column("window_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("new_signal_count", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("platform_count", sa.Integer(), nullable=False),
        sa.Column("signal_velocity", sa.Float(), nullable=True),
        sa.Column("interaction_velocity", sa.Float(), nullable=True),
        sa.Column("cross_source", sa.Boolean(), nullable=False),
        sa.Column("cross_platform", sa.Boolean(), nullable=False),
        sa.Column("semantic_novelty", sa.Float(), nullable=True),
        sa.Column("cn_gap", sa.Float(), nullable=True),
        sa.Column("update_value", sa.Float(), nullable=True),
        sa.Column("feature_availability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("component_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("window_end_at > window_start_at", name="trend_window_valid"),
        sa.CheckConstraint("signal_count >= 0", name="trend_signal_count_nonnegative"),
        sa.CheckConstraint("new_signal_count >= 0", name="trend_new_signal_count_nonnegative"),
        sa.CheckConstraint("source_count >= 0", name="trend_source_count_nonnegative"),
        sa.CheckConstraint("platform_count >= 0", name="trend_platform_count_nonnegative"),
        sa.CheckConstraint("signal_velocity IS NULL OR signal_velocity >= 0", name="trend_signal_velocity_nonnegative"),
        sa.CheckConstraint("interaction_velocity IS NULL OR interaction_velocity >= 0", name="trend_interaction_velocity_nonnegative"),
        sa.CheckConstraint("semantic_novelty IS NULL OR (semantic_novelty >= 0 AND semantic_novelty <= 1)", name="trend_semantic_novelty_range"),
        sa.CheckConstraint("cn_gap IS NULL OR (cn_gap >= -1 AND cn_gap <= 1)", name="trend_cn_gap_range"),
        sa.CheckConstraint("update_value IS NULL OR (update_value >= 0 AND update_value <= 100)", name="trend_update_value_range"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="trend_input_hash_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_event_trend_snapshots_event_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_trend_snapshots"),
    )
    op.create_index("ix_event_trend_snapshots_event_id", "event_trend_snapshots", ["event_id"])
    op.create_index("ix_event_trend_snapshots_event_created", "event_trend_snapshots", ["event_id", "created_at"])
    op.create_index("ix_event_trend_snapshots_event_window", "event_trend_snapshots", ["event_id", "window_end_at"])
    op.create_index(
        "uq_event_trend_snapshots_idempotency",
        "event_trend_snapshots",
        ["event_id", "calculation_version", "window_start_at", "window_end_at", "input_hash"],
        unique=True,
    )

    op.create_table(
        "editorial_scoring_runs",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("trend_snapshot_id", UUID, nullable=False),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("score_template", sa.String(100), nullable=False),
        sa.Column("score_template_version", sa.String(100), nullable=False),
        sa.Column("scoring_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(7), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("mode IN ('preview','apply')", name="editorial_scoring_mode"),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="editorial_scoring_status"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="editorial_scoring_run_input_hash_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_editorial_scoring_runs_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trend_snapshot_id"], ["event_trend_snapshots.id"], name="fk_editorial_scoring_runs_trend_snapshot_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_editorial_scoring_runs_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_scoring_runs"),
    )
    op.create_index("ix_editorial_scoring_runs_event_id", "editorial_scoring_runs", ["event_id"])
    op.create_index("ix_editorial_scoring_runs_trend_snapshot_id", "editorial_scoring_runs", ["trend_snapshot_id"])
    op.create_index("ix_editorial_scoring_runs_ai_invocation_id", "editorial_scoring_runs", ["ai_invocation_id"])
    op.create_index("ix_editorial_scoring_runs_event_created", "editorial_scoring_runs", ["event_id", "created_at"])
    op.create_index("ix_editorial_scoring_runs_invocation", "editorial_scoring_runs", ["ai_invocation_id"])

    op.create_table(
        "editorial_scores",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("trend_snapshot_id", UUID, nullable=True),
        sa.Column("score_template", sa.String(100), nullable=False),
        sa.Column("score_template_version", sa.String(100), nullable=False),
        sa.Column("scoring_version", sa.String(100), nullable=False),
        sa.Column("source_type", sa.String(5), nullable=False),
        sa.Column("emotion", sa.Integer(), nullable=False),
        sa.Column("information_gap", sa.Integer(), nullable=False),
        sa.Column("visual_value", sa.Integer(), nullable=False),
        sa.Column("user_relevance", sa.Integer(), nullable=False),
        sa.Column("discussion", sa.Integer(), nullable=False),
        sa.Column("novelty", sa.Integer(), nullable=False),
        sa.Column("extendability", sa.Integer(), nullable=False),
        sa.Column("traffic_total", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(2), nullable=False),
        sa.Column("recommended_format", sa.String(32), nullable=False),
        sa.Column("model_reason", sa.Text(), nullable=True),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("scoring_run_id", UUID, nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(255), nullable=False),
        sa.Column("source_reason", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("source_type IN ('ai','human')", name="editorial_score_source_type"),
        sa.CheckConstraint("risk_level IN ('R0','R1','R2','R3','R4')", name="editorial_risk_level"),
        sa.CheckConstraint(
            "recommended_format IN ('daily_compilation','quick_explainer','fact_check','deep_dive','entertainment','consumer_safety')",
            name="editorial_recommended_format",
        ),
        sa.CheckConstraint("emotion >= 0 AND emotion <= 100", name="editorial_score_emotion_range"),
        sa.CheckConstraint("information_gap >= 0 AND information_gap <= 100", name="editorial_score_information_gap_range"),
        sa.CheckConstraint("visual_value >= 0 AND visual_value <= 100", name="editorial_score_visual_value_range"),
        sa.CheckConstraint("user_relevance >= 0 AND user_relevance <= 100", name="editorial_score_user_relevance_range"),
        sa.CheckConstraint("discussion >= 0 AND discussion <= 100", name="editorial_score_discussion_range"),
        sa.CheckConstraint("novelty >= 0 AND novelty <= 100", name="editorial_score_novelty_range"),
        sa.CheckConstraint("extendability >= 0 AND extendability <= 100", name="editorial_score_extendability_range"),
        sa.CheckConstraint("traffic_total >= 0 AND traffic_total <= 100", name="editorial_score_traffic_total_range"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="editorial_score_input_hash_sha256"),
        sa.CheckConstraint(
            "(source_type = 'ai' AND ai_invocation_id IS NOT NULL AND scoring_run_id IS NOT NULL) OR "
            "(source_type = 'human' AND ai_invocation_id IS NULL AND scoring_run_id IS NULL "
            "AND source_reason IS NOT NULL AND char_length(btrim(source_reason)) > 0)",
            name="editorial_score_source_provenance",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_editorial_scores_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trend_snapshot_id"], ["event_trend_snapshots.id"], name="fk_editorial_scores_trend_snapshot_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_editorial_scores_ai_invocation_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scoring_run_id"], ["editorial_scoring_runs.id"], name="fk_editorial_scores_scoring_run_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_scores"),
        sa.UniqueConstraint("scoring_run_id", name="uq_editorial_scores_scoring_run_id"),
    )
    op.create_index("ix_editorial_scores_event_id", "editorial_scores", ["event_id"])
    op.create_index("ix_editorial_scores_trend_snapshot_id", "editorial_scores", ["trend_snapshot_id"])
    op.create_index("ix_editorial_scores_ai_invocation_id", "editorial_scores", ["ai_invocation_id"])
    op.create_index("ix_editorial_scores_event_created", "editorial_scores", ["event_id", "created_at"])
    op.create_index("ix_editorial_scores_trend_snapshot", "editorial_scores", ["trend_snapshot_id"])
    op.create_index("ix_editorial_scores_ai_invocation", "editorial_scores", ["ai_invocation_id"])
    op.create_index(
        "uq_editorial_scores_ai_idempotency",
        "editorial_scores",
        ["event_id", "score_template", "score_template_version", "scoring_version", "input_hash"],
        unique=True,
        postgresql_where=sa.text("source_type = 'ai'"),
    )

    op.create_table(
        "editorial_score_overrides",
        sa.Column("editorial_score_id", UUID, nullable=False),
        sa.Column("overridden_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="editorial_score_override_actor_nonempty"),
        sa.CheckConstraint("char_length(btrim(reason)) > 0", name="editorial_score_override_reason_nonempty"),
        sa.ForeignKeyConstraint(["editorial_score_id"], ["editorial_scores.id"], name="fk_editorial_score_overrides_editorial_score_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_score_overrides"),
    )
    op.create_index("ix_editorial_score_overrides_editorial_score_id", "editorial_score_overrides", ["editorial_score_id"])
    op.create_index("ix_editorial_score_overrides_score_created", "editorial_score_overrides", ["editorial_score_id", "created_at"])


def downgrade() -> None:
    op.drop_table("editorial_score_overrides")
    op.drop_table("editorial_scores")
    op.drop_table("editorial_scoring_runs")
    op.drop_table("event_trend_snapshots")
