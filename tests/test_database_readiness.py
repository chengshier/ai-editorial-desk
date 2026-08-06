import pytest

from packages.database.session import check_database_ready, dispose_database


@pytest.mark.asyncio
async def test_database_readiness_executes_postgresql_ping() -> None:
    try:
        await check_database_ready(timeout_seconds=5)
    finally:
        await dispose_database()
