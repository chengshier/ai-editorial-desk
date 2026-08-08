import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_m3a_schema() -> dict[str, object]:
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
                        "events_columns": {
                            item["name"] for item in inspect(sync).get_columns("events")
                        },
                        "event_signals_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("event_signals")
                        },
                        "event_indexes": {
                            item["name"] for item in inspect(sync).get_indexes("events")
                        },
                        "event_signal_indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("event_signals")
                        },
                        "event_checks": {
                            item["name"]
                            for item in inspect(sync).get_check_constraints("events")
                        },
                        "event_signal_checks": {
                            item["name"]
                            for item in inspect(sync).get_check_constraints("event_signals")
                        },
                        "event_signal_uniques": {
                            (
                                item["name"],
                                tuple(item["column_names"]),
                            )
                            for item in inspect(sync).get_unique_constraints(
                                "event_signals"
                            )
                        },
                        "event_signal_fks": {
                            item["name"]
                            for item in inspect(sync).get_foreign_keys("event_signals")
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m3a_migration_creates_event_foundation_constraints_and_indexes() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m3a_schema()

    assert {"events", "event_signals"} <= schema["tables"]
    assert {
        "id",
        "title",
        "summary",
        "category",
        "status",
        "first_seen_at",
        "last_updated_at",
        "primary_language",
        "entities",
        "keywords",
        "source_count",
        "platform_count",
        "created_at",
        "updated_at",
    } <= schema["events_columns"]
    assert {
        "id",
        "event_id",
        "signal_id",
        "relation",
        "confidence",
        "attached_by",
        "created_at",
        "updated_at",
    } <= schema["event_signals_columns"]
    assert {
        "ix_events_status",
        "ix_events_first_seen_at",
        "ix_events_last_updated_at",
    } <= schema["event_indexes"]
    assert {
        "ix_event_signals_event_id",
        "ix_event_signals_signal_id",
    } <= schema["event_signal_indexes"]
    assert {
        "ck_events_event_status",
        "ck_events_source_count_nonnegative",
        "ck_events_platform_count_nonnegative",
    } <= schema["event_checks"]
    assert {
        "ck_event_signals_event_signal_relation",
        "ck_event_signals_event_signal_attached_by",
        "ck_event_signals_confidence_range",
    } <= schema["event_signal_checks"]
    assert (
        "uq_event_signals_event_signal",
        ("event_id", "signal_id"),
    ) in schema["event_signal_uniques"]
    assert all(
        columns != ("signal_id",)
        for _name, columns in schema["event_signal_uniques"]
    )
    assert {
        "fk_event_signals_event_id",
        "fk_event_signals_signal_id",
    } <= schema["event_signal_fks"]


def test_m3a_migration_downgrade_preserves_m2_raw_signal_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    try:
        command.downgrade(config, "20260807_0005")
        async def inspect_tables() -> set[str]:
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

        tables = asyncio.run(inspect_tables())
        assert "raw_signals" in tables
        assert "raw_signal_comments" in tables
        assert "events" not in tables
        assert "event_signals" not in tables
    finally:
        command.upgrade(config, "head")
