import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_m3d_schema() -> dict[str, object]:
    async def inspect_schema() -> dict[str, object]:
        engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync: {
                        "tables": set(inspect(sync).get_table_names()),
                        "run_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("clustering_processing_runs")
                        },
                        "run_indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("clustering_processing_runs")
                        },
                        "assignment_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("event_assignment_records")
                        },
                        "assignment_indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("event_assignment_records")
                        },
                        "assignment_fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "event_assignment_records"
                            )
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m3d_migration_creates_processing_and_assignment_audit_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m3d_schema()
    assert {"clustering_processing_runs", "event_assignment_records"} <= schema["tables"]
    assert {
        "mode",
        "status",
        "algorithm_version",
        "dataset_version",
        "actor",
        "started_at",
        "finished_at",
        "requested_count",
        "processed_count",
        "counters",
        "config_snapshot",
        "error_summary",
    } <= schema["run_columns"]
    assert {
        "signal_id",
        "event_id",
        "action",
        "attached_by",
        "algorithm_version",
        "match_decision_id",
        "processing_run_id",
        "previous_event_id",
    } <= schema["assignment_columns"]
    assert {
        "ix_clustering_processing_runs_algorithm_version",
        "ix_clustering_processing_runs_status_started",
        "ix_clustering_processing_runs_algorithm_started",
    } <= schema["run_indexes"]
    assert {
        "ix_event_assignment_records_signal_created",
        "ix_event_assignment_records_event_created",
        "ix_event_assignment_records_algorithm_created",
        "ix_event_assignment_records_run_created",
    } <= schema["assignment_indexes"]
    assert schema["assignment_fks"]["fk_event_assignment_records_signal_id"][
        "referred_table"
    ] == "raw_signals"
    assert schema["assignment_fks"]["fk_event_assignment_records_event_id"][
        "referred_table"
    ] == "events"
    assert schema["assignment_fks"]["fk_event_assignment_records_match_decision_id"][
        "referred_table"
    ] == "signal_match_decisions"


def test_m3d_downgrade_one_restores_m3c_without_touching_0008() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    try:
        command.downgrade(config, "-1")

        async def inspect_after_downgrade() -> set[str]:
            engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
            try:
                async with engine.connect() as connection:
                    return await connection.run_sync(
                        lambda sync: set(inspect(sync).get_table_names())
                    )
            finally:
                await engine.dispose()

        tables = asyncio.run(inspect_after_downgrade())
        assert "clustering_processing_runs" not in tables
        assert "event_assignment_records" not in tables
        assert "signal_fingerprints" in tables
        assert "signal_match_decisions" in tables
        assert "signal_match_overrides" in tables
        assert "signal_event_suppressions" in tables
    finally:
        command.upgrade(config, "head")
