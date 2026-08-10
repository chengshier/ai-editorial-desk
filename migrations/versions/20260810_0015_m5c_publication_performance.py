# ruff: noqa: E501
"""Add M5-C publication records, performance snapshots and CSV import runs.

Revision ID: 20260810_0015
Revises: 20260810_0014
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0015"
down_revision: str | None = "20260810_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
FORMATS = "'daily_compilation','quick_explainer','fact_check','deep_dive','entertainment','consumer_safety'"
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
        "publications",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("draft_id", UUID, nullable=True),
        sa.Column("publication_mode", sa.String(15), nullable=False),
        sa.Column("platform_key", sa.String(100), nullable=False),
        sa.Column("account_label", sa.String(255), nullable=True),
        sa.Column("external_post_id", sa.String(255), nullable=True),
        sa.Column("public_url", sa.String(2048), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title_snapshot", sa.String(500), nullable=True),
        sa.Column("cover_text_snapshot", sa.Text(), nullable=True),
        sa.Column("body_snapshot", sa.Text(), nullable=True),
        sa.Column("publication_content_hash", sa.String(64), nullable=True),
        sa.Column("candidate_run_id", UUID, nullable=True),
        sa.Column("candidate_id", UUID, nullable=True),
        sa.Column("candidate_rank_snapshot", sa.Integer(), nullable=True),
        sa.Column("editorial_decision_id", UUID, nullable=True),
        sa.Column("editorial_decision_snapshot", sa.String(7), nullable=True),
        sa.Column("base_editorial_score_id", UUID, nullable=True),
        sa.Column("editorial_score_snapshot", JSONB, nullable=True),
        sa.Column("effective_traffic_total_snapshot", sa.Float(), nullable=True),
        sa.Column("risk_snapshot", sa.String(2), nullable=True),
        sa.Column("recommended_format_snapshot", sa.String(32), nullable=True),
        sa.Column("draft_chain_id", UUID, nullable=True),
        sa.Column("draft_version_snapshot", sa.Integer(), nullable=True),
        sa.Column("draft_source_type_snapshot", sa.String(5), nullable=True),
        sa.Column("draft_format_snapshot", sa.String(32), nullable=True),
        sa.Column("draft_duration_seconds_snapshot", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("backfill_reason", sa.Text(), nullable=True),
        sa.Column("record_version", sa.String(100), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("publication_mode IN ('workflow','manual_backfill')", name="publication_mode"),
        sa.CheckConstraint("char_length(btrim(platform_key)) > 0", name="publication_platform_key_nonempty"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="publication_actor_nonempty"),
        sa.CheckConstraint("public_url LIKE 'http://%' OR public_url LIKE 'https://%'", name="publication_public_url_http"),
        sa.CheckConstraint("publication_mode != 'workflow' OR (draft_id IS NOT NULL AND editorial_decision_id IS NOT NULL)", name="publication_workflow_provenance"),
        sa.CheckConstraint("publication_mode != 'manual_backfill' OR (backfill_reason IS NOT NULL AND char_length(btrim(backfill_reason)) > 0)", name="publication_backfill_reason"),
        sa.CheckConstraint("candidate_rank_snapshot IS NULL OR candidate_rank_snapshot > 0", name="publication_candidate_rank_positive"),
        sa.CheckConstraint("effective_traffic_total_snapshot IS NULL OR (effective_traffic_total_snapshot >= 0 AND effective_traffic_total_snapshot <= 100)", name="publication_traffic_range"),
        sa.CheckConstraint("draft_version_snapshot IS NULL OR draft_version_snapshot > 0", name="publication_draft_version_positive"),
        sa.CheckConstraint("draft_duration_seconds_snapshot IS NULL OR draft_duration_seconds_snapshot >= 0", name="publication_draft_duration_nonnegative"),
        sa.CheckConstraint("publication_content_hash IS NULL OR char_length(publication_content_hash) = 64", name="publication_content_hash_sha256"),
        sa.CheckConstraint("char_length(btrim(record_version)) > 0", name="publication_record_version_nonempty"),
        sa.CheckConstraint("editorial_decision_snapshot IS NULL OR editorial_decision_snapshot IN ('adopt','watch','drop','archive')", name="publication_editorial_decision"),
        sa.CheckConstraint(f"risk_snapshot IS NULL OR risk_snapshot IN ({RISKS})", name="publication_risk_level"),
        sa.CheckConstraint(f"recommended_format_snapshot IS NULL OR recommended_format_snapshot IN ({FORMATS})", name="publication_recommended_format"),
        sa.CheckConstraint("draft_source_type_snapshot IS NULL OR draft_source_type_snapshot IN ('ai','human')", name="publication_draft_source_type"),
        sa.CheckConstraint(f"draft_format_snapshot IS NULL OR draft_format_snapshot IN ({FORMATS})", name="publication_draft_format"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_publications_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["draft_id"], ["editorial_drafts.id"], name="fk_publications_draft_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_run_id"], ["daily_candidate_runs.id"], name="fk_publications_candidate_run_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_id"], ["daily_candidates.id"], name="fk_publications_candidate_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editorial_decision_id"], ["editorial_decisions.id"], name="fk_publications_editorial_decision_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_editorial_score_id"], ["editorial_scores.id"], name="fk_publications_base_editorial_score_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_publications"),
    )
    op.create_index("ix_publications_event_id", "publications", ["event_id"])
    op.create_index("ix_publications_draft_id", "publications", ["draft_id"])
    op.create_index("ix_publications_candidate_run_id", "publications", ["candidate_run_id"])
    op.create_index("ix_publications_candidate_id", "publications", ["candidate_id"])
    op.create_index("ix_publications_editorial_decision_id", "publications", ["editorial_decision_id"])
    op.create_index("ix_publications_base_editorial_score_id", "publications", ["base_editorial_score_id"])
    op.create_index("ix_publications_draft_chain_id", "publications", ["draft_chain_id"])
    op.create_index("ix_publications_event_published", "publications", ["event_id", "published_at"])
    op.create_index("ix_publications_platform_published", "publications", ["platform_key", "published_at"])
    op.create_index("ix_publications_mode_published", "publications", ["publication_mode", "published_at"])
    op.create_index(
        "uq_publications_platform_external_post",
        "publications",
        ["platform_key", "external_post_id"],
        unique=True,
        postgresql_where=sa.text("external_post_id IS NOT NULL"),
    )
    op.create_index(
        "uq_publications_platform_public_url",
        "publications",
        ["platform_key", "public_url"],
        unique=True,
    )

    op.create_table(
        "performance_import_runs",
        sa.Column("source_type", sa.String(6), nullable=False),
        sa.Column("mapping_version", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", JSONB, nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("source_type = 'csv'", name="performance_import_source"),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="performance_import_status"),
        sa.CheckConstraint("char_length(file_sha256) = 64", name="performance_import_file_hash_sha256"),
        sa.CheckConstraint("char_length(btrim(mapping_version)) > 0", name="performance_import_mapping_version_nonempty"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="performance_import_actor_nonempty"),
        sa.CheckConstraint("row_count >= 0", name="performance_import_row_nonnegative"),
        sa.CheckConstraint("valid_count >= 0", name="performance_import_valid_nonnegative"),
        sa.CheckConstraint("inserted_count >= 0", name="performance_import_inserted_nonnegative"),
        sa.CheckConstraint("duplicate_count >= 0", name="performance_import_duplicate_nonnegative"),
        sa.CheckConstraint("error_count >= 0", name="performance_import_error_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_performance_import_runs"),
    )
    op.create_index("ix_performance_import_created", "performance_import_runs", ["created_at"])
    op.create_index(
        "uq_performance_import_success_file",
        "performance_import_runs",
        ["file_sha256", "mapping_version"],
        unique=True,
        postgresql_where=sa.text("status IN ('running','succeeded')"),
    )

    op.create_table(
        "publication_performance_snapshots",
        sa.Column("publication_id", UUID, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon", sa.String(6), nullable=False),
        sa.Column("source", sa.String(6), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("completion_rate", sa.Float(), nullable=True),
        sa.Column("average_watch_seconds", sa.Float(), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("favorites", sa.BigInteger(), nullable=True),
        sa.Column("follower_delta", sa.BigInteger(), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("supersedes_snapshot_id", UUID, nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("import_run_id", UUID, nullable=True),
        sa.Column("snapshot_version", sa.String(100), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("horizon IN ('h1','h24','d7','custom')", name="performance_horizon"),
        sa.CheckConstraint("source IN ('manual','csv')", name="performance_source"),
        sa.CheckConstraint("views IS NULL OR views >= 0", name="performance_views_nonnegative"),
        sa.CheckConstraint("completion_rate IS NULL OR (completion_rate >= 0 AND completion_rate <= 1)", name="performance_completion_range"),
        sa.CheckConstraint("average_watch_seconds IS NULL OR average_watch_seconds >= 0", name="performance_average_watch_nonnegative"),
        sa.CheckConstraint("likes IS NULL OR likes >= 0", name="performance_likes_nonnegative"),
        sa.CheckConstraint("comments IS NULL OR comments >= 0", name="performance_comments_nonnegative"),
        sa.CheckConstraint("shares IS NULL OR shares >= 0", name="performance_shares_nonnegative"),
        sa.CheckConstraint("favorites IS NULL OR favorites >= 0", name="performance_favorites_nonnegative"),
        sa.CheckConstraint("views IS NOT NULL OR completion_rate IS NOT NULL OR average_watch_seconds IS NOT NULL OR likes IS NOT NULL OR comments IS NOT NULL OR shares IS NOT NULL OR favorites IS NOT NULL OR follower_delta IS NOT NULL", name="performance_at_least_one_metric"),
        sa.CheckConstraint("char_length(snapshot_hash) = 64", name="performance_snapshot_hash_sha256"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="performance_snapshot_actor_nonempty"),
        sa.CheckConstraint("supersedes_snapshot_id IS NULL OR (correction_reason IS NOT NULL AND char_length(btrim(correction_reason)) > 0)", name="performance_correction_reason"),
        sa.CheckConstraint("char_length(btrim(snapshot_version)) > 0", name="performance_snapshot_version_nonempty"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], name="fk_publication_performance_snapshots_publication_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_snapshot_id"], ["publication_performance_snapshots.id"], name="fk_publication_performance_snapshots_supersedes_snapshot_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["import_run_id"], ["performance_import_runs.id"], name="fk_publication_performance_snapshots_import_run_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_publication_performance_snapshots"),
    )
    op.create_index("ix_publication_performance_snapshots_publication_id", "publication_performance_snapshots", ["publication_id"])
    op.create_index("ix_publication_performance_snapshots_supersedes_snapshot_id", "publication_performance_snapshots", ["supersedes_snapshot_id"])
    op.create_index("ix_performance_snapshot_import_run", "publication_performance_snapshots", ["import_run_id"])
    op.create_index("ix_performance_snapshot_publication_observed", "publication_performance_snapshots", ["publication_id", "observed_at"])
    op.create_index("uq_performance_snapshot_hash", "publication_performance_snapshots", ["snapshot_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_performance_snapshot_hash", table_name="publication_performance_snapshots")
    op.drop_index("ix_performance_snapshot_publication_observed", table_name="publication_performance_snapshots")
    op.drop_index("ix_performance_snapshot_import_run", table_name="publication_performance_snapshots")
    op.drop_index("ix_publication_performance_snapshots_supersedes_snapshot_id", table_name="publication_performance_snapshots")
    op.drop_index("ix_publication_performance_snapshots_publication_id", table_name="publication_performance_snapshots")
    op.drop_table("publication_performance_snapshots")

    op.drop_index("uq_performance_import_success_file", table_name="performance_import_runs")
    op.drop_index("ix_performance_import_created", table_name="performance_import_runs")
    op.drop_table("performance_import_runs")

    op.drop_index("uq_publications_platform_public_url", table_name="publications")
    op.drop_index("uq_publications_platform_external_post", table_name="publications")
    op.drop_index("ix_publications_mode_published", table_name="publications")
    op.drop_index("ix_publications_platform_published", table_name="publications")
    op.drop_index("ix_publications_event_published", table_name="publications")
    op.drop_index("ix_publications_draft_chain_id", table_name="publications")
    op.drop_index("ix_publications_base_editorial_score_id", table_name="publications")
    op.drop_index("ix_publications_editorial_decision_id", table_name="publications")
    op.drop_index("ix_publications_candidate_id", table_name="publications")
    op.drop_index("ix_publications_candidate_run_id", table_name="publications")
    op.drop_index("ix_publications_draft_id", table_name="publications")
    op.drop_index("ix_publications_event_id", table_name="publications")
    op.drop_table("publications")
