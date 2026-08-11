from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.structured_output import structured_output_mode
from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import AuditLogRepository, Page
from packages.database.models import (
    AIBudgetRecord,
    AIInvocationAttemptRecord,
    AIInvocationRecord,
    AIModelRecord,
    AIProviderRecord,
    AITaskRouteRecord,
)
from packages.database.types import is_sensitive_key

_PROVIDER_TYPES = frozenset({"openai_compatible", "local_openai_compatible"})
_CAPABILITIES = frozenset(
    {"embedding", "text_generation", "structured_output", "vision", "audio"}
)
_ENV_REF = re.compile(r"^env://[A-Z][A-Z0-9_]{1,127}$")


def _safe_config(config: dict[str, Any]) -> dict[str, Any]:
    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if is_sensitive_key(str(key)):
                    raise BusinessValidationError("Provider/Model config 禁止包含 credential 或 secret")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(config)
    return config


def _safe_model_config(config: dict[str, Any]) -> dict[str, Any]:
    safe_config = _safe_config(config)
    try:
        structured_output_mode(safe_config)
    except ValueError as exc:
        raise BusinessValidationError(str(exc)) from exc
    return safe_config


def _validate_credential_ref(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if _ENV_REF.fullmatch(normalized) is None:
        raise BusinessValidationError("M4-A credential_ref 仅支持 env://UPPER_CASE_NAME")
    return normalized


def _validate_base_url(base_url: str, config: dict[str, Any]) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BusinessValidationError("Provider base_url 仅允许有效 http/https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BusinessValidationError("Provider base_url 禁止 userinfo/query/fragment")
    if parsed.scheme == "http" and not bool(config.get("allow_insecure_http", False)):
        raise BusinessValidationError("HTTP Provider 必须显式配置 allow_insecure_http=true")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ) and not bool(config.get("allow_private_network", False)):
        raise BusinessValidationError("私网 Provider 必须显式配置 allow_private_network=true")
    return normalized


def _provider_snapshot(provider: AIProviderRecord) -> dict[str, Any]:
    return {
        "provider_key": provider.provider_key,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "credential_configured": bool(provider.credential_ref),
        "enabled": provider.enabled,
        "validation_status": provider.validation_status,
        "timeout_seconds": provider.timeout_seconds,
        "max_concurrency": provider.max_concurrency,
        "retry_limit": provider.retry_limit,
        "config": provider.config,
    }


def _model_snapshot(model: AIModelRecord) -> dict[str, Any]:
    return {
        "provider_id": str(model.provider_id),
        "model_key": model.model_key,
        "model_name": model.model_name,
        "capabilities": model.capabilities,
        "enabled": model.enabled,
        "context_window": model.context_window,
        "input_price_per_million": str(model.input_price_per_million)
        if model.input_price_per_million is not None
        else None,
        "output_price_per_million": str(model.output_price_per_million)
        if model.output_price_per_million is not None
        else None,
        "embedding_price_per_million": str(model.embedding_price_per_million)
        if model.embedding_price_per_million is not None
        else None,
        "pricing_version": model.pricing_version,
        "dimensions": model.dimensions,
        "config": model.config,
    }


def _route_snapshot(route: AITaskRouteRecord) -> dict[str, Any]:
    return {
        "task_key": route.task_key,
        "version": route.version,
        "primary_model_id": str(route.primary_model_id) if route.primary_model_id else None,
        "fallback_model_ids": route.fallback_model_ids,
        "timeout_seconds": route.timeout_seconds,
        "retry_limit": route.retry_limit,
        "budget_policy": route.budget_policy,
        "config": route.config,
        "enabled": route.enabled,
        "is_active": route.is_active,
    }


def _budget_snapshot(budget: AIBudgetRecord) -> dict[str, Any]:
    return {
        "scope_type": budget.scope_type,
        "scope_key": budget.scope_key,
        "enabled": budget.enabled,
        "daily_cost_limit": str(budget.daily_cost_limit)
        if budget.daily_cost_limit is not None
        else None,
        "monthly_cost_limit": str(budget.monthly_cost_limit)
        if budget.monthly_cost_limit is not None
        else None,
        "daily_token_limit": budget.daily_token_limit,
        "unknown_usage_policy": budget.unknown_usage_policy,
        "config": budget.config,
    }


class AIManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditLogRepository(session)

    async def create_provider(self, *, values: dict[str, Any], actor: str) -> AIProviderRecord:
        provider_key = str(values["provider_key"]).strip()
        provider_type = str(values["provider_type"]).strip()
        if provider_type not in _PROVIDER_TYPES:
            raise BusinessValidationError("当前仅支持 OpenAI-compatible Provider protocol")
        config = _safe_config(dict(values.get("config") or {}))
        base_url = _validate_base_url(str(values["base_url"]), config)
        credential_ref = _validate_credential_ref(values.get("credential_ref"))
        async with self.session.begin():
            duplicate = await self.session.scalar(
                select(AIProviderRecord).where(AIProviderRecord.provider_key == provider_key)
            )
            if duplicate is not None:
                raise ConflictError("provider_key 已存在")
            provider = AIProviderRecord(
                provider_key=provider_key,
                display_name=str(values["display_name"]).strip(),
                provider_type=provider_type,
                base_url=base_url,
                credential_ref=credential_ref,
                enabled=bool(values.get("enabled", False)),
                timeout_seconds=int(values.get("timeout_seconds", 30)),
                max_concurrency=int(values.get("max_concurrency", 4)),
                retry_limit=int(values.get("retry_limit", 1)),
                config=config,
                created_by=actor,
                updated_by=actor,
            )
            self.session.add(provider)
            await self.session.flush()
            self.audit.add(
                entity_type="ai_provider",
                entity_id=provider.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_provider_snapshot(provider),
            )
        return provider

    async def get_provider(self, provider_id: UUID) -> AIProviderRecord:
        provider = await self.session.get(AIProviderRecord, provider_id)
        if provider is None:
            raise ResourceNotFoundError("AI Provider 不存在")
        return provider

    async def list_providers(self, *, page: int, page_size: int) -> Page[AIProviderRecord]:
        total = int(await self.session.scalar(select(func.count()).select_from(AIProviderRecord)) or 0)
        items = list(
            (
                await self.session.scalars(
                    select(AIProviderRecord)
                    .order_by(AIProviderRecord.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def update_provider(
        self,
        *,
        provider_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> AIProviderRecord:
        async with self.session.begin():
            provider = await self.session.get(AIProviderRecord, provider_id, with_for_update=True)
            if provider is None:
                raise ResourceNotFoundError("AI Provider 不存在")
            before = _provider_snapshot(provider)
            config = dict(provider.config)
            if "config" in changes and changes["config"] is not None:
                config = _safe_config(dict(changes["config"]))
                provider.config = config
            if "display_name" in changes and changes["display_name"] is not None:
                provider.display_name = str(changes["display_name"]).strip()
            if "base_url" in changes and changes["base_url"] is not None:
                provider.base_url = _validate_base_url(str(changes["base_url"]), config)
            elif "config" in changes:
                provider.base_url = _validate_base_url(provider.base_url, config)
            if "replace_credential_ref" in changes:
                provider.credential_ref = _validate_credential_ref(changes["replace_credential_ref"])
                provider.validation_status = "NOT_TESTED"
                provider.last_validated_at = None
            for field in ("timeout_seconds", "max_concurrency", "retry_limit"):
                if field in changes and changes[field] is not None:
                    setattr(provider, field, int(changes[field]))
            provider.updated_by = actor
            after = _provider_snapshot(provider)
            if after != before:
                self.audit.add(
                    entity_type="ai_provider",
                    entity_id=provider.id,
                    action="update",
                    actor=actor,
                    before_data=before,
                    after_data=after,
                )
        return provider

    async def set_provider_enabled(
        self,
        *,
        provider_id: UUID,
        enabled: bool,
        actor: str,
    ) -> AIProviderRecord:
        async with self.session.begin():
            provider = await self.session.get(AIProviderRecord, provider_id, with_for_update=True)
            if provider is None:
                raise ResourceNotFoundError("AI Provider 不存在")
            before = _provider_snapshot(provider)
            provider.enabled = enabled
            provider.updated_by = actor
            if before != _provider_snapshot(provider):
                self.audit.add(
                    entity_type="ai_provider",
                    entity_id=provider.id,
                    action="enable" if enabled else "disable",
                    actor=actor,
                    before_data=before,
                    after_data=_provider_snapshot(provider),
                )
        return provider

    async def create_model(self, *, values: dict[str, Any], actor: str) -> AIModelRecord:
        capabilities = _validate_capabilities(values.get("capabilities"))
        config = _safe_model_config(dict(values.get("config") or {}))
        async with self.session.begin():
            provider = await self.session.get(AIProviderRecord, values["provider_id"])
            if provider is None:
                raise ResourceNotFoundError("AI Provider 不存在")
            duplicate = await self.session.scalar(
                select(AIModelRecord).where(
                    AIModelRecord.provider_id == provider.id,
                    AIModelRecord.model_key == str(values["model_key"]).strip(),
                )
            )
            if duplicate is not None:
                raise ConflictError("同一 Provider 下 model_key 已存在")
            model = AIModelRecord(
                provider_id=provider.id,
                model_key=str(values["model_key"]).strip(),
                model_name=str(values["model_name"]).strip(),
                capabilities=capabilities,
                enabled=bool(values.get("enabled", False)),
                context_window=values.get("context_window"),
                input_price_per_million=values.get("input_price_per_million"),
                output_price_per_million=values.get("output_price_per_million"),
                embedding_price_per_million=values.get("embedding_price_per_million"),
                pricing_version=str(values.get("pricing_version", "unpriced-v1")).strip(),
                dimensions=values.get("dimensions"),
                config=config,
                created_by=actor,
                updated_by=actor,
            )
            if "embedding" in capabilities and model.dimensions is None:
                raise BusinessValidationError("Embedding model 必须声明 dimensions")
            self.session.add(model)
            await self.session.flush()
            self.audit.add(
                entity_type="ai_model",
                entity_id=model.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_model_snapshot(model),
            )
        return model

    async def get_model(self, model_id: UUID) -> AIModelRecord:
        model = await self.session.get(AIModelRecord, model_id)
        if model is None:
            raise ResourceNotFoundError("AI Model 不存在")
        return model

    async def list_models(
        self,
        *,
        page: int,
        page_size: int,
        provider_id: UUID | None = None,
    ) -> Page[AIModelRecord]:
        filters = [] if provider_id is None else [AIModelRecord.provider_id == provider_id]
        total = int(
            await self.session.scalar(select(func.count()).select_from(AIModelRecord).where(*filters))
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(AIModelRecord)
                    .where(*filters)
                    .order_by(AIModelRecord.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def update_model(
        self,
        *,
        model_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> AIModelRecord:
        async with self.session.begin():
            model = await self.session.get(AIModelRecord, model_id, with_for_update=True)
            if model is None:
                raise ResourceNotFoundError("AI Model 不存在")
            before = _model_snapshot(model)
            if "capabilities" in changes and changes["capabilities"] is not None:
                model.capabilities = _validate_capabilities(changes["capabilities"])
            if "config" in changes and changes["config"] is not None:
                model.config = _safe_model_config(dict(changes["config"]))
            for field in (
                "model_name",
                "context_window",
                "input_price_per_million",
                "output_price_per_million",
                "embedding_price_per_million",
                "pricing_version",
                "dimensions",
            ):
                if field in changes:
                    setattr(model, field, changes[field])
            if "embedding" in model.capabilities and model.dimensions is None:
                raise BusinessValidationError("Embedding model 必须声明 dimensions")
            model.updated_by = actor
            if before != _model_snapshot(model):
                self.audit.add(
                    entity_type="ai_model",
                    entity_id=model.id,
                    action="update",
                    actor=actor,
                    before_data=before,
                    after_data=_model_snapshot(model),
                )
        return model

    async def set_model_enabled(
        self,
        *,
        model_id: UUID,
        enabled: bool,
        actor: str,
    ) -> AIModelRecord:
        async with self.session.begin():
            model = await self.session.get(AIModelRecord, model_id, with_for_update=True)
            if model is None:
                raise ResourceNotFoundError("AI Model 不存在")
            before = _model_snapshot(model)
            model.enabled = enabled
            model.updated_by = actor
            if before != _model_snapshot(model):
                self.audit.add(
                    entity_type="ai_model",
                    entity_id=model.id,
                    action="enable" if enabled else "disable",
                    actor=actor,
                    before_data=before,
                    after_data=_model_snapshot(model),
                )
        return model

    async def list_routes(self, *, page: int, page_size: int) -> Page[AITaskRouteRecord]:
        predicate = AITaskRouteRecord.is_active.is_(True)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AITaskRouteRecord).where(predicate)
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(AITaskRouteRecord)
                    .where(predicate)
                    .order_by(AITaskRouteRecord.task_key)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def get_route(self, task_key: str) -> AITaskRouteRecord:
        route = await self.session.scalar(
            select(AITaskRouteRecord).where(
                AITaskRouteRecord.task_key == task_key,
                AITaskRouteRecord.is_active.is_(True),
            )
        )
        if route is None:
            raise ResourceNotFoundError("AI Route 不存在")
        return route

    async def update_route(
        self,
        *,
        task_key: str,
        values: dict[str, Any],
        actor: str,
    ) -> AITaskRouteRecord:
        async with self.session.begin():
            current = await self.session.scalar(
                select(AITaskRouteRecord)
                .where(
                    AITaskRouteRecord.task_key == task_key,
                    AITaskRouteRecord.is_active.is_(True),
                )
                .with_for_update()
            )
            if current is None:
                raise ResourceNotFoundError("AI Route 不存在")
            before = _route_snapshot(current)
            primary_model_id = values.get("primary_model_id")
            fallback_ids = list(dict.fromkeys(values.get("fallback_model_ids") or []))
            if primary_model_id in fallback_ids:
                fallback_ids.remove(primary_model_id)
            await self._validate_route_models(
                primary_model_id=primary_model_id,
                fallback_model_ids=fallback_ids,
                enabled=bool(values.get("enabled", False)),
            )
            current.is_active = False
            await self.session.flush()
            route = AITaskRouteRecord(
                task_key=task_key,
                version=current.version + 1,
                primary_model_id=primary_model_id,
                fallback_model_ids=[str(value) for value in fallback_ids],
                timeout_seconds=int(values.get("timeout_seconds", 30)),
                retry_limit=int(values.get("retry_limit", 1)),
                budget_policy=_safe_config(dict(values.get("budget_policy") or {})),
                config=_safe_config(dict(values.get("config") or {})),
                enabled=bool(values.get("enabled", False)),
                is_active=True,
                created_by=actor,
            )
            self.session.add(route)
            await self.session.flush()
            self.audit.add(
                entity_type="ai_task_route",
                entity_id=route.id,
                action="version_update",
                actor=actor,
                before_data=before,
                after_data=_route_snapshot(route),
            )
        return route

    async def _validate_route_models(
        self,
        *,
        primary_model_id: UUID | None,
        fallback_model_ids: list[UUID],
        enabled: bool,
    ) -> None:
        if enabled and primary_model_id is None:
            raise BusinessValidationError("启用 AI Route 前必须配置 primary model")
        for model_id in ([primary_model_id] if primary_model_id is not None else []) + fallback_model_ids:
            model = await self.session.get(AIModelRecord, model_id)
            if model is None:
                raise ResourceNotFoundError("AI Route 引用了不存在的 Model")
            if enabled:
                provider = await self.session.get(AIProviderRecord, model.provider_id)
                if not model.enabled or provider is None or not provider.enabled:
                    raise ConflictError("启用 Route 前 Provider 与 Model 必须均为 enabled")

    async def create_budget(self, *, values: dict[str, Any], actor: str) -> AIBudgetRecord:
        scope_type = str(values["scope_type"])
        scope_key = str(values["scope_key"]).strip()
        if scope_type == "global" and scope_key != "global":
            raise BusinessValidationError("global budget 的 scope_key 必须为 global")
        async with self.session.begin():
            duplicate = await self.session.scalar(
                select(AIBudgetRecord).where(
                    AIBudgetRecord.scope_type == scope_type,
                    AIBudgetRecord.scope_key == scope_key,
                )
            )
            if duplicate is not None:
                raise ConflictError("AI Budget scope 已存在")
            budget = AIBudgetRecord(
                scope_type=scope_type,
                scope_key=scope_key,
                enabled=bool(values.get("enabled", True)),
                daily_cost_limit=values.get("daily_cost_limit"),
                monthly_cost_limit=values.get("monthly_cost_limit"),
                daily_token_limit=values.get("daily_token_limit"),
                unknown_usage_policy=str(values.get("unknown_usage_policy", "block")),
                config=_safe_config(dict(values.get("config") or {})),
                updated_by=actor,
            )
            self.session.add(budget)
            await self.session.flush()
            self.audit.add(
                entity_type="ai_budget",
                entity_id=budget.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_budget_snapshot(budget),
            )
        return budget

    async def list_budgets(self, *, page: int, page_size: int) -> Page[AIBudgetRecord]:
        total = int(await self.session.scalar(select(func.count()).select_from(AIBudgetRecord)) or 0)
        items = list(
            (
                await self.session.scalars(
                    select(AIBudgetRecord)
                    .order_by(AIBudgetRecord.scope_type, AIBudgetRecord.scope_key)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def update_budget(
        self,
        *,
        budget_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> AIBudgetRecord:
        async with self.session.begin():
            budget = await self.session.get(AIBudgetRecord, budget_id, with_for_update=True)
            if budget is None:
                raise ResourceNotFoundError("AI Budget 不存在")
            before = _budget_snapshot(budget)
            for field in (
                "enabled",
                "daily_cost_limit",
                "monthly_cost_limit",
                "daily_token_limit",
                "unknown_usage_policy",
            ):
                if field in changes:
                    setattr(budget, field, changes[field])
            if "config" in changes and changes["config"] is not None:
                budget.config = _safe_config(dict(changes["config"]))
            budget.updated_by = actor
            if before != _budget_snapshot(budget):
                self.audit.add(
                    entity_type="ai_budget",
                    entity_id=budget.id,
                    action="update",
                    actor=actor,
                    before_data=before,
                    after_data=_budget_snapshot(budget),
                )
        return budget

    async def list_invocations(
        self,
        *,
        page: int,
        page_size: int,
        task_key: str | None = None,
        status: str | None = None,
    ) -> Page[AIInvocationRecord]:
        filters = []
        if task_key:
            filters.append(AIInvocationRecord.task_key == task_key)
        if status:
            filters.append(AIInvocationRecord.status == status)
        total = int(
            await self.session.scalar(select(func.count()).select_from(AIInvocationRecord).where(*filters))
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(AIInvocationRecord)
                    .where(*filters)
                    .order_by(AIInvocationRecord.started_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def invocation_detail(
        self,
        invocation_id: UUID,
    ) -> tuple[AIInvocationRecord, list[AIInvocationAttemptRecord]]:
        invocation = await self.session.get(AIInvocationRecord, invocation_id)
        if invocation is None:
            raise ResourceNotFoundError("AI Invocation 不存在")
        attempts = list(
            (
                await self.session.scalars(
                    select(AIInvocationAttemptRecord)
                    .where(AIInvocationAttemptRecord.invocation_id == invocation_id)
                    .order_by(AIInvocationAttemptRecord.attempt_no)
                )
            ).all()
        )
        return invocation, attempts

    async def provider_stats(
        self, provider_id: UUID, provider_key: str
    ) -> tuple[int, Any, float | None]:
        model_count = int(
            await self.session.scalar(
                select(func.count()).select_from(AIModelRecord).where(AIModelRecord.provider_id == provider_id)
            )
            or 0
        )
        last_invocation = await self.session.scalar(
            select(func.max(AIInvocationRecord.started_at)).where(
                AIInvocationRecord.provider_key == provider_key
            )
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AIInvocationRecord).where(
                    AIInvocationRecord.provider_key == provider_key
                )
            )
            or 0
        )
        if total == 0:
            return model_count, last_invocation, None
        failures = int(
            await self.session.scalar(
                select(func.count()).select_from(AIInvocationRecord).where(
                    AIInvocationRecord.provider_key == provider_key,
                    AIInvocationRecord.status == "failed",
                )
            )
            or 0
        )
        return model_count, last_invocation, failures / total


def _validate_capabilities(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise BusinessValidationError("capabilities 必须是列表")
    capabilities = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if not capabilities or any(item not in _CAPABILITIES for item in capabilities):
        raise BusinessValidationError("AI Model capability 无效")
    return capabilities
