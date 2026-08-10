import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


async def _tables() -> set[str]:
    engine = create_async_engine(get_settings().database_url_value, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
    finally:
        await engine.dispose()


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
                        "card_indexes": {
                            item["name"]: item
                            for item in inspect(sync).get_indexes("event_cards")
                        },
                        "draft_indexes": {
                            item["name"]: item
                            for item in inspect(sync).get_indexes("editorial_drafts")
                        },
                        "ref_fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "draft_claim_references"
                            )
                        },
                    }
                )
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m4d_migration_creates_versioned_card_pack_draft_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _schema()
    assert {
        "event_cards",
        "editorial_packs",
        "draft_generation_runs",
        "editorial_drafts",
        "draft_claim_references",
    } <= schema["tables"]
    assert schema["card_indexes"]["uq_event_cards_idempotency"]["unique"]
    assert schema["draft_indexes"]["uq_editorial_drafts_chain_version"]["unique"]
    assert schema["draft_indexes"]["uq_editorial_drafts_ai_input"]["unique"]
    claim_fk = schema["ref_fks"]["fk_draft_claim_references_claim_id"]
    draft_fk = schema["ref_fks"]["fk_draft_claim_references_draft_id"]
    assert claim_fk["referred_table"] == "evidence_claims"
    assert draft_fk["referred_table"] == "editorial_drafts"
    assert claim_fk["options"].get("ondelete") == "RESTRICT"
    assert draft_fk["options"].get("ondelete") == "RESTRICT"


def test_m4d_downgrade_one_preserves_m4c_tables() -> None:
    config = Config("alembic.ini")
    command.downgrade(config, "20260809_0013")
    try:
        command.downgrade(config, "-1")
        tables = asyncio.run(_tables())
        for table in (
            "event_cards",
            "editorial_packs",
            "draft_generation_runs",
            "editorial_drafts",
            "draft_claim_references",
        ):
            assert table not in tables
        assert "event_trend_snapshots" in tables
        assert "editorial_scores" in tables
        assert "editorial_score_overrides" in tables
        assert "evidence_claims" in tables
        assert "ai_providers" in tables
    finally:
        command.upgrade(config, "head")
