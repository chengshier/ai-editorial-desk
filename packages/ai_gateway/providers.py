from __future__ import annotations

from typing import Protocol

from packages.ai_gateway.domain import (
    AIModelTarget,
    EmbeddingProviderRequest,
    EmbeddingProviderResponse,
    StructuredProviderRequest,
    StructuredProviderResponse,
    TextProviderRequest,
    TextProviderResponse,
)


class EmbeddingGenerationProvider(Protocol):
    async def embed(
        self,
        *,
        target: AIModelTarget,
        request: EmbeddingProviderRequest,
        timeout_seconds: float,
    ) -> EmbeddingProviderResponse: ...


class TextGenerationProvider(Protocol):
    async def generate_text(
        self,
        *,
        target: AIModelTarget,
        request: TextProviderRequest,
        timeout_seconds: float,
    ) -> TextProviderResponse: ...


class StructuredGenerationProvider(Protocol):
    async def generate_structured(
        self,
        *,
        target: AIModelTarget,
        request: StructuredProviderRequest,
        timeout_seconds: float,
    ) -> StructuredProviderResponse: ...


class AIProviderAdapter(
    EmbeddingGenerationProvider,
    TextGenerationProvider,
    StructuredGenerationProvider,
    Protocol,
):
    """Provider adapters operate only on gateway domain objects, never business ORM rows."""


class ProviderAdapterFactory(Protocol):
    def build(self, provider_type: str) -> AIProviderAdapter: ...
