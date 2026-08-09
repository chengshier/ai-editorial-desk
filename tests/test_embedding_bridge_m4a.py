from __future__ import annotations

import httpx
import pytest

from packages.ai_gateway.embedding_bridge import GatewayEmbeddingProvider
from packages.ai_gateway.gateway import AIGateway
from packages.database.models import SignalEmbeddingRecord
from packages.database.session import get_async_sessionmaker
from packages.embeddings.repositories import SignalEmbeddingRepository
from packages.embeddings.services import EmbeddingService
from tests.m3b_helpers import create_signal, create_source
from tests.m4a_helpers import create_ai_stack, mock_factory


@pytest.mark.usefixtures("clean_database")
async def test_gateway_embedding_bridge_preserves_m3b_signal_embedding_semantics(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(
        db_session,
        source,
        external_id="m4a-gateway-embedding",
        title="AI Gateway embedding",
        text="M3-B must remain the persistence owner",
    )
    await create_ai_stack(
        db_session,
        task_key="embedding",
        primary_name="embedding-vendor-model",
        capability="embedding",
        embedding_version="embedding-m4a-v1",
        dimensions=3,
    )

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "id": "embedding-request-1",
                "data": [{"index": 0, "embedding": [1.0, 0.25, 0.5]}],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    provider = await GatewayEmbeddingProvider.from_active_route(
        gateway=gateway,
        embedding_version="embedding-m4a-v1",
    )
    result = await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id],
        embedding_version="embedding-m4a-v1",
        provider=provider,
    )
    assert result.generated == 1
    assert result.failed == 0
    assert calls == 1

    stored = await SignalEmbeddingRepository(db_session).get(signal.id, "embedding-m4a-v1")
    assert isinstance(stored, SignalEmbeddingRecord)
    assert stored.provider_key == "test-provider"
    assert stored.model_name == "embedding-vendor-model"
    assert stored.dimensions == 3
    assert len(stored.input_hash) == 64
    assert tuple(float(value) for value in stored.embedding) == (1.0, 0.25, 0.5)
