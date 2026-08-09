from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def known(self) -> bool:
        return self.total_tokens is not None or (
            self.input_tokens is not None and self.output_tokens is not None
        )


@dataclass(frozen=True, slots=True)
class AIModelTarget:
    model_id: UUID
    provider_id: UUID
    provider_key: str
    provider_type: str
    base_url: str
    credential_ref: str | None
    provider_timeout_seconds: int
    provider_retry_limit: int
    provider_config: dict[str, Any]
    model_key: str
    model_name: str
    capabilities: tuple[str, ...]
    dimensions: int | None
    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
    embedding_price_per_million: Decimal | None
    pricing_version: str
    model_config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AIRouteSnapshot:
    route_id: UUID
    task_key: str
    version: int
    timeout_seconds: int
    retry_limit: int
    budget_policy: dict[str, Any]
    config: dict[str, Any]
    targets: tuple[AIModelTarget, ...]


@dataclass(frozen=True, slots=True)
class AIMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class EmbeddingProviderRequest:
    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextProviderRequest:
    messages: tuple[AIMessage, ...]
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class StructuredProviderRequest:
    messages: tuple[AIMessage, ...]
    schema: dict[str, Any]
    schema_name: str
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingProviderResponse:
    vectors: tuple[tuple[float, ...], ...]
    usage: AIUsage = field(default_factory=AIUsage)
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class TextProviderResponse:
    text: str
    usage: AIUsage = field(default_factory=AIUsage)
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredProviderResponse:
    data: dict[str, Any]
    usage: AIUsage = field(default_factory=AIUsage)
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class InvocationContext:
    prompt_version: str | None = None
    schema_version: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    test: bool = False


@dataclass(frozen=True, slots=True)
class GatewayEmbeddingResult:
    invocation_id: UUID
    provider_key: str
    model_name: str
    vectors: tuple[tuple[float, ...], ...]
    usage: AIUsage
    estimated_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class GatewayTextResult:
    invocation_id: UUID
    provider_key: str
    model_name: str
    text: str
    usage: AIUsage
    estimated_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class GatewayStructuredResult:
    invocation_id: UUID
    provider_key: str
    model_name: str
    data: dict[str, Any]
    usage: AIUsage
    estimated_cost: Decimal | None


AI_CAPABILITIES = frozenset({"embedding", "text_generation", "structured_output"})
