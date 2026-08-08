from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from packages.clustering.services import EventClusteringService
from packages.connectors.base import RawSignal
from packages.database.models import RawSignalRecord
from packages.embeddings.services import EmbeddingService
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService
from packages.signals.urls import normalize_http_url
from tests.m3b_helpers import MappingEmbeddingProvider, create_source


async def create_m3c_signal(
    db_session,  # type: ignore[no-untyped-def]
    source,  # type: ignore[no-untyped-def]
    *,
    external_id: str,
    title: str | None,
    text: str | None,
    url: str | None = None,
    platform: str = "rss",
    connector_type: str = "rss",
    published_at: datetime | None = None,
    collected_at: datetime | None = None,
) -> RawSignalRecord:
    published_at = published_at or datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    collected_at = collected_at or datetime(2026, 8, 8, 1, 1, tzinfo=UTC)
    raw = RawSignal(
        platform=platform,
        external_id=external_id,
        url=url or f"https://example.com/m3c/{external_id}",
        title=title,
        text=text,
        published_at=published_at,
        raw_payload={"credential": "m3c-secret", "safe": external_id},
        language="zh-CN",
    )
    normalized = NormalizedSignal.from_connector_signal(
        source_id=source.id,
        connector_instance_id=source.connector_instance_id,
        connector_run_id=None,
        connector_type=connector_type,
        signal=raw,
        canonical_url=normalize_http_url(raw.url),
    )
    result = (await RawSignalService(db_session).ingest_many([normalized]))[0]
    stored = await db_session.get(RawSignalRecord, result.signal_id)
    assert stored is not None
    stored.collected_at = collected_at
    await db_session.commit()
    return stored


async def add_test_embeddings(
    db_session,  # type: ignore[no-untyped-def]
    *,
    embedding_version: str,
    vectors: dict[UUID, tuple[float, ...]],
) -> None:
    dimensions = len(next(iter(vectors.values())))
    provider = MappingEmbeddingProvider(
        embedding_version=embedding_version,
        dimensions=dimensions,
        vectors=vectors,
    )
    summary = await EmbeddingService(db_session).process_signals(
        signal_ids=list(vectors),
        embedding_version=embedding_version,
        provider=provider,
    )
    assert summary.failed == 0


async def auto_cluster(
    db_session,  # type: ignore[no-untyped-def]
    signal_id: UUID,
    *,
    embedding_version: str | None = None,
):  # type: ignore[no-untyped-def]
    return await EventClusteringService(db_session).cluster_signal(
        signal_id=signal_id,
        embedding_version=embedding_version,
        actor="m3c-test",
    )


__all__ = [
    "add_test_embeddings",
    "auto_cluster",
    "create_m3c_signal",
    "create_source",
]
