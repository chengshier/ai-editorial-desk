# ruff: noqa: E501
"""Add M4-B evidence claims, source provenance, unknowns and extraction runs.

Revision ID: 20260809_0011
Revises: 20260809_0010
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0011"
down_revision: str | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "evidence_extraction_runs",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("extraction_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(7), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("requested_signal_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("claim_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unknown_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("invalid_item_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("character_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint("mode IN ('preview','apply')", name="evidence_extraction_run_mode"),
        sa.CheckConstraint("status IN ('running','succeeded','partial','failed')", name="evidence_extraction_run_status"),
        sa.CheckConstraint("requested_signal_count >= 0", name="evidence_run_signal_count_nonnegative"),
        sa.CheckConstraint("claim_count >= 0", name="evidence_run_claim_count_nonnegative"),
        sa.CheckConstraint("unknown_count >= 0", name="evidence_run_unknown_count_nonnegative"),
        sa.CheckConstraint("invalid_item_count >= 0", name="evidence_run_invalid_count_nonnegative"),
        sa.CheckConstraint("character_count >= 0", name="evidence_run_character_count_nonnegative"),
        sa.CheckConstraint("char_length(input_hash) = 64", name="evidence_run_input_hash_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_evidence_extraction_runs_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_evidence_extraction_runs_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_extraction_runs"),
    )
    op.create_index("ix_evidence_extraction_runs_event_id", "evidence_extraction_runs", ["event_id"])
    op.create_index("ix_evidence_extraction_runs_ai_invocation_id", "evidence_extraction_runs", ["ai_invocation_id"])
    op.create_index("ix_evidence_extraction_runs_event_created", "evidence_extraction_runs", ["event_id", "created_at"])
    op.create_index("ix_evidence_extraction_runs_invocation", "evidence_extraction_runs", ["ai_invocation_id"])

    op.create_table(
        "evidence_claims",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(10), nullable=False),
        sa.Column("verification_state", sa.String(13), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("claim_fingerprint", sa.String(64), nullable=False),
        sa.Column("extraction_version", sa.String(100), nullable=False),
        sa.Column("extraction_run_id", UUID, nullable=True),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("created_by_type", sa.String(5), nullable=False),
        sa.Column("created_by_actor", sa.String(255), nullable=True),
        sa.Column("editor_note", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("claim_type IN ('fact','allegation','opinion','forecast')", name="evidence_claim_type"),
        sa.CheckConstraint("verification_state IN ('confirmed','investigating','single_source','disputed','false')", name="evidence_verification_state"),
        sa.CheckConstraint("created_by_type IN ('ai','human')", name="evidence_created_by_type"),
        sa.CheckConstraint("char_length(btrim(claim_text)) > 0", name="evidence_claim_text_nonempty"),
        sa.CheckConstraint("char_length(claim_fingerprint) = 64", name="evidence_claim_fingerprint_sha256"),
        sa.CheckConstraint("extraction_confidence IS NULL OR (extraction_confidence >= 0 AND extraction_confidence <= 1)", name="evidence_claim_confidence_range"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_evidence_claims_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["evidence_extraction_runs.id"], name="fk_evidence_claims_extraction_run_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_evidence_claims_ai_invocation_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_claims"),
        sa.UniqueConstraint("event_id", "claim_fingerprint", name="uq_evidence_claims_event_fingerprint"),
    )
    op.create_index("ix_evidence_claims_event_id", "evidence_claims", ["event_id"])
    op.create_index("ix_evidence_claims_extraction_run_id", "evidence_claims", ["extraction_run_id"])
    op.create_index("ix_evidence_claims_ai_invocation_id", "evidence_claims", ["ai_invocation_id"])
    op.create_index("ix_evidence_claims_event_state", "evidence_claims", ["event_id", "verification_state"])
    op.create_index("ix_evidence_claims_invocation", "evidence_claims", ["ai_invocation_id"])

    op.create_table(
        "evidence_claim_sources",
        sa.Column("claim_id", UUID, nullable=False),
        sa.Column("signal_id", UUID, nullable=False),
        sa.Column("role", sa.String(13), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint("role IN ('supporting','contradicting')", name="evidence_source_role"),
        sa.ForeignKeyConstraint(["claim_id"], ["evidence_claims.id"], name="fk_evidence_claim_sources_claim_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["signal_id"], ["raw_signals.id"], name="fk_evidence_claim_sources_signal_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_claim_sources"),
        sa.UniqueConstraint("claim_id", "signal_id", name="uq_evidence_claim_sources_claim_signal"),
    )
    op.create_index("ix_evidence_claim_sources_claim_id", "evidence_claim_sources", ["claim_id"])
    op.create_index("ix_evidence_claim_sources_signal_id", "evidence_claim_sources", ["signal_id"])
    op.create_index("ix_evidence_claim_sources_signal", "evidence_claim_sources", ["signal_id"])

    op.create_table(
        "event_unknowns",
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("unknown_text", sa.Text(), nullable=False),
        sa.Column("unknown_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("source_type", sa.String(5), nullable=False),
        sa.Column("extraction_run_id", UUID, nullable=True),
        sa.Column("ai_invocation_id", UUID, nullable=True),
        sa.Column("resolved_by_claim_id", UUID, nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_by_actor", sa.String(255), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('open','resolved','dismissed')", name="event_unknown_status"),
        sa.CheckConstraint("source_type IN ('ai','human')", name="event_unknown_source_type"),
        sa.CheckConstraint("char_length(btrim(unknown_text)) > 0", name="event_unknown_text_nonempty"),
        sa.CheckConstraint("char_length(unknown_fingerprint) = 64", name="event_unknown_fingerprint_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_event_unknowns_event_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["evidence_extraction_runs.id"], name="fk_event_unknowns_extraction_run_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ai_invocation_id"], ["ai_invocations.id"], name="fk_event_unknowns_ai_invocation_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_claim_id"], ["evidence_claims.id"], name="fk_event_unknowns_resolved_by_claim_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_event_unknowns"),
        sa.UniqueConstraint("event_id", "unknown_fingerprint", name="uq_event_unknowns_event_fingerprint"),
    )
    op.create_index("ix_event_unknowns_event_id", "event_unknowns", ["event_id"])
    op.create_index("ix_event_unknowns_extraction_run_id", "event_unknowns", ["extraction_run_id"])
    op.create_index("ix_event_unknowns_ai_invocation_id", "event_unknowns", ["ai_invocation_id"])
    op.create_index("ix_event_unknowns_resolved_by_claim_id", "event_unknowns", ["resolved_by_claim_id"])
    op.create_index("ix_event_unknowns_event_status", "event_unknowns", ["event_id", "status"])


def downgrade() -> None:
    op.drop_table("event_unknowns")
    op.drop_table("evidence_claim_sources")
    op.drop_table("evidence_claims")
    op.drop_table("evidence_extraction_runs")
