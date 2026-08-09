# ruff: noqa: E501
"""Add M4-D Event Cards, editorial packs, versioned drafts and citations.

Revision ID: 20260809_0013
Revises: 20260809_0012
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0013"
down_revision: str | None = "20260809_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())

FORMATS = "'daily_compilation','quick_explainer','fact_check','deep_dive','entertainment','consumer_safety'"


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "event_cards",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("card_version", sa.String(100), nullable=False),
        sa.Column("evidence_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("trend_snapshot_id", UUID, nullable=True),
        sa.Column("editorial_score_id", UUID, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("concise_summary", sa.Text(), nullable=False),
        sa.Column("timeline", JSONB, nullable=False),
        sa.Column("confirmed_claim_ids", JSONB, nullable=False),
        sa.Column("investigating_claim_ids", JSONB, nullable=False),
        sa.Column("single_source_claim_ids", JSONB, nullable=False),
        sa.Column("disputed_claim_ids", JSONB, nullable=False),
        sa.Column("false_claim_ids", JSONB, nullable=False),
        sa.Column("unknown_ids", JSONB, nullable=False),
        sa.Column("source_summary", JSONB, nullable=False),
        sa.Column("effective_assessment", JSONB, nullable=False),
        sa.Column("risk_level", sa.String(2), nullable=False),
        sa.Column("recommended_format", sa.String(32), nullable=False),
        sa.Column("generated_by", sa.String(32), server_default=sa.text("'deterministic'"), nullable=False),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("char_length(evidence_snapshot_hash) = 64", name="event_card_evidence_hash_sha256"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="event_card_input_hash_sha256"),
        sa.CheckConstraint("risk_level IN ('R0','R1','R2','R3','R4')", name="event_card_risk_level"),
        sa.CheckConstraint(f"recommended_format IN ({FORMATS})", name="event_card_recommended_format"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_event_cards_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trend_snapshot_id"], ["event_trend_snapshots.id"], name="fk_event_cards_trend_snapshot_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editorial_score_id"], ["editorial_scores.id"], name="fk_event_cards_editorial_score_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_event_cards_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_cards"),
    )
    op.create_index("ix_event_cards_event_id", "event_cards", ["event_id"])
    op.create_index("ix_event_cards_trend_snapshot_id", "event_cards", ["trend_snapshot_id"])
    op.create_index("ix_event_cards_editorial_score_id", "event_cards", ["editorial_score_id"])
    op.create_index("ix_event_cards_ai_invocation_id", "event_cards", ["ai_invocation_id"])
    op.create_index("ix_event_cards_event_created", "event_cards", ["event_id", "created_at"])
    op.create_index(
        "uq_event_cards_idempotency",
        "event_cards",
        ["event_id", "card_version", "input_hash"],
        unique=True,
    )

    op.create_table(
        "editorial_packs",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("event_card_id", UUID, nullable=False),
        sa.Column("pack_version", sa.String(100), nullable=False),
        sa.Column("recommended_format", sa.String(32), nullable=False),
        sa.Column("suggested_angles", JSONB, nullable=False),
        sa.Column("source_items", JSONB, nullable=False),
        sa.Column("timeline_items", JSONB, nullable=False),
        sa.Column("material_items", JSONB, nullable=False),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("unknown_items", JSONB, nullable=False),
        sa.Column("claim_references", JSONB, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("char_length(input_hash) = 64", name="editorial_pack_input_hash_sha256"),
        sa.CheckConstraint(f"recommended_format IN ({FORMATS})", name="editorial_pack_recommended_format"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_editorial_packs_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_card_id"], ["event_cards.id"], name="fk_editorial_packs_event_card_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_editorial_packs_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_packs"),
    )
    op.create_index("ix_editorial_packs_event_id", "editorial_packs", ["event_id"])
    op.create_index("ix_editorial_packs_event_card_id", "editorial_packs", ["event_card_id"])
    op.create_index("ix_editorial_packs_ai_invocation_id", "editorial_packs", ["ai_invocation_id"])
    op.create_index("ix_editorial_packs_event_created", "editorial_packs", ["event_id", "created_at"])
    op.create_index(
        "uq_editorial_packs_idempotency",
        "editorial_packs",
        ["event_id", "event_card_id", "pack_version", "input_hash"],
        unique=True,
    )

    op.create_table(
        "draft_generation_runs",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("event_card_id", UUID, nullable=False),
        sa.Column("editorial_pack_id", UUID, nullable=False),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("draft_type", sa.String(12), nullable=False),
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
        _created_at(),
        sa.CheckConstraint("draft_type IN ('short_30s','standard_90s','deep_180s')", name="draft_generation_draft_type"),
        sa.CheckConstraint("mode IN ('preview','apply')", name="draft_generation_mode"),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="draft_generation_status"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="draft_generation_run_input_hash_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_draft_generation_runs_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_card_id"], ["event_cards.id"], name="fk_draft_generation_runs_event_card_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editorial_pack_id"], ["editorial_packs.id"], name="fk_draft_generation_runs_editorial_pack_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_draft_generation_runs_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_draft_generation_runs"),
    )
    op.create_index("ix_draft_generation_runs_event_id", "draft_generation_runs", ["event_id"])
    op.create_index("ix_draft_generation_runs_event_card_id", "draft_generation_runs", ["event_card_id"])
    op.create_index("ix_draft_generation_runs_editorial_pack_id", "draft_generation_runs", ["editorial_pack_id"])
    op.create_index("ix_draft_generation_runs_ai_invocation_id", "draft_generation_runs", ["ai_invocation_id"])
    op.create_index("ix_draft_generation_runs_event_created", "draft_generation_runs", ["event_id", "created_at"])
    op.create_index("ix_draft_generation_runs_invocation", "draft_generation_runs", ["ai_invocation_id"])
    op.create_index(
        "uq_draft_generation_runs_apply_input",
        "draft_generation_runs",
        ["event_id", "event_card_id", "editorial_pack_id", "draft_type", "prompt_version", "schema_version", "input_hash"],
        unique=True,
        postgresql_where=sa.text("mode = 'apply'"),
    )

    op.create_table(
        "editorial_drafts",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("event_card_id", UUID, nullable=False),
        sa.Column("editorial_pack_id", UUID, nullable=False),
        sa.Column("draft_chain_id", UUID, nullable=False),
        sa.Column("draft_type", sa.String(12), nullable=False),
        sa.Column("format_key", sa.String(32), nullable=False),
        sa.Column("duration_target_seconds", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("parent_draft_id", UUID, nullable=True),
        sa.Column("source_type", sa.String(5), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("title_candidates", JSONB, nullable=False),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("hook_candidates", JSONB, nullable=False),
        sa.Column("cover_text_candidates", JSONB, nullable=False),
        sa.Column("sections", JSONB, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ending", sa.Text(), nullable=True),
        sa.Column("interaction_question", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("schema_version", sa.String(100), nullable=True),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("generation_run_id", UUID, nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(255), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("draft_type IN ('short_30s','standard_90s','deep_180s')", name="editorial_draft_type"),
        sa.CheckConstraint(f"format_key IN ({FORMATS})", name="editorial_draft_format"),
        sa.CheckConstraint("source_type IN ('ai','human')", name="editorial_draft_source_type"),
        sa.CheckConstraint("status IN ('generated','edited','reviewed','archived')", name="editorial_draft_status"),
        sa.CheckConstraint("draft_version > 0", name="editorial_draft_version_positive"),
        sa.CheckConstraint("duration_target_seconds IN (30,90,180)", name="editorial_draft_duration_allowed"),
        sa.CheckConstraint("char_length(btrim(body)) > 0", name="editorial_draft_body_nonempty"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="editorial_draft_input_hash_sha256"),
        sa.CheckConstraint(
            "(source_type = 'ai' AND ai_invocation_id IS NOT NULL AND generation_run_id IS NOT NULL AND prompt_version IS NOT NULL AND schema_version IS NOT NULL) OR "
            "(source_type = 'human' AND ai_invocation_id IS NULL AND generation_run_id IS NULL AND created_by_actor IS NOT NULL AND char_length(btrim(created_by_actor)) > 0 AND change_note IS NOT NULL AND char_length(btrim(change_note)) > 0)",
            name="editorial_draft_source_provenance",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_editorial_drafts_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_card_id"], ["event_cards.id"], name="fk_editorial_drafts_event_card_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editorial_pack_id"], ["editorial_packs.id"], name="fk_editorial_drafts_editorial_pack_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_draft_id"], ["editorial_drafts.id"], name="fk_editorial_drafts_parent_draft_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_editorial_drafts_ai_invocation_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["draft_generation_runs.id"], name="fk_editorial_drafts_generation_run_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_editorial_drafts"),
        sa.UniqueConstraint("generation_run_id", name="uq_editorial_drafts_generation_run_id"),
    )
    op.create_index("ix_editorial_drafts_event_id", "editorial_drafts", ["event_id"])
    op.create_index("ix_editorial_drafts_event_card_id", "editorial_drafts", ["event_card_id"])
    op.create_index("ix_editorial_drafts_editorial_pack_id", "editorial_drafts", ["editorial_pack_id"])
    op.create_index("ix_editorial_drafts_parent_draft_id", "editorial_drafts", ["parent_draft_id"])
    op.create_index("ix_editorial_drafts_ai_invocation_id", "editorial_drafts", ["ai_invocation_id"])
    op.create_index("ix_editorial_drafts_generation_run_id", "editorial_drafts", ["generation_run_id"])
    op.create_index("ix_editorial_drafts_event_created", "editorial_drafts", ["event_id", "created_at"])
    op.create_index("ix_editorial_drafts_chain", "editorial_drafts", ["draft_chain_id", "draft_version"])
    op.create_index("uq_editorial_drafts_chain_version", "editorial_drafts", ["draft_chain_id", "draft_version"], unique=True)
    op.create_index(
        "uq_editorial_drafts_ai_input",
        "editorial_drafts",
        ["event_card_id", "editorial_pack_id", "draft_type", "prompt_version", "schema_version", "input_hash"],
        unique=True,
        postgresql_where=sa.text("source_type = 'ai'"),
    )

    op.create_table(
        "draft_claim_references",
        sa.Column("draft_id", UUID, nullable=False),
        sa.Column("claim_id", UUID, nullable=False),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("usage", sa.String(10), nullable=False),
        sa.Column("id", UUID, nullable=False),
        _created_at(),
        sa.CheckConstraint("usage IN ('fact','attributed','disputed','debunked')", name="draft_claim_reference_usage"),
        sa.ForeignKeyConstraint(["draft_id"], ["editorial_drafts.id"], name="fk_draft_claim_references_draft_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["evidence_claims.id"], name="fk_draft_claim_references_claim_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_draft_claim_references"),
    )
    op.create_index("ix_draft_claim_references_draft_id", "draft_claim_references", ["draft_id"])
    op.create_index("ix_draft_claim_references_claim_id", "draft_claim_references", ["claim_id"])
    op.create_index("ix_draft_claim_references_claim", "draft_claim_references", ["claim_id"])
    op.create_index(
        "uq_draft_claim_references_section_claim",
        "draft_claim_references",
        ["draft_id", "claim_id", "section_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("draft_claim_references")
    op.drop_table("editorial_drafts")
    op.drop_table("draft_generation_runs")
    op.drop_table("editorial_packs")
    op.drop_table("event_cards")
