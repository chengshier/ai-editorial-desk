import httpx
import pytest

from apps.api.main import app
from packages.common.config import get_settings
from packages.embeddings.services import EmbeddingService
from tests.m3b_helpers import MappingEmbeddingProvider, create_signal, create_source

ADMIN_HEADERS = {"X-Admin-Token": get_settings().admin_token_value}


@pytest.mark.usefixtures("clean_database")
async def test_embedding_admin_api_requires_admin_token() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        metadata = await client.get(
            "/api/v1/admin/embeddings/signals/00000000-0000-0000-0000-000000000001"
        )
        recall = await client.post(
            "/api/v1/admin/embeddings/recall",
            json={
                "signal_id": "00000000-0000-0000-0000-000000000001",
                "embedding_version": "embedding-v1",
            },
        )
    assert metadata.status_code == 401
    assert recall.status_code == 401


@pytest.mark.usefixtures("clean_database")
async def test_embedding_metadata_api_never_returns_vector(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="metadata-api")
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={signal.id: (1.0, 0.0)},
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[signal.id],
        embedding_version="embedding-v1",
        provider=provider,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/admin/embeddings/signals/{signal.id}",
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["signal_id"] == str(signal.id)
    assert len(body["items"]) == 1
    metadata = body["items"][0]
    assert metadata["embedding_version"] == "embedding-v1"
    assert metadata["provider_key"] == "test-provider"
    assert metadata["model_name"] == "test-model"
    assert metadata["dimensions"] == 2
    assert len(metadata["input_hash"]) == 64
    assert "embedding" not in metadata
    assert "vector" not in response.text.casefold()


@pytest.mark.usefixtures("clean_database")
async def test_similarity_recall_api_returns_safe_candidates(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    target = await create_signal(db_session, source, external_id="api-target")
    candidate = await create_signal(
        db_session,
        source,
        external_id="api-candidate",
        platform="weibo",
    )
    provider = MappingEmbeddingProvider(
        embedding_version="embedding-v1",
        dimensions=2,
        vectors={target.id: (1.0, 0.0), candidate.id: (0.9, 0.1)},
    )
    await EmbeddingService(db_session).process_signals(
        signal_ids=[target.id, candidate.id],
        embedding_version="embedding-v1",
        provider=provider,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/admin/embeddings/recall",
            headers=ADMIN_HEADERS,
            json={
                "signal_id": str(target.id),
                "embedding_version": "embedding-v1",
                "top_k": 5,
                "min_similarity": 0.5,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["signal_id"] == str(target.id)
    assert [item["candidate_signal_id"] for item in body["candidates"]] == [
        str(candidate.id)
    ]
    assert body["candidates"][0]["similarity"] > 0.9
    assert body["candidates"][0]["platform"] == "weibo"
    assert "raw_payload" not in response.text
    assert "embedding" not in body["candidates"][0]


@pytest.mark.usefixtures("clean_database")
async def test_similarity_recall_api_validates_inputs_and_missing_embedding(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_signal(db_session, source, external_id="api-validation")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post(
            "/api/v1/admin/embeddings/recall",
            headers=ADMIN_HEADERS,
            json={
                "signal_id": str(signal.id),
                "embedding_version": "embedding-v1",
                "top_k": 0,
            },
        )
        missing = await client.post(
            "/api/v1/admin/embeddings/recall",
            headers=ADMIN_HEADERS,
            json={
                "signal_id": str(signal.id),
                "embedding_version": "embedding-v1",
                "top_k": 10,
            },
        )
    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"
