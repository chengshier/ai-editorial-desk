from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1c import (
    CollectionBudgetCreate,
    CollectionBudgetPage,
    CollectionBudgetResponse,
    CollectionBudgetUpdate,
)
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/collection-budgets",
    tags=["admin-collection-budgets"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("", response_model=CollectionBudgetResponse, status_code=201)
async def create_budget(
    payload: CollectionBudgetCreate,
    session: Session,
    actor: Actor,
) -> CollectionBudgetResponse:
    values = payload.model_dump(exclude={"scope_type", "scope_key"})
    budget = await CollectionBudgetService(session).create(
        scope_type=payload.scope_type,
        scope_key=payload.scope_key,
        values=values,
        actor=actor,
    )
    return CollectionBudgetResponse.model_validate(budget)


@router.get("", response_model=CollectionBudgetPage)
async def list_budgets(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    scope_type: str | None = None,
    enabled: bool | None = None,
) -> CollectionBudgetPage:
    result = await CollectionBudgetService(session).list(
        page=page,
        page_size=page_size,
        scope_type=scope_type,
        enabled=enabled,
    )
    return CollectionBudgetPage(
        items=[CollectionBudgetResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{budget_id}", response_model=CollectionBudgetResponse)
async def get_budget(
    budget_id: UUID,
    session: Session,
) -> CollectionBudgetResponse:
    return CollectionBudgetResponse.model_validate(
        await CollectionBudgetService(session).get(budget_id)
    )


@router.patch("/{budget_id}", response_model=CollectionBudgetResponse)
async def update_budget(
    budget_id: UUID,
    payload: CollectionBudgetUpdate,
    session: Session,
    actor: Actor,
) -> CollectionBudgetResponse:
    budget = await CollectionBudgetService(session).update(
        budget_id=budget_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return CollectionBudgetResponse.model_validate(budget)
