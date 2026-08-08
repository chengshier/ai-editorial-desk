import asyncio
import math
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from packages.database.models import RawSignalRecord, SignalEmbeddingRecord
from packages.database.session import get_async_sessionmaker
from packages.embeddings.repositories import SignalEmbeddingRepository
from packages.embeddings.services import EmbeddingOutcomeStatus, EmbeddingService
from tests.m3b_helpers import MappingEmbeddingProvider, create_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_signal_embedding_insert_read_versions_idempotent_and_raw_signal_immutable(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(
        db_session,
        source,
        external_id="persistence",
        title="  测试标题 ",
        text=" 测试正文 ",
    )
    signal_id = signal.id
    original = {
        "title": signal.title,
        "text": signal.text,
        "original_url": signal.original_url,
        "canonical_url": signal.canonical_url,
        "raw_payload": dict(signal.raw_payload),
        "platform": signal.platform,
        "source_id": signal.source_id,
    }

    provider_v1 = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=3,
        vectors={signal_id: (1.0, 0.0, 0.0)},
    )
    first = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v1",
        provider=provider_v1,
    )
    duplicate = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v1",
        provider=provider_v1,
    )

    assert first.generated == 1 and first.failed == 0
    assert duplicate.skipped == 1 and duplicate.generated == 0
    assert len(provider_v1.calls) == 1

    provider_v2 = MappingEmbeddingProvider(
        embedding_version="embedding-v2",
        dimensions=2,
        vectors={signal_id: (0.0, 1.0)},
        model_name="test-model-v2",
    )
    second_version = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v2",
        provider=provider_v2,
    )
    assert second_version.generated == 1

    versions = await EmbeddingService(db_session).list_versions(signal_id)
    assert {item.embedding_version for item in versions} == {
        "embedding-v1",
        "embedding-v2",
    }
    assert {item.dimensions for item in versions} == {2, 3}
    assert all(len(item.input_hash) == 64 for item in versions)

    refreshed = await db_session.get(RawSignalRecord, signal_id)
    assert refreshed is not None
    for key, value in original.items():
        assert getattr(refreshed, key) == value


@pytest.mark.usefixtures("clean_database")
async def test_same_version_different_input_hash_is_explicit_conflict(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="version-conflict")
    signal_id = signal.id
    async with db_session.begin():
        _, created = await SignalEmbeddingRepository(db_session).insert_idempotently(
            signal_id=signal_id,
            provider_key="test-provider",
            model_name="test-model",
            dimensions=2,
            embedding_version="embedding-v1",
            input_schema_version="signal-text-v1",
            input_hash="a" * 64,
            embedding=[1.0, 0.0],
        )
    assert created is True

    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal_id: (1.0, 0.0)},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert result.failed == 1
    assert result.outcomes[0].code == "EMBEDDING_VERSION_CONFLICT"
    assert provider.calls == []


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize(
    ("vector", "dimensions", "expected_code"),
    [
        ((1.0, 0.0), 3, "DIMENSION_MISMATCH"),
        ((math.nan, 1.0), 2, "INVALID_PROVIDER_RESPONSE"),
        ((math.inf, 1.0), 2, "INVALID_PROVIDER_RESPONSE"),
        ((0.0, 0.0), 2, "INVALID_PROVIDER_RESPONSE"),
        ((), 2, "INVALID_PROVIDER_RESPONSE"),
    ],
)
async def test_invalid_provider_vectors_are_rejected_before_persistence(
    db_session, vector: tuple[float, ...], dimensions: int, expected_code: str
) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(
        db_session,
        source,
        external_id=f"invalid-{expected_code}-{len(vector)}",
    )
    signal_id = signal.id
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=dimensions,
        vectors={signal_id: vector},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert result.failed == 1
    assert result.outcomes[0].code == expected_code
    assert await SignalEmbeddingRepository(db_session).get(signal_id, "embedding-v1") is None


@pytest.mark.usefixtures("clean_database")
async def test_postgresql_fk_dimension_and_zero_vector_checks(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="db-checks")
    signal_id = signal.id

    with pytest.raises(SQLAlchemyError):
        async with db_session.begin():
            db_session.add(
                SignalEmbeddingRecord(
                    signal_id=uuid4(),
                    provider_key="test-provider",
                    model_name="test-model",
                    dimensions=2,
                    embedding_version="fk-v1",
                    input_schema_version="signal-text-v1",
                    input_hash="b" * 64,
                    embedding=[1.0, 0.0],
                )
            )
            await db_session.flush()

    with pytest.raises(SQLAlchemyError):
        async with db_session.begin():
            db_session.add(
                SignalEmbeddingRecord(
                    signal_id=signal_id,
                    provider_key="test-provider",
                    model_name="test-model",
                    dimensions=3,
                    embedding_version="dimension-v1",
                    input_schema_version="signal-text-v1",
                    input_hash="c" * 64,
                    embedding=[1.0, 0.0],
                )
            )
            await db_session.flush()

    with pytest.raises(SQLAlchemyError):
        async with db_session.begin():
            db_session.add(
                SignalEmbeddingRecord(
                    signal_id=signal_id,
                    provider_key="test-provider",
                    model_name="test-model",
                    dimensions=2,
                    embedding_version="zero-v1",
                    input_schema_version="signal-text-v1",
                    input_hash="d" * 64,
                    embedding=[0.0, 0.0],
                )
            )
            await db_session.flush()


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_generation_has_one_database_artifact(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="concurrent-embedding")
    signal_id = signal.id
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal_id: (1.0, 0.0)},
    )

    async def generate_once():  # type: ignore[no-untyped-def]
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            return await EmbeddingService(session).process_signals(
                signal_ids=[signal_id],
                embedding_version="embedding-v1",
                provider=provider,
            )

    first, second = await asyncio.gather(generate_once(), generate_once())
    statuses = [first.outcomes[0].status, second.outcomes[0].status]
    assert statuses.count(EmbeddingOutcomeStatus.GENERATED) == 1
    assert statuses.count(EmbeddingOutcomeStatus.SKIPPED) == 1
    count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(SignalEmbeddingRecord)
            .where(
                SignalEmbeddingRecord.signal_id == signal_id,
                SignalEmbeddingRecord.embedding_version == "embedding-v1",
            )
        )
        or 0
    )
    assert count == 1


@pytest.mark.usefixtures("clean_database")
async def test_raw_signal_delete_cascades_embedding_only(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="cascade")
    signal_id = signal.id
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal_id: (1.0, 0.0)},
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert await SignalEmbeddingRepository(db_session).get(signal_id, "embedding-v1") is not None

    stored = await db_session.get(RawSignalRecord, signal_id)
    assert stored is not None
    await db_session.delete(stored)
    await db_session.commit()

    assert await db_session.get(RawSignalRecord, signal_id) is None
    assert await SignalEmbeddingRepository(db_session).get(signal_id, "embedding-v1") is None
