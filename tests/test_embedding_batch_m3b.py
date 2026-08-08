import pytest

from packages.embeddings.services import EmbeddingService
from tests.m3b_helpers import MappingEmbeddingProvider, create_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_batch_one_item_and_duplicate_signal_id(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="batch-one")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal.id: (1.0, 0.0)},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id, signal.id],
        embedding_version="embedding-v1",
        provider=provider,
        batch_size=1,
    )
    assert result.requested == 1
    assert result.generated == 1
    assert [len(call) for call in provider.calls] == [1]


@pytest.mark.usefixtures("clean_database")
async def test_batch_size_chunks_provider_calls(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signals = [
        await create_signal(db_session, source, external_id=f"batch-{index}")
        for index in range(5)
    ]
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal.id: (1.0, float(index + 1)) for index, signal in enumerate(signals)},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id for signal in signals],
        embedding_version="embedding-v1",
        provider=provider,
        batch_size=2,
    )
    assert result.generated == 5
    assert [len(call) for call in provider.calls] == [2, 2, 1]


@pytest.mark.usefixtures("clean_database")
async def test_batch_mixed_existing_missing_and_empty_text(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    existing = await create_signal(db_session, source, external_id="batch-existing")
    missing = await create_signal(db_session, source, external_id="batch-missing")
    empty = await create_signal(
        db_session,
        source,
        external_id="batch-empty",
        title="   ",
        text="\n\t",
    )
    first_provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={existing.id: (1.0, 0.0)},
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[existing.id],
        embedding_version="embedding-v1",
        provider=first_provider,
    )

    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={missing.id: (0.0, 1.0)},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[existing.id, missing.id, empty.id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert result.generated == 1
    assert result.skipped == 2
    codes = {outcome.signal_id: outcome.code for outcome in result.outcomes}
    assert codes[existing.id] == "ALREADY_EMBEDDED"
    assert codes[empty.id] == "NO_EMBEDDABLE_TEXT"
    assert provider.calls == [(missing.id,)]


@pytest.mark.usefixtures("clean_database")
async def test_provider_wrong_result_count_fails_chunk_without_writes(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_signal(db_session, source, external_id="count-first")
    second = await create_signal(db_session, source, external_id="count-second")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={first.id: (1.0, 0.0), second.id: (0.0, 1.0)},
        truncate_results=True,
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[first.id, second.id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert result.failed == 2
    assert {item.code for item in result.outcomes} == {"INVALID_PROVIDER_RESPONSE"}
    assert await EmbeddingService(db_session).list_versions(first.id) == []
    assert await EmbeddingService(db_session).list_versions(second.id) == []


@pytest.mark.usefixtures("clean_database")
async def test_provider_result_dimension_mismatch_fails_without_writes(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="result-dimension")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        result_dimensions=3,
        vectors={signal.id: (1.0, 0.0)},
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id],
        embedding_version="embedding-v1",
        provider=provider,
    )
    assert result.failed == 1
    assert result.outcomes[0].code == "DIMENSION_MISMATCH"
    assert await EmbeddingService(db_session).list_versions(signal.id) == []


@pytest.mark.usefixtures("clean_database")
async def test_retryable_provider_failure_respects_attempt_boundary(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="retry-success")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal.id: (1.0, 0.0)},
        fail_times=1,
        retryable=True,
    )
    success = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id],
        embedding_version="embedding-v1",
        provider=provider,
        max_provider_attempts=2,
    )
    assert success.generated == 1
    assert len(provider.calls) == 2

    second = await create_signal(db_session, source, external_id="retry-fail")
    always_fails = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={second.id: (1.0, 0.0)},
        fail_times=3,
        retryable=True,
    )
    failed = await EmbeddingService(db_session).process_signals(
        signal_ids=[second.id],
        embedding_version="embedding-v1",
        provider=always_fails,
        max_provider_attempts=2,
    )
    assert failed.failed == 1
    assert failed.outcomes[0].code == "RETRYABLE_PROVIDER_FAILURE"
    assert failed.outcomes[0].retryable is True
    assert len(always_fails.calls) == 2


@pytest.mark.usefixtures("clean_database")
async def test_nonretryable_provider_failure_is_not_retried(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="nonretryable")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal.id: (1.0, 0.0)},
        fail_times=1,
        retryable=False,
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id],
        embedding_version="embedding-v1",
        provider=provider,
        max_provider_attempts=3,
    )
    assert result.failed == 1
    assert result.outcomes[0].code == "PROVIDER_FAILURE"
    assert len(provider.calls) == 1


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize("batch_size", [0, 1001])
async def test_invalid_batch_size_is_rejected(db_session, batch_size: int) -> None:  # type: ignore[no-untyped-def]
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={},
    )
    with pytest.raises(Exception, match="batch_size"):  # noqa: B017
        await EmbeddingService(db_session).process_signals(
            signal_ids=[],
            embedding_version="embedding-v1",
            provider=provider,
            batch_size=batch_size,
        )
