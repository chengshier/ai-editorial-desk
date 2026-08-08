from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import ConnectorDefinition, RawSignalRecord
from packages.embeddings.exceptions import EmbeddingProviderError
from packages.embeddings.providers import (
    EmbeddingBatchResult,
    EmbeddingRequest,
)
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url


class MappingEmbeddingProvider:
    def __init__(
        self,
        *,
        embedding_version: str,
        dimensions: int,
        vectors: dict[UUID, tuple[float, ...]],
        provider_key: str = "test-provider",
        model_name: str = "test-model",
        fail_times: int = 0,
        retryable: bool = True,
        result_dimensions: int | None = None,
        truncate_results: bool = False,
    ) -> None:
        self.provider_key = provider_key
        self.model_name = model_name
        self.embedding_version = embedding_version
        self.dimensions = dimensions
        self.vectors = vectors
        self.fail_times = fail_times
        self.retryable = retryable
        self.result_dimensions = result_dimensions
        self.truncate_results = truncate_results
        self.calls: list[tuple[UUID, ...]] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        self.calls.append(tuple(item.signal_id for item in request.items))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmbeddingProviderError("test provider failure", retryable=self.retryable)
        vectors = tuple(self.vectors[item.signal_id] for item in request.items)
        if self.truncate_results and vectors:
            vectors = vectors[:-1]
        return EmbeddingBatchResult(
            provider_key=self.provider_key,
            model_name=self.model_name,
            embedding_version=self.embedding_version,
            dimensions=(
                self.result_dimensions
                if self.result_dimensions is not None
                else self.dimensions
            ),
            vectors=vectors,
            usage_metadata={"inputs": len(request.items)},
            latency_ms=1.0,
        )


async def create_source(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="M3-B RSS 实例",
        config={"feed_urls": ["https://example.com/m3b.xml"]},
        schedule_config={},
        actor="m3b-test",
    )
    return await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M3-B 来源",
        source_type="rss",
        mode="feed",
        scope_key="https://example.com/m3b.xml",
        external_ref="https://example.com/m3b.xml",
        config={},
        enabled=True,
        actor="m3b-test",
    )


async def create_signal(
    db_session,  # type: ignore[no-untyped-def]
    source,  # type: ignore[no-untyped-def]
    *,
    external_id: str,
    title: str | None = "M3-B 标题",
    text: str | None = "M3-B 正文",
    platform: str = "rss",
    published_at: datetime | None = None,
    collected_at: datetime | None = None,
) -> RawSignalRecord:
    published_at = published_at or datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    collected_at = collected_at or datetime(2026, 8, 8, 0, 1, tzinfo=UTC)
    raw = RawSignal(
        platform=platform,
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=title,
        text=text,
        published_at=published_at,
        raw_payload={"token": "m3b-secret", "safe": external_id},
        language="zh-CN",
    )
    normalized = NormalizedSignal.from_connector_signal(
        source_id=source.id,
        connector_instance_id=source.connector_instance_id,
        connector_run_id=None,
        connector_type="rss",
        signal=raw,
        canonical_url=normalize_http_url(raw.url),
    )
    result = (await RawSignalService(db_session).ingest_many([normalized]))[0]
    stored = await db_session.get(RawSignalRecord, result.signal_id)
    assert stored is not None
    stored.collected_at = collected_at
    await db_session.commit()
    return stored
