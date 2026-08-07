from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1c import SourceCreate, SourcePage, SourceResponse, SourceUpdate
from packages.database.session import get_database_session
from packages.signals.services import SourceService

router = APIRouter(
    prefix="/sources",
    tags=["admin-sources"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    payload: SourceCreate,
    session: Session,
    actor: Actor,
) -> SourceResponse:
    source = await SourceService(session).create(
        connector_instance_id=payload.connector_instance_id,
        name=payload.name,
        source_type=payload.source_type,
        mode=payload.mode,
        scope_key=payload.scope_key,
        external_ref=payload.external_ref,
        config=payload.config,
        enabled=payload.enabled,
        actor=actor,
    )
    return SourceResponse.model_validate(source)


@router.get("", response_model=SourcePage)
async def list_sources(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_instance_id: UUID | None = None,
    source_type: str | None = None,
    enabled: bool | None = None,
    status: str | None = None,
) -> SourcePage:
    result = await SourceService(session).list(
        page=page,
        page_size=page_size,
        connector_instance_id=connector_instance_id,
        source_type=source_type,
        enabled=enabled,
        status=status,
    )
    return SourcePage(
        items=[SourceResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(source_id: UUID, session: Session) -> SourceResponse:
    return SourceResponse.model_validate(await SourceService(session).get(source_id))


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    payload: SourceUpdate,
    session: Session,
    actor: Actor,
) -> SourceResponse:
    source = await SourceService(session).update(
        source_id=source_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return SourceResponse.model_validate(source)


@router.post("/{source_id}/archive", response_model=SourceResponse)
async def archive_source(
    source_id: UUID,
    session: Session,
    actor: Actor,
) -> SourceResponse:
    return SourceResponse.model_validate(
        await SourceService(session).archive(source_id=source_id, actor=actor)
    )
