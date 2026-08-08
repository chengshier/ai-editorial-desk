import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from packages.common.config import get_settings


def _inspect_m3b_schema() -> dict[str, object]:
    async def inspect_schema() -> dict[str, object]:
        engine = create_async_engine(
            get_settings().database_url_value,
            poolclass=NullPool,
        )
        try:
            async with engine.connect() as connection:
                schema = await connection.run_sync(
                    lambda sync: {
                        "tables": set(inspect(sync).get_table_names()),
                        "columns": {
                            item["name"]
                            for item in inspect(sync).get_columns("signal_embeddings")
                        },
                        "indexes": {
                            item["name"]
                            for item in inspect(sync).get_indexes("signal_embeddings")
                        },
                        "checks": {
                            item["name"]
                            for item in inspect(sync).get_check_constraints(
                                "signal_embeddings"
                            )
                        },
                        "uniques": {
                            (item["name"], tuple(item["column_names"]))
                            for item in inspect(sync).get_unique_constraints(
                                "signal_embeddings"
                            )
                        },
                        "fks": {
                            item["name"]: item
                            for item in inspect(sync).get_foreign_keys(
                                "signal_embeddings"
                            )
                        },
                    }
                )
                extension = bool(
                    await connection.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                        )
                    )
                )
                vector_type = await connection.scalar(
                    text(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        WHERE c.relname = 'signal_embeddings'
                          AND a.attname = 'embedding'
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                        """
                    )
                )
                schema["vector_extension"] = extension
                schema["vector_type"] = vector_type
                return schema
        finally:
            await engine.dispose()

    return asyncio.run(inspect_schema())


def test_m3b_migration_creates_dimensionless_vector_artifact_schema() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    schema = _inspect_m3b_schema()

    assert "signal_embeddings" in schema["tables"]
    assert schema["vector_extension"] is True
    assert schema["vector_type"] == "vector"
    assert {
        "id",
        "signal_id",
        "provider_key",
        "model_name",
        "dimensions",
        "embedding_version",
        "input_schema_version",
        "input_hash",
        "embedding",
        "created_at",
    } <= schema["columns"]
    assert {
        "ix_signal_embeddings_signal_id",
        "ix_signal_embeddings_embedding_version",
        "ix_signal_embeddings_version_dimensions",
        "ix_signal_embeddings_created_at",
    } <= schema["indexes"]
    assert {
        "ck_signal_embeddings_dimensions_positive",
        "ck_signal_embeddings_input_hash_sha256",
        "ck_signal_embeddings_provider_key_nonempty",
        "ck_signal_embeddings_model_name_nonempty",
        "ck_signal_embeddings_embedding_version_nonempty",
        "ck_signal_embeddings_input_schema_version_nonempty",
        "ck_signal_embeddings_embedding_dimensions_match",
        "ck_signal_embeddings_embedding_nonzero",
    } <= schema["checks"]
    assert (
        "uq_signal_embeddings_signal_version",
        ("signal_id", "embedding_version"),
    ) in schema["uniques"]
    fk = schema["fks"]["fk_signal_embeddings_signal_id"]
    assert fk["referred_table"] == "raw_signals"
    assert fk["options"].get("ondelete") == "CASCADE"


def test_m3b_downgrade_removes_artifact_but_keeps_vector_extension_and_m3a() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    try:
        command.downgrade(config, "20260808_0006")

        async def inspect_after_downgrade() -> tuple[set[str], bool]:
            engine = create_async_engine(
                get_settings().database_url_value,
                poolclass=NullPool,
            )
            try:
                async with engine.connect() as connection:
                    tables = await connection.run_sync(
                        lambda sync: set(inspect(sync).get_table_names())
                    )
                    extension = bool(
                        await connection.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                            )
                        )
                    )
                    return tables, extension
            finally:
                await engine.dispose()

        tables, extension = asyncio.run(inspect_after_downgrade())
        assert "signal_embeddings" not in tables
        assert {"events", "event_signals", "raw_signals"} <= tables
        assert extension is True
    finally:
        command.upgrade(config, "head")
