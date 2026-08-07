import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from packages.database.session import dispose_database, get_async_engine


def test_m1d_migration_creates_scheduler_validation_and_debug_fields() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")

    async def inspect_schema() -> tuple[set[str], set[str], set[str]]:
        async with get_async_engine().connect() as connection:
            tables = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            run_columns = await connection.run_sync(
                lambda sync: {item["name"] for item in inspect(sync).get_columns("connector_runs")}
            )
            checkpoint_columns = await connection.run_sync(
                lambda sync: {
                    item["name"] for item in inspect(sync).get_columns("connector_checkpoints")
                }
            )
            return tables, run_columns, checkpoint_columns

    tables, run_columns, checkpoint_columns = asyncio.run(inspect_schema())
    assert {
        "collection_schedules",
        "collection_schedule_triggers",
        "scheduler_instances",
        "connector_validation_records",
    } <= tables
    assert {"parent_run_id", "trigger_type", "progress_updated_at"} <= run_columns
    assert "source_id" in checkpoint_columns
    asyncio.run(dispose_database())


def test_m1d_migration_downgrade_one_preserves_m1c() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "-1")

    async def inspect_schema() -> tuple[set[str], set[str]]:
        async with get_async_engine().connect() as connection:
            tables = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            run_columns = await connection.run_sync(
                lambda sync: {item["name"] for item in inspect(sync).get_columns("connector_runs")}
            )
            return tables, run_columns

    tables, run_columns = asyncio.run(inspect_schema())
    assert "sources" in tables
    assert "raw_signals" in tables
    assert "collection_budgets" in tables
    assert "collection_schedules" not in tables
    assert "connector_validation_records" not in tables
    assert "source_id" in run_columns
    assert "trigger_type" not in run_columns
    asyncio.run(dispose_database())
    command.upgrade(config, "head")
