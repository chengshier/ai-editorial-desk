import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_m3c_schema() -> dict[str, object]:
    async def inspect_schema() -> dict[str, object]:
        engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync: {
                        "tables": set(inspect(sync).get_table_names()),
                        "event_columns": {
                            item["name"] for item in inspect(sync).get_columns("events")
                        },
                        "event_indexes": {
                            item["name"] for item in inspect(sync).get_indexes("events")
                        },
                        "event_fks": {
                            item["name"]: item for item in inspect(sync).get_foreign_keys("events")
                        },
                        "event_signal_checks": {
                            item["name"]: item["sqltext"]
                            for item in inspect(sync).get_check_constraints("event_signals")
                        },
                        "fingerprint_indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("signal_fingerprints")
                        },
                        "fingerprint_uniques": {
                            (item["name"], tuple(item["column_names"]))
                            for item in inspect(sync).get_unique_constraints("signal_fingerprints")
                        },
                        "decision_indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("signal_match_decisions")
                        },
                        "decision_uniques": {
                            (item["name"], tuple(item["column_names"]))
                            for item in inspect(sync).get_unique_constraints("signal_match_decisions")
                        },
                        "decision_checks": {
                            item["name"]
                            for item in inspect(sync).get_check_constraints("signal_match_decisions")
                        },
                        "override_uniques": {
                            (item["name"], tuple(item["column_names"]))
                            for item in inspect(sync).get_unique_constraints("signal_match_overrides")
                        },
                        "suppression_uniques": {
                            (item["name"], tuple(item["column_names"]))
                            for item in inspect(sync).get_unique_constraints("signal_event_suppressions")
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m3c_migration_creates_dedup_cluster_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m3c_schema()
    assert {
        "signal_fingerprints",
        "signal_match_decisions",
        "signal_match_overrides",
        "signal_event_suppressions",
    } <= schema["tables"]
    assert "merged_into_event_id" in schema["event_columns"]
    assert "ix_events_merged_into_event_id" in schema["event_indexes"]
    event_fk = schema["event_fks"]["fk_events_merged_into_event_id"]
    assert event_fk["referred_table"] == "events"
    assert event_fk["options"].get("ondelete") == "RESTRICT"
    assert "related" in schema["event_signal_checks"]["ck_event_signals_event_signal_relation"]
    assert (
        "uq_signal_fingerprints_signal_version",
        ("signal_id", "fingerprint_version"),
    ) in schema["fingerprint_uniques"]
    assert {
        "ix_signal_fingerprints_signal_id",
        "ix_signal_fingerprints_fingerprint_version",
        "ix_signal_fingerprints_version_created",
    } <= schema["fingerprint_indexes"]
    assert (
        "uq_signal_match_decisions_pair_algorithm",
        ("left_signal_id", "right_signal_id", "algorithm_version"),
    ) in schema["decision_uniques"]
    assert {
        "ck_signal_match_decisions_match_pair_canonical_order",
        "ck_signal_match_decisions_match_score_range",
        "ck_signal_match_decisions_match_algorithm_version_nonempty",
        "ck_signal_match_decisions_signal_match_decision",
        "ck_signal_match_decisions_signal_match_primary_method",
    } <= schema["decision_checks"]
    assert {
        "ix_signal_match_decisions_left",
        "ix_signal_match_decisions_right",
        "ix_signal_match_decisions_algorithm",
        "ix_signal_match_decisions_decision",
    } <= schema["decision_indexes"]
    assert (
        "uq_signal_match_overrides_pair",
        ("left_signal_id", "right_signal_id"),
    ) in schema["override_uniques"]
    assert (
        "uq_signal_event_suppressions_signal_event",
        ("signal_id", "event_id"),
    ) in schema["suppression_uniques"]


def test_m3c_downgrade_restores_m3b_and_removes_related_relation() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    try:
        command.downgrade(config, "20260808_0007")

        async def inspect_after_downgrade() -> tuple[set[str], set[str], str]:
            engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
            try:
                async with engine.connect() as connection:
                    return await connection.run_sync(
                        lambda sync: (
                            set(inspect(sync).get_table_names()),
                            {item["name"] for item in inspect(sync).get_columns("events")},
                            next(
                                item["sqltext"]
                                for item in inspect(sync).get_check_constraints("event_signals")
                                if item["name"] == "ck_event_signals_event_signal_relation"
                            ),
                        )
                    )
            finally:
                await engine.dispose()

        tables, event_columns, relation_check = asyncio.run(inspect_after_downgrade())
        assert "signal_embeddings" in tables
        assert "signal_fingerprints" not in tables
        assert "signal_match_decisions" not in tables
        assert "signal_match_overrides" not in tables
        assert "signal_event_suppressions" not in tables
        assert "merged_into_event_id" not in event_columns
        assert "related" not in relation_check
    finally:
        command.upgrade(config, "head")
