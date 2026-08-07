import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from packages.database.session import dispose_database, get_async_engine

M1C_REVISION = "20260806_0003"


def test_m1c_migration_creates_budget_usage_primary_key() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, M1C_REVISION)

    async def inspect_budget_usage() -> tuple[set[str], list[str]]:
        async with get_async_engine().connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {
                    item["name"]
                    for item in inspect(sync).get_columns("collection_budget_usage")
                }
            )
            primary_key = await connection.run_sync(
                lambda sync: inspect(sync)
                .get_pk_constraint("collection_budget_usage")
                .get("constrained_columns", [])
            )
            return columns, primary_key

    columns, primary_key = asyncio.run(inspect_budget_usage())
    assert "id" in columns
    assert primary_key == ["id"]
    asyncio.run(dispose_database())
    command.upgrade(config, "head")


def test_m1c_migration_downgrade_one_preserves_m1b_tables() -> None:
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, M1C_REVISION)
    command.downgrade(config, "-1")

    async def inspect_schema() -> tuple[set[str], set[str]]:
        async with get_async_engine().connect() as connection:
            tables = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            run_columns = await connection.run_sync(
                lambda sync: {
                    item["name"]
                    for item in inspect(sync).get_columns("connector_runs")
                }
            )
            return tables, run_columns

    tables, run_columns = asyncio.run(inspect_schema())
    assert "configuration_change_logs" in tables
    assert "connector_runs" in tables
    assert "sources" not in tables
    assert "raw_signals" not in tables
    assert "collection_budgets" not in tables
    assert "source_id" not in run_columns
    assert "failed_count" not in run_columns
    asyncio.run(dispose_database())
    command.upgrade(config, "head")
