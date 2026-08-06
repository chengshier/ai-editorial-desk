import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from packages.database.session import dispose_database, get_async_engine


def test_m1c_migration_downgrade_one_preserves_m1b_tables() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
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
