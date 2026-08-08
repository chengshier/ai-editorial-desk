from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EmbeddingRequestItem:
    signal_id: UUID
    text: str
    input_hash: str


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    embedding_version: str
    input_schema_version: str
    items: tuple[EmbeddingRequestItem, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    provider_key: str
    model_name: str
    embedding_version: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]
    usage_metadata: Mapping[str, int | float | str] | None = None
    latency_ms: float | None = None
    error_metadata: Mapping[str, int | float | str] | None = None


class EmbeddingProvider(Protocol):
    """M3-B-only provider contract; general AI routing belongs to M4."""

    @property
    def provider_key(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def embedding_version(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult: ...
