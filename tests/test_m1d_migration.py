import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_schema() -> tuple[set[str], set[str], set[str]]:
    async def inspect_schema() -> tuple[set[str], set[str], set[str]]:
        engine = create_async_engine(
            get_settings().database_url_value,
            poolclass=NullPool,
        )
        try:
            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync: set(inspect(sync).get_table_names())
                )
                run_columns = await connection.run_sync(
                    lambda sync: {
                        item["name"]
                        for item in inspect(sync).get_columns("connector_runs")
                    }
                )
                checkpoint_columns = await connection.run_sync(
                    lambda sync: {
                        item["name"]
                        for item in inspect(sync).get_columns("connector_checkpoints")
                    }
                )
                return tables, run_columns, checkpoint_columns
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m1d_migration_creates_scheduler_validation_and_debug_fields() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    tables, run_columns, checkpoint_columns = _inspect_schema()
    assert {
        "collection_schedules",
        "collection_schedule_triggers",
        "scheduler_instances",
        "connector_validation_records",
    } <= tables
    assert {"parent_run_id", "trigger_type", "progress_updated_at"} <= run_columns
    assert "source_id" in checkpoint_columns


def test_m1d_migration_downgrade_one_preserves_m1c() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "-1")

    tables, run_columns, _ = _inspect_schema()
    assert "sources" in tables
    assert "raw_signals" in tables
    assert "collection_budgets" in tables
    assert "collection_schedules" not in tables
    assert "connector_validation_records" not in tables
    assert "source_id" in run_columns
    assert "trigger_type" not in run_columns
    command.upgrade(config, "head")
