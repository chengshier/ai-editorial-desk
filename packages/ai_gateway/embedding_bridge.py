from __future__ import annotations

from packages.ai_gateway.domain import InvocationContext
from packages.ai_gateway.errors import AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.connector_management.exceptions import BusinessValidationError
from packages.embeddings.exceptions import EmbeddingProviderError
from packages.embeddings.providers import EmbeddingBatchResult, EmbeddingRequest


class GatewayEmbeddingProvider:
    """M4 production bridge that preserves the existing M3-B EmbeddingProvider contract."""

    def __init__(
        self,
        *,
        gateway: AIGateway,
        provider_key: str,
        model_name: str,
        embedding_version: str,
        dimensions: int,
    ) -> None:
        self.gateway = gateway
        self._provider_key = provider_key
        self._model_name = model_name
        self._embedding_version = embedding_version
        self._dimensions = dimensions

    @classmethod
    async def from_active_route(
        cls,
        *,
        gateway: AIGateway,
        embedding_version: str,
    ) -> GatewayEmbeddingProvider:
        snapshot = await gateway.route_snapshot(
            task_key="embedding",
            capability="embedding",
            primary_only=True,
        )
        target = snapshot.targets[0]
        configured_version = target.model_config.get("embedding_version")
        if configured_version != embedding_version:
            raise BusinessValidationError(
                "embedding route 主模型必须显式声明与请求一致的 embedding_version"
            )
        if target.dimensions is None or target.dimensions <= 0:
            raise BusinessValidationError("embedding route 主模型必须声明 dimensions")
        return cls(
            gateway=gateway,
            provider_key=target.provider_key,
            model_name=target.model_name,
            embedding_version=embedding_version,
            dimensions=target.dimensions,
        )

    @property
    def provider_key(self) -> str:
        return self._provider_key

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def embedding_version(self) -> str:
        return self._embedding_version

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        if request.embedding_version != self.embedding_version:
            raise EmbeddingProviderError(
                "Gateway embedding_version 与 M3-B 请求不一致",
                retryable=False,
            )
        try:
            result = await self.gateway.embed(
                task_key="embedding",
                texts=tuple(item.text for item in request.items),
                context=InvocationContext(
                    prompt_version=None,
                    schema_version=request.input_schema_version,
                    metadata={"embedding_version": request.embedding_version},
                ),
                primary_only=True,
            )
        except AIGatewayError as exc:
            raise EmbeddingProviderError(
                f"AI Gateway embedding 调用失败: {exc.code.value}",
                retryable=exc.retryable,
            ) from exc
        if result.provider_key != self.provider_key or result.model_name != self.model_name:
            raise EmbeddingProviderError(
                "embedding route 在 Provider 生命周期内发生变化，请重建 GatewayEmbeddingProvider",
                retryable=False,
            )
        if any(len(vector) != self.dimensions for vector in result.vectors):
            raise EmbeddingProviderError("AI Gateway 返回 dimensions 不一致", retryable=False)
        usage_metadata: dict[str, int | float | str] = {
            "invocation_id": str(result.invocation_id),
        }
        if result.usage.input_tokens is not None:
            usage_metadata["input_tokens"] = result.usage.input_tokens
        if result.usage.output_tokens is not None:
            usage_metadata["output_tokens"] = result.usage.output_tokens
        if result.usage.total_tokens is not None:
            usage_metadata["total_tokens"] = result.usage.total_tokens
        if result.estimated_cost is not None:
            usage_metadata["estimated_cost"] = str(result.estimated_cost)
        return EmbeddingBatchResult(
            provider_key=self.provider_key,
            model_name=self.model_name,
            embedding_version=self.embedding_version,
            dimensions=self.dimensions,
            vectors=result.vectors,
            usage_metadata=usage_metadata,
        )
