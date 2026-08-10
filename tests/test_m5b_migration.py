import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _schema() -> dict[str, object]:
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
                        "run_indexes": {
                            item["name"]: item
                            for item in inspect(sync).get_indexes(
                                "daily_candidate_runs"
                            )
                        },
                        "candidate_uniques": {
                            item["name"]: item
                            for item in inspect(sync).get_unique_constraints(
                                "daily_candidates"
                            )
                        },
                        "decision_fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "editorial_decisions"
                            )
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m5b_migration_creates_candidate_and_decision_snapshot_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _schema()
    expected_tables = {
        "daily_candidate_runs",
        "daily_candidates",
        "editorial_decisions",
    }
    assert expected_tables <= schema["tables"]
    assert schema["run_indexes"]["uq_daily_candidate_runs_success_input"][
        "unique"
    ]
    expected_uniques = {
        "uq_daily_candidates_run_event",
        "uq_daily_candidates_run_rank",
    }
    assert expected_uniques <= set(schema["candidate_uniques"])
    for fk in schema["decision_fks"].values():
        assert fk["options"].get("ondelete") == "RESTRICT"


def test_m5b_downgrade_one_preserves_m4d_tables() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "20260810_0014")
    try:
        command.downgrade(config, "-1")

        async def tables() -> set[str]:
            engine = create_async_engine(
                get_settings().database_url_value,
                poolclass=NullPool,
            )
            try:
                async with engine.connect() as connection:
                    return await connection.run_sync(
                        lambda sync: set(inspect(sync).get_table_names())
                    )
            finally:
                await engine.dispose()

        names = asyncio.run(tables())
        assert "daily_candidate_runs" not in names
        assert "daily_candidates" not in names
        assert "editorial_decisions" not in names
        assert "event_cards" in names
        assert "editorial_packs" in names
        assert "editorial_drafts" in names
    finally:
        command.upgrade(config, "head")
