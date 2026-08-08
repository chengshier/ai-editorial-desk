from datetime import UTC, datetime

import pytest

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.embeddings.repositories import SignalEmbeddingRepository
from packages.embeddings.services import EmbeddingService, SignalSimilarityService
from tests.m3b_helpers import MappingEmbeddingProvider, create_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_exact_cosine_recall_orders_candidates_excludes_self_and_respects_top_k(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal_a = await create_signal(
        db_session,
        source,
        external_id="recall-a",
        published_at=datetime(2026, 8, 8, 0, 0, tzinfo=UTC),
    )
    signal_b = await create_signal(
        db_session,
        source,
        external_id="recall-b",
        published_at=datetime(2026, 8, 8, 0, 10, tzinfo=UTC),
    )
    signal_c = await create_signal(
        db_session,
        source,
        external_id="recall-c",
        published_at=datetime(2026, 8, 8, 2, 0, tzinfo=UTC),
    )
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={
            signal_a.id: (1.0, 0.0),
            signal_b.id: (0.9, 0.1),
            signal_c.id: (0.0, 1.0),
        },
    )
    generated = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal_a.id, signal_b.id, signal_c.id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert generated.generated == 3

    candidates = await SignalSimilarityService(db_session).recall(
        signal_id=signal_a.id,
        embedding_version="embedding-v1",
        top_k=10,
    )
    assert [item.candidate_signal_id for item in candidates] == [signal_b.id, signal_c.id]
    assert candidates[0].similarity > candidates[1].similarity
    assert candidates[0].similarity > 0.99
    assert candidates[1].similarity == pytest.approx(0.0)
    assert all(item.candidate_signal_id != signal_a.id for item in candidates)

    top_one = await SignalSimilarityService(db_session).recall(
        signal_id=signal_a.id,
        embedding_version="embedding-v1",
        top_k=1,
    )
    assert [item.candidate_signal_id for item in top_one] == [signal_b.id]


@pytest.mark.usefixtures("clean_database")
async def test_recall_threshold_time_window_version_and_dimension_isolation(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    target = await create_signal(
        db_session,
        source,
        external_id="isolation-target",
        platform="rss",
        published_at=datetime(2026, 8, 8, 0, 0, tzinfo=UTC),
    )
    in_window = await create_signal(
        db_session,
        source,
        external_id="isolation-window",
        platform="weibo",
        published_at=datetime(2026, 8, 8, 0, 15, tzinfo=UTC),
    )
    outside_window = await create_signal(
        db_session,
        source,
        external_id="isolation-outside",
        published_at=datetime(2026, 8, 8, 3, 0, tzinfo=UTC),
    )
    other_version = await create_signal(
        db_session,
        source,
        external_id="isolation-version",
        published_at=datetime(2026, 8, 8, 0, 20, tzinfo=UTC),
    )
    other_dimension = await create_signal(
        db_session,
        source,
        external_id="isolation-dimension",
        published_at=datetime(2026, 8, 8, 0, 25, tzinfo=UTC),
    )

    v1 = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={
            target.id: (1.0, 0.0),
            in_window.id: (0.95, 0.05),
            outside_window.id: (0.0, 1.0),
        },
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[target.id, in_window.id, outside_window.id],
        embedding_version="embedding-v1",
        provider=v1,
    )
    v2 = MappingEmbeddingProvider(
        embedding_version="embedding-v2",
        dimensions=2,
        vectors={other_version.id: (1.0, 0.0)},
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[other_version.id],
        embedding_version="embedding-v2",
        provider=v2,
    )
    async with db_session.begin():
        await SignalEmbeddingRepository(db_session).insert_idempotently(
            signal_id=other_dimension.id,
            provider_key="test-provider",
            model_name="test-model",
            dimensions=3,
            embedding_version="embedding-v1",
            input_schema_version="signal-text-v1",
            input_hash="e" * 64,
            embedding=[1.0, 0.0, 0.0],
        )

    candidates = await SignalSimilarityService(db_session).recall(
        signal_id=target.id,
        embedding_version="embedding-v1",
        top_k=10,
        min_similarity=0.9,
        time_from=datetime(2026, 8, 8, 0, 5, tzinfo=UTC),
        time_to=datetime(2026, 8, 8, 0, 30, tzinfo=UTC),
    )
    assert [item.candidate_signal_id for item in candidates] == [in_window.id]
    candidate = candidates[0]
    assert candidate.embedding_version == "embedding-v1"
    assert candidate.platform == "weibo"
    assert candidate.source_id == source.id
    assert candidate.published_at == datetime(2026, 8, 8, 0, 15, tzinfo=UTC)
    assert other_version.id not in {item.candidate_signal_id for item in candidates}
    assert other_dimension.id not in {item.candidate_signal_id for item in candidates}


@pytest.mark.usefixtures("clean_database")
async def test_recall_requires_existing_embedding(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="no-embedding")
    with pytest.raises(ResourceNotFoundError, match="embedding_version"):
        await SignalSimilarityService(db_session).recall(
            signal_id=signal.id,
            embedding_version="embedding-v1",
            top_k=10,
        )
