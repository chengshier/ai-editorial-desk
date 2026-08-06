import asyncio
import os
import subprocess

import asyncpg

EXPECTED_TABLES = {
    "alembic_version",
    "connector_definitions",
    "connector_instances",
    "platform_accounts",
    "connector_runs",
    "connector_checkpoints",
    "platform_risk_events",
    "configuration_change_logs",
    "sources",
    "raw_signals",
    "collection_budgets",
    "collection_budget_usage",
}


def run_alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True, capture_output=True, text=True)


async def application_tables() -> set[str]:
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn=dsn)
    try:
        rows = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        return {str(row["tablename"]) for row in rows}
    finally:
        await connection.close()


def test_alembic_upgrade_downgrade_upgrade_roundtrip() -> None:
    run_alembic("upgrade", "head")
    assert EXPECTED_TABLES <= asyncio.run(application_tables())

    run_alembic("downgrade", "base")
    assert not (EXPECTED_TABLES - {"alembic_version"}) & asyncio.run(application_tables())

    run_alembic("upgrade", "head")
    assert EXPECTED_TABLES <= asyncio.run(application_tables())
