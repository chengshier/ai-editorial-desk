import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


async def _inspect_tables() -> set[str]:
    engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
    finally:
        await engine.dispose()


def _inspect_m4c_schema() -> dict[str, object]:
    async def inspect_schema() -> dict[str, object]:
        engine = create_async_engine(
            get_settings().database_url_value,
            poolclass=NullPool,
        )
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync: {
                        "tables": set(inspect(sync).get_table_names()),
                        "trend_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("event_trend_snapshots")
                        },
                        "score_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("editorial_scores")
                        },
                        "score_indexes": {
                            item["name"]: item
                            for item in inspect(sync).get_indexes("editorial_scores")
                        },
                        "trend_indexes": {
                            item["name"]: item
                            for item in inspect(sync).get_indexes(
                                "event_trend_snapshots"
                            )
                        },
                        "override_fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "editorial_score_overrides"
                            )
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m4c_migration_creates_trend_score_run_and_override_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m4c_schema()
    assert {
        "event_trend_snapshots",
        "editorial_scoring_runs",
        "editorial_scores",
        "editorial_score_overrides",
    } <= schema["tables"]
    assert {
        "event_id",
        "calculation_version",
        "window_start_at",
        "window_end_at",
        "signal_velocity",
        "interaction_velocity",
        "semantic_novelty",
        "cn_gap",
        "update_value",
        "feature_availability",
        "component_metrics",
        "input_hash",
    } <= schema["trend_columns"]
    assert {
        "event_id",
        "trend_snapshot_id",
        "score_template",
        "score_template_version",
        "scoring_version",
        "source_type",
        "emotion",
        "information_gap",
        "visual_value",
        "user_relevance",
        "discussion",
        "novelty",
        "extendability",
        "traffic_total",
        "risk_level",
        "recommended_format",
        "ai_invocation_id",
        "scoring_run_id",
        "input_hash",
    } <= schema["score_columns"]
    assert schema["trend_indexes"]["uq_event_trend_snapshots_idempotency"]["unique"]
    assert schema["score_indexes"]["uq_editorial_scores_ai_idempotency"]["unique"]
    override_fk = schema["override_fks"][
        "fk_editorial_score_overrides_editorial_score_id"
    ]
    assert override_fk["referred_table"] == "editorial_scores"
    assert override_fk["options"].get("ondelete") == "RESTRICT"


def test_m4c_downgrade_one_preserves_m4b_tables() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "20260809_0012")
    try:
        command.downgrade(config, "-1")
        tables = asyncio.run(_inspect_tables())
        assert "event_trend_snapshots" not in tables
        assert "editorial_scoring_runs" not in tables
        assert "editorial_scores" not in tables
        assert "editorial_score_overrides" not in tables
        assert "evidence_extraction_runs" in tables
        assert "evidence_claims" in tables
        assert "evidence_claim_sources" in tables
        assert "event_unknowns" in tables
        assert "ai_providers" in tables
    finally:
        command.upgrade(config, "head")
