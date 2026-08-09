import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://ai_editorial:ai_editorial_test@127.0.0.1:55432/ai_editorial_test",
)
os.environ.setdefault(
    "APP_SECRET_KEY",
    "test-only-secret-key-that-is-at-least-32-characters",
)
os.environ.setdefault(
    "APP_ADMIN_TOKEN",
    "test-only-admin-token-at-least-24-characters",
)

from packages.database.session import (  # noqa: E402
    dispose_database,
    get_async_engine,
    get_async_sessionmaker,
)

TABLES_IN_DELETE_ORDER = (
    "editorial_score_overrides",
    "editorial_scores",
    "editorial_scoring_runs",
    "event_trend_snapshots",
    "event_unknowns",
    "evidence_claim_sources",
    "evidence_claims",
    "evidence_extraction_runs",
    "ai_invocation_attempts",
    "ai_invocations",
    "ai_budget_usages",
    "ai_budgets",
    "ai_task_routes",
    "ai_models",
    "ai_providers",
    "event_assignment_records",
    "clustering_processing_runs",
    "signal_match_decisions",
    "signal_match_overrides",
    "signal_event_suppressions",
    "signal_fingerprints",
    "signal_embeddings",
    "event_signals",
    "events",
    "collection_schedule_triggers",
    "collection_schedules",
    "scheduler_instances",
    "connector_validation_records",
    "configuration_change_logs",
    "raw_signal_comments",
    "raw_signals",
    "collection_budget_usage",
    "collection_budgets",
    "platform_risk_events",
    "connector_checkpoints",
    "connector_runs",
    "sources",
    "platform_accounts",
    "connector_instances",
    "connector_definitions",
)

_FIRST_FAILURE_CODE = 1
_FAILURE_FILE_CODES = {
    "tests/test_admin_api_m4c.py": 41,
    "tests/test_editorial_concurrency_m4c.py": 42,
    "tests/test_editorial_database_m4c.py": 43,
    "tests/test_editorial_fixture_matrix_m4c.py": 44,
    "tests/test_editorial_human_m4c.py": 45,
    "tests/test_editorial_scoring_m4c.py": 46,
    "tests/test_m4c_migration.py": 47,
    "tests/test_trend_m4c.py": 48,
    "tests/test_metadata.py": 61,
    "tests/test_migrations.py": 62,
    "tests/test_m4b_migration.py": 63,
    "tests/test_m3d_migration.py": 64,
    "tests/test_m3c_migration.py": 65,
    "tests/test_m3b_migration.py": 66,
    "tests/test_m3a_migration.py": 67,
    "tests/test_definition_sync_m1b.py": 68,
}


def _diagnostic_code(path: str) -> int:
    exact = _FAILURE_FILE_CODES.get(path)
    if exact is not None:
        return exact
    filename = path.rsplit("/", 1)[-1]
    if filename < "test_editorial_":
        return 71
    if filename < "test_m1":
        return 72
    if filename < "test_metadata":
        return 73
    if filename < "test_read":
        return 74
    if filename < "test_validation":
        return 75
    return 76


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture
async def clean_database(migrated_database: None) -> AsyncIterator[None]:
    del migrated_database
    async with get_async_engine().begin() as connection:
        await connection.execute(
            text(f"TRUNCATE {', '.join(TABLES_IN_DELETE_ORDER)} CASCADE")
        )
    yield
    await dispose_database()


@pytest_asyncio.fixture
async def db_session(clean_database: None) -> AsyncIterator[AsyncSession]:
    del clean_database
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        yield session
        await session.rollback()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    global _FIRST_FAILURE_CODE
    if not report.failed:
        return
    path = report.nodeid.split("::", 1)[0]
    _FIRST_FAILURE_CODE = _diagnostic_code(path)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if session.testsfailed:
        session.exitstatus = _FIRST_FAILURE_CODE
