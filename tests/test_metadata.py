from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import JSONB

from packages.database.base import Base
from packages.database.models import (
    ConfigurationChangeLog,
    ConnectorRun,
    RawSignalCommentRecord,
    RawSignalRecord,
    SignalEmbeddingRecord,
)
from packages.database.types import SanitizedJSONB

EXPECTED_TABLES = {
    "connector_definitions",
    "connector_instances",
    "platform_accounts",
    "connector_runs",
    "connector_checkpoints",
    "platform_risk_events",
    "configuration_change_logs",
    "sources",
    "raw_signals",
    "raw_signal_comments",
    "events",
    "event_signals",
    "signal_embeddings",
    "signal_fingerprints",
    "signal_match_decisions",
    "signal_match_overrides",
    "signal_event_suppressions",
    "clustering_processing_runs",
    "event_assignment_records",
    "collection_budgets",
    "collection_budget_usage",
    "collection_schedules",
    "collection_schedule_triggers",
    "scheduler_instances",
    "connector_validation_records",
    "ai_providers",
    "ai_models",
    "ai_task_routes",
    "ai_invocations",
    "ai_invocation_attempts",
    "ai_budgets",
    "ai_budget_usages",
    "evidence_extraction_runs",
    "evidence_claims",
    "evidence_claim_sources",
    "event_unknowns",
    "event_trend_snapshots",
    "editorial_scoring_runs",
    "editorial_scores",
    "editorial_score_overrides",
    "event_cards",
    "editorial_packs",
    "draft_generation_runs",
    "editorial_drafts",
    "draft_claim_references",
    "daily_candidate_runs",
    "daily_candidates",
    "editorial_decisions",
}


def test_all_models_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_connector_run_metadata_uses_sanitized_jsonb_alias() -> None:
    column = ConnectorRun.__table__.c.metadata

    assert isinstance(column.type, SanitizedJSONB)
    assert isinstance(column.type.impl, JSONB)
    assert ConnectorRun.run_metadata.property.columns[0].name == "metadata"


def test_configuration_change_log_uses_sanitized_jsonb() -> None:
    assert isinstance(ConfigurationChangeLog.__table__.c.before_data.type, SanitizedJSONB)
    assert isinstance(ConfigurationChangeLog.__table__.c.after_data.type, SanitizedJSONB)


def test_raw_signal_payload_uses_sanitized_jsonb() -> None:
    assert isinstance(RawSignalRecord.__table__.c.raw_payload.type, SanitizedJSONB)


def test_raw_signal_comment_payload_uses_sanitized_jsonb() -> None:
    assert isinstance(
        RawSignalCommentRecord.__table__.c.raw_payload.type,
        SanitizedJSONB,
    )


def test_signal_embedding_uses_dimensionless_pgvector_type() -> None:
    column_type = SignalEmbeddingRecord.__table__.c.embedding.type
    assert isinstance(column_type, VECTOR)
    assert column_type.dim is None
