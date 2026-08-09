from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m4a import (
    AIBudgetCreate,
    AIBudgetPage,
    AIBudgetResponse,
    AIBudgetUpdate,
    AIConnectionTestRequest,
    AIConnectionTestResponse,
    AIInvocationAttemptResponse,
    AIInvocationDetail,
    AIInvocationPage,
    AIInvocationResponse,
    AIModelCreate,
    AIModelPage,
    AIModelResponse,
    AIModelUpdate,
    AIProviderCreate,
    AIProviderPage,
    AIProviderResponse,
    AIProviderUpdate,
    AITaskRoutePage,
    AITaskRouteResponse,
    AITaskRouteUpdate,
)
from packages.ai_gateway.connection_test import AIConnectionTester
from packages.ai_gateway.credentials import EnvironmentCredentialResolver, credential_ref_mask
from packages.ai_gateway.management import AIManagementService
from packages.database.models import AIProviderRecord, AITaskRouteRecord
from packages.database.session import get_async_sessionmaker, get_database_session

router = APIRouter(
    prefix="/ai",
    tags=["admin-ai"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


async def _provider_response(
    service: AIManagementService,
    provider: AIProviderRecord,
) -> AIProviderResponse:
    model_count, last_invocation_at, error_rate = await service.provider_stats(
        provider.id,
        provider.provider_key,
    )
    resolver = EnvironmentCredentialResolver()
    return AIProviderResponse(
        id=provider.id,
        provider_key=provider.provider_key,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        credential_configured=resolver.configured(provider.credential_ref),
        credential_ref_masked=credential_ref_mask(provider.credential_ref),
        enabled=provider.enabled,
        validation_status=provider.validation_status,
        last_validated_at=provider.last_validated_at,
        timeout_seconds=provider.timeout_seconds,
        max_concurrency=provider.max_concurrency,
        retry_limit=provider.retry_limit,
        config=provider.config,
        model_count=model_count,
        last_invocation_at=last_invocation_at,
        error_rate=error_rate,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _route_response(route: AITaskRouteRecord) -> AITaskRouteResponse:
    return AITaskRouteResponse(
        id=route.id,
        task_key=route.task_key,
        version=route.version,
        primary_model_id=route.primary_model_id,
        fallback_model_ids=[UUID(str(value)) for value in route.fallback_model_ids],
        timeout_seconds=route.timeout_seconds,
        retry_limit=route.retry_limit,
        budget_policy=route.budget_policy,
        config=route.config,
        enabled=route.enabled,
        is_active=route.is_active,
        created_at=route.created_at,
    )


@router.get("/providers", response_model=AIProviderPage)
async def list_providers(
    session: Session,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> AIProviderPage:
    service = AIManagementService(session)
    result = await service.list_providers(page=page, page_size=page_size)
    items = [await _provider_response(service, provider) for provider in result.items]
    return AIProviderPage(
        items=items,
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.post("/providers", response_model=AIProviderResponse, status_code=201)
async def create_provider(
    payload: AIProviderCreate,
    session: Session,
    actor: Actor,
) -> AIProviderResponse:
    service = AIManagementService(session)
    provider = await service.create_provider(
        values=payload.model_dump(),
        actor=actor,
    )
    return await _provider_response(service, provider)


@router.get("/providers/{provider_id}", response_model=AIProviderResponse)
async def get_provider(provider_id: UUID, session: Session) -> AIProviderResponse:
    service = AIManagementService(session)
    provider = await service.get_provider(provider_id)
    return await _provider_response(service, provider)


@router.patch("/providers/{provider_id}", response_model=AIProviderResponse)
async def update_provider(
    provider_id: UUID,
    payload: AIProviderUpdate,
    session: Session,
    actor: Actor,
) -> AIProviderResponse:
    service = AIManagementService(session)
    provider = await service.update_provider(
        provider_id=provider_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return await _provider_response(service, provider)


@router.post("/providers/{provider_id}/enable", response_model=AIProviderResponse)
async def enable_provider(provider_id: UUID, session: Session, actor: Actor) -> AIProviderResponse:
    service = AIManagementService(session)
    provider = await service.set_provider_enabled(
        provider_id=provider_id,
        enabled=True,
        actor=actor,
    )
    return await _provider_response(service, provider)


@router.post("/providers/{provider_id}/disable", response_model=AIProviderResponse)
async def disable_provider(provider_id: UUID, session: Session, actor: Actor) -> AIProviderResponse:
    service = AIManagementService(session)
    provider = await service.set_provider_enabled(
        provider_id=provider_id,
        enabled=False,
        actor=actor,
    )
    return await _provider_response(service, provider)


@router.post("/providers/{provider_id}/test", response_model=AIConnectionTestResponse)
async def test_provider(
    provider_id: UUID,
    payload: AIConnectionTestRequest,
    actor: Actor,
) -> AIConnectionTestResponse:
    invocation_id, status, error_code = await AIConnectionTester(
        get_async_sessionmaker()
    ).test(
        provider_id=provider_id,
        model_id=payload.model_id,
        actor=actor,
    )
    return AIConnectionTestResponse(
        invocation_id=invocation_id,
        status=status,
        error_code=error_code,
    )


@router.get("/models", response_model=AIModelPage)
async def list_models(
    session: Session,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    provider_id: UUID | None = None,
) -> AIModelPage:
    result = await AIManagementService(session).list_models(
        page=page,
        page_size=page_size,
        provider_id=provider_id,
    )
    return AIModelPage(
        items=[AIModelResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.post("/models", response_model=AIModelResponse, status_code=201)
async def create_model(
    payload: AIModelCreate,
    session: Session,
    actor: Actor,
) -> AIModelResponse:
    model = await AIManagementService(session).create_model(
        values=payload.model_dump(),
        actor=actor,
    )
    return AIModelResponse.model_validate(model)


@router.patch("/models/{model_id}", response_model=AIModelResponse)
async def update_model(
    model_id: UUID,
    payload: AIModelUpdate,
    session: Session,
    actor: Actor,
) -> AIModelResponse:
    model = await AIManagementService(session).update_model(
        model_id=model_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return AIModelResponse.model_validate(model)


@router.post("/models/{model_id}/enable", response_model=AIModelResponse)
async def enable_model(model_id: UUID, session: Session, actor: Actor) -> AIModelResponse:
    model = await AIManagementService(session).set_model_enabled(
        model_id=model_id,
        enabled=True,
        actor=actor,
    )
    return AIModelResponse.model_validate(model)


@router.post("/models/{model_id}/disable", response_model=AIModelResponse)
async def disable_model(model_id: UUID, session: Session, actor: Actor) -> AIModelResponse:
    model = await AIManagementService(session).set_model_enabled(
        model_id=model_id,
        enabled=False,
        actor=actor,
    )
    return AIModelResponse.model_validate(model)


@router.get("/routes", response_model=AITaskRoutePage)
async def list_routes(
    session: Session,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> AITaskRoutePage:
    result = await AIManagementService(session).list_routes(page=page, page_size=page_size)
    return AITaskRoutePage(
        items=[_route_response(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/routes/{task_key}", response_model=AITaskRouteResponse)
async def get_route(task_key: str, session: Session) -> AITaskRouteResponse:
    return _route_response(await AIManagementService(session).get_route(task_key))


@router.put("/routes/{task_key}", response_model=AITaskRouteResponse)
async def update_route(
    task_key: str,
    payload: AITaskRouteUpdate,
    session: Session,
    actor: Actor,
) -> AITaskRouteResponse:
    route = await AIManagementService(session).update_route(
        task_key=task_key,
        values=payload.model_dump(),
        actor=actor,
    )
    return _route_response(route)


@router.get("/budgets", response_model=AIBudgetPage)
async def list_budgets(
    session: Session,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> AIBudgetPage:
    result = await AIManagementService(session).list_budgets(page=page, page_size=page_size)
    return AIBudgetPage(
        items=[AIBudgetResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.post("/budgets", response_model=AIBudgetResponse, status_code=201)
async def create_budget(
    payload: AIBudgetCreate,
    session: Session,
    actor: Actor,
) -> AIBudgetResponse:
    budget = await AIManagementService(session).create_budget(
        values=payload.model_dump(),
        actor=actor,
    )
    return AIBudgetResponse.model_validate(budget)


@router.patch("/budgets/{budget_id}", response_model=AIBudgetResponse)
async def update_budget(
    budget_id: UUID,
    payload: AIBudgetUpdate,
    session: Session,
    actor: Actor,
) -> AIBudgetResponse:
    budget = await AIManagementService(session).update_budget(
        budget_id=budget_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return AIBudgetResponse.model_validate(budget)


@router.get("/invocations", response_model=AIInvocationPage)
async def list_invocations(
    session: Session,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    task_key: str | None = None,
    status: str | None = None,
) -> AIInvocationPage:
    result = await AIManagementService(session).list_invocations(
        page=page,
        page_size=page_size,
        task_key=task_key,
        status=status,
    )
    return AIInvocationPage(
        items=[AIInvocationResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/invocations/{invocation_id}", response_model=AIInvocationDetail)
async def invocation_detail(invocation_id: UUID, session: Session) -> AIInvocationDetail:
    invocation, attempts = await AIManagementService(session).invocation_detail(invocation_id)
    base = AIInvocationResponse.model_validate(invocation)
    return AIInvocationDetail(
        **base.model_dump(),
        attempts=[AIInvocationAttemptResponse.model_validate(item) for item in attempts],
    )
