from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.domain import AIModelTarget, AIRouteSnapshot
from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.database.models import AIModelRecord, AIProviderRecord, AITaskRouteRecord


class AIRouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_snapshot(
        self,
        *,
        task_key: str,
        capability: str,
        primary_only: bool = False,
    ) -> AIRouteSnapshot:
        route = await self.session.scalar(
            select(AITaskRouteRecord).where(
                AITaskRouteRecord.task_key == task_key,
                AITaskRouteRecord.is_active.is_(True),
            )
        )
        if route is None or not route.enabled or route.primary_model_id is None:
            raise AIGatewayError(
                AIErrorCode.ROUTE_NOT_CONFIGURED,
                f"AI task route 未启用或未配置主模型: {task_key}",
            )
        model_ids = [route.primary_model_id]
        if not primary_only:
            for raw_id in route.fallback_model_ids:
                try:
                    model_id = UUID(str(raw_id))
                except ValueError as exc:
                    raise AIGatewayError(
                        AIErrorCode.ROUTE_NOT_CONFIGURED,
                        "AI route fallback model id 无效",
                    ) from exc
                if model_id not in model_ids:
                    model_ids.append(model_id)
        targets = tuple(
            [await self._target(model_id=model_id, capability=capability) for model_id in model_ids]
        )
        return AIRouteSnapshot(
            route_id=route.id,
            task_key=route.task_key,
            version=route.version,
            timeout_seconds=route.timeout_seconds,
            retry_limit=route.retry_limit,
            budget_policy=dict(route.budget_policy),
            config=dict(route.config),
            targets=targets,
        )

    async def _target(self, *, model_id: UUID, capability: str) -> AIModelTarget:
        model = await self.session.get(AIModelRecord, model_id)
        if model is None:
            raise AIGatewayError(AIErrorCode.MODEL_NOT_FOUND, "AI route 引用了不存在的模型")
        if not model.enabled:
            raise AIGatewayError(AIErrorCode.MODEL_DISABLED, "AI route 引用了停用模型")
        if capability not in model.capabilities:
            raise AIGatewayError(
                AIErrorCode.CAPABILITY_NOT_SUPPORTED,
                f"AI 模型不支持 capability: {capability}",
            )
        provider = await self.session.get(AIProviderRecord, model.provider_id)
        if provider is None:
            raise AIGatewayError(AIErrorCode.PROVIDER_UNAVAILABLE, "AI 模型 Provider 不存在")
        if not provider.enabled:
            raise AIGatewayError(AIErrorCode.PROVIDER_DISABLED, "AI 模型 Provider 已停用")
        return AIModelTarget(
            model_id=model.id,
            provider_id=provider.id,
            provider_key=provider.provider_key,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            credential_ref=provider.credential_ref,
            provider_timeout_seconds=provider.timeout_seconds,
            provider_retry_limit=provider.retry_limit,
            provider_config=dict(provider.config),
            model_key=model.model_key,
            model_name=model.model_name,
            capabilities=tuple(str(value) for value in model.capabilities),
            dimensions=model.dimensions,
            input_price_per_million=model.input_price_per_million,
            output_price_per_million=model.output_price_per_million,
            embedding_price_per_million=model.embedding_price_per_million,
            pricing_version=model.pricing_version,
            model_config=dict(model.config),
        )
