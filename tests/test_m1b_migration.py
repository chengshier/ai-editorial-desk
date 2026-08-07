import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from packages.database.session import dispose_database, get_async_engine


def test_m1b_migration_downgrade_one_preserves_m1a_tables() -> None:
    config = Config("alembic.ini")
    asyncio.run(dispose_database())
    command.downgrade(config, "base")
    command.upgrade(config, "20260806_0002")
    command.downgrade(config, "-1")

    async def inspect_schema() -> tuple[set[str], set[str]]:
        async with get_async_engine().connect() as connection:
            tables = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            columns = await connection.run_sync(
                lambda sync: {
                    item["name"]
                    for item in inspect(sync).get_columns("platform_accounts")
                }
            )
            return tables, columns

    tables, columns = asyncio.run(inspect_schema())
    assert "connector_definitions" in tables
    assert "platform_accounts" in tables
    assert "configuration_change_logs" not in tables
    assert "updated_by" not in columns
    asyncio.run(dispose_database())
    command.upgrade(config, "head")
