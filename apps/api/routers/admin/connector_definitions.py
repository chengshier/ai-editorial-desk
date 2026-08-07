from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_admin_token
from apps.api.schemas.m1c import (
    ConnectorDefinitionRuntimePage,
    ConnectorDefinitionRuntimeResponse,
)
from packages.connector_management.services import ConnectorDefinitionQueryService
from packages.connectors.implementations import implementation_registry
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/connector-definitions",
    tags=["admin-connector-definitions"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get("", response_model=ConnectorDefinitionRuntimePage)
async def list_definitions(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_type: str | None = None,
    platform: str | None = None,
    is_enabled: bool | None = None,
) -> ConnectorDefinitionRuntimePage:
    result = await ConnectorDefinitionQueryService(session).list(
        page=page,
        page_size=page_size,
        connector_type=connector_type,
        platform=platform,
        is_enabled=is_enabled,
    )
    return ConnectorDefinitionRuntimePage(
        items=[
            ConnectorDefinitionRuntimeResponse.from_orm_model(
                item,
                implementation_registry,
            )
            for item in result.items
        ],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{definition_id}", response_model=ConnectorDefinitionRuntimeResponse)
async def get_definition(
    definition_id: UUID,
    session: Session,
) -> ConnectorDefinitionRuntimeResponse:
    item = await ConnectorDefinitionQueryService(session).get(definition_id)
    return ConnectorDefinitionRuntimeResponse.from_orm_model(
        item,
        implementation_registry,
    )
