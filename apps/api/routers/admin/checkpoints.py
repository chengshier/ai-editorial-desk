from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1d import CheckpointPage, CheckpointResetRequest, CheckpointResponse
from packages.database.session import get_database_session
from packages.scheduling.admin import CheckpointDebugService

router = APIRouter(
    prefix="/checkpoints",
    tags=["admin-checkpoints"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("", response_model=CheckpointPage)
async def list_checkpoints(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_instance_id: UUID | None = None,
    source_id: UUID | None = None,
    platform_account_id: UUID | None = None,
    mode: str | None = None,
    scope_key: str | None = None,
) -> CheckpointPage:
    result = await CheckpointDebugService(session).list(
        page=page,
        page_size=page_size,
        connector_instance_id=connector_instance_id,
        source_id=source_id,
        platform_account_id=platform_account_id,
        mode=mode,
        scope_key=scope_key,
    )
    return CheckpointPage(
        items=[CheckpointResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{checkpoint_id}", response_model=CheckpointResponse)
async def get_checkpoint(checkpoint_id: UUID, session: Session) -> CheckpointResponse:
    return CheckpointResponse.from_orm_model(
        await CheckpointDebugService(session).get(checkpoint_id)
    )


@router.post("/{checkpoint_id}/reset", response_model=CheckpointResponse)
async def reset_checkpoint(
    checkpoint_id: UUID,
    payload: CheckpointResetRequest,
    session: Session,
    actor: Actor,
) -> CheckpointResponse:
    checkpoint = await CheckpointDebugService(session).reset(
        checkpoint_id=checkpoint_id,
        expected_version=payload.expected_version,
        reason=payload.reason,
        actor=actor,
    )
    return CheckpointResponse.from_orm_model(checkpoint)
