from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.admin import (
    PlatformRiskEventPage,
    PlatformRiskEventResolve,
    PlatformRiskEventResponse,
)
from packages.connector_management.services import PlatformRiskEventService
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/platform-risk-events",
    tags=["admin-platform-risk-events"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("", response_model=PlatformRiskEventPage)
async def list_risk_events(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    platform: str | None = None,
    platform_account_id: UUID | None = None,
    risk_level: str | None = None,
    resolved: bool | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> PlatformRiskEventPage:
    result = await PlatformRiskEventService(session).list(
        page=page,
        page_size=page_size,
        platform=platform,
        platform_account_id=platform_account_id,
        risk_level=risk_level,
        resolved=resolved,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    return PlatformRiskEventPage(
        items=[PlatformRiskEventResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{event_id}", response_model=PlatformRiskEventResponse)
async def get_risk_event(event_id: UUID, session: Session) -> PlatformRiskEventResponse:
    event = await PlatformRiskEventService(session).get(event_id)
    return PlatformRiskEventResponse.from_orm_model(event)


@router.post("/{event_id}/resolve", response_model=PlatformRiskEventResponse)
async def resolve_risk_event(
    event_id: UUID,
    payload: PlatformRiskEventResolve,
    session: Session,
    actor: Actor,
) -> PlatformRiskEventResponse:
    event = await PlatformRiskEventService(session).resolve(
        event_id=event_id,
        resolution_note=payload.resolution_note,
        actor=actor,
    )
    return PlatformRiskEventResponse.from_orm_model(event)
