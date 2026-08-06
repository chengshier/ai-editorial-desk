from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.admin import (
    ConnectorInstanceCreate,
    ConnectorInstancePage,
    ConnectorInstanceResponse,
    ConnectorInstanceUpdate,
)
from packages.connector_management.services import ConnectorInstanceService
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/connector-instances",
    tags=["admin-connector-instances"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("", response_model=ConnectorInstanceResponse, status_code=201)
async def create_instance(
    payload: ConnectorInstanceCreate,
    session: Session,
    actor: Actor,
) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).create(
        definition_id=payload.definition_id,
        name=payload.name,
        config=payload.config,
        schedule_config=payload.schedule_config,
        actor=actor,
    )
    return ConnectorInstanceResponse.from_orm_model(instance)


@router.get("", response_model=ConnectorInstancePage)
async def list_instances(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    definition_id: UUID | None = None,
    enabled: bool | None = None,
    status: str | None = None,
) -> ConnectorInstancePage:
    result = await ConnectorInstanceService(session).list(
        page=page,
        page_size=page_size,
        definition_id=definition_id,
        enabled=enabled,
        status=status,
    )
    return ConnectorInstancePage(
        items=[ConnectorInstanceResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{instance_id}", response_model=ConnectorInstanceResponse)
async def get_instance(instance_id: UUID, session: Session) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).get(instance_id)
    return ConnectorInstanceResponse.from_orm_model(instance)


@router.patch("/{instance_id}", response_model=ConnectorInstanceResponse)
async def update_instance(
    instance_id: UUID,
    payload: ConnectorInstanceUpdate,
    session: Session,
    actor: Actor,
) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).update(
        instance_id=instance_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return ConnectorInstanceResponse.from_orm_model(instance)


@router.post("/{instance_id}/enable", response_model=ConnectorInstanceResponse)
async def enable_instance(
    instance_id: UUID, session: Session, actor: Actor
) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).enable(
        instance_id=instance_id, actor=actor
    )
    return ConnectorInstanceResponse.from_orm_model(instance)


@router.post("/{instance_id}/disable", response_model=ConnectorInstanceResponse)
async def disable_instance(
    instance_id: UUID, session: Session, actor: Actor
) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).disable(
        instance_id=instance_id, actor=actor
    )
    return ConnectorInstanceResponse.from_orm_model(instance)


@router.post("/{instance_id}/archive", response_model=ConnectorInstanceResponse)
async def archive_instance(
    instance_id: UUID, session: Session, actor: Actor
) -> ConnectorInstanceResponse:
    instance = await ConnectorInstanceService(session).archive(
        instance_id=instance_id, actor=actor
    )
    return ConnectorInstanceResponse.from_orm_model(instance)
