import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_m4b_schema() -> dict[str, object]:
    async def inspect_schema() -> dict[str, object]:
        engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync: {
                        "tables": set(inspect(sync).get_table_names()),
                        "claim_columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("evidence_claims")
                        },
                        "source_fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "evidence_claim_sources"
                            )
                        },
                        "claim_uniques": {
                            item["name"]
                            for item in inspect(sync).get_unique_constraints(
                                "evidence_claims"
                            )
                        },
                        "source_uniques": {
                            item["name"]
                            for item in inspect(sync).get_unique_constraints(
                                "evidence_claim_sources"
                            )
                        },
                        "unknown_uniques": {
                            item["name"]
                            for item in inspect(sync).get_unique_constraints(
                                "event_unknowns"
                            )
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m4b_migration_creates_evidence_provenance_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m4b_schema()
    assert {
        "evidence_extraction_runs",
        "evidence_claims",
        "evidence_claim_sources",
        "event_unknowns",
    } <= schema["tables"]
    assert {
        "event_id",
        "claim_text",
        "claim_type",
        "verification_state",
        "extraction_confidence",
        "claim_fingerprint",
        "extraction_version",
        "extraction_run_id",
        "ai_invocation_id",
        "created_by_type",
        "created_by_actor",
        "editor_note",
    } <= schema["claim_columns"]
    assert "uq_evidence_claims_event_fingerprint" in schema["claim_uniques"]
    assert "uq_evidence_claim_sources_claim_signal" in schema["source_uniques"]
    assert "uq_event_unknowns_event_fingerprint" in schema["unknown_uniques"]
    source_fks = schema["source_fks"]
    assert source_fks["fk_evidence_claim_sources_signal_id"]["referred_table"] == "raw_signals"
    assert source_fks["fk_evidence_claim_sources_signal_id"]["options"].get(
        "ondelete"
    ) == "RESTRICT"
    assert source_fks["fk_evidence_claim_sources_claim_id"]["referred_table"] == "evidence_claims"


def test_m4b_downgrade_one_preserves_m4a_tables() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "20260809_0011")
    try:
        command.downgrade(config, "-1")

        async def inspect_tables() -> set[str]:
            engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
            try:
                async with engine.connect() as connection:
                    return await connection.run_sync(
                        lambda sync: set(inspect(sync).get_table_names())
                    )
            finally:
                await engine.dispose()

        tables = asyncio.run(inspect_tables())
        assert "evidence_extraction_runs" not in tables
        assert "evidence_claims" not in tables
        assert "evidence_claim_sources" not in tables
        assert "event_unknowns" not in tables
        assert "ai_providers" in tables
        assert "ai_models" in tables
        assert "ai_task_routes" in tables
        assert "ai_invocations" in tables
        assert "ai_budgets" in tables
    finally:
        command.upgrade(config, "head")
