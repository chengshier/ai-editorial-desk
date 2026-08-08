from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m3a import (
    EventCreate,
    EventPage,
    EventResponse,
    EventSignalAttach,
    EventSignalPage,
    EventSignalResponse,
)
from apps.api.schemas.m3c import EventMergeRequest, EventSplitRequest
from packages.clustering.services import EventClusterMaintenanceService
from packages.database.models import EventStatus
from packages.database.session import get_database_session
from packages.events.services import EventService

router = APIRouter(
    prefix="/events",
    tags=["admin-events"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    payload: EventCreate,
    session: Session,
    actor: Actor,
) -> EventResponse:
    event = await EventService(session).create(
        title=payload.title,
        summary=payload.summary,
        category=payload.category,
        status=payload.status,
        primary_language=payload.primary_language,
        entities=payload.entities,
        keywords=payload.keywords,
        actor=actor,
    )
    return EventResponse.model_validate(event)


@router.get("", response_model=EventPage)
async def list_events(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: EventStatus | None = None,
    include_merged: bool = False,
) -> EventPage:
    result = await EventService(session).list(
        page=page,
        page_size=page_size,
        status=status.value if status is not None else None,
        include_merged=include_merged,
    )
    return EventPage(
        items=[EventResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: UUID, session: Session) -> EventResponse:
    return EventResponse.model_validate(await EventService(session).get(event_id))


@router.get("/{event_id}/signals", response_model=EventSignalPage)
async def list_event_signals(
    event_id: UUID,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EventSignalPage:
    result = await EventService(session).list_signals(
        event_id=event_id,
        page=page,
        page_size=page_size,
    )
    return EventSignalPage(
        items=[EventSignalResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.post("/{event_id}/signals", response_model=EventSignalResponse)
async def attach_event_signal(
    event_id: UUID,
    payload: EventSignalAttach,
    session: Session,
    actor: Actor,
) -> EventSignalResponse:
    association, _created = await EventService(session).attach_signal(
        event_id=event_id,
        signal_id=payload.signal_id,
        relation=payload.relation,
        confidence=payload.confidence,
        attached_by=payload.attached_by,
        actor=actor,
    )
    return EventSignalResponse.model_validate(association)


@router.delete("/{event_id}/signals/{signal_id}", status_code=204)
async def detach_event_signal(
    event_id: UUID,
    signal_id: UUID,
    session: Session,
    actor: Actor,
) -> Response:
    await EventService(session).detach_signal(
        event_id=event_id,
        signal_id=signal_id,
        actor=actor,
    )
    return Response(status_code=204)


@router.post("/{target_event_id}/merge", response_model=EventResponse)
async def merge_event(
    target_event_id: UUID,
    payload: EventMergeRequest,
    session: Session,
    actor: Actor,
) -> EventResponse:
    event = await EventClusterMaintenanceService(session).merge(
        target_event_id=target_event_id,
        source_event_id=payload.source_event_id,
        reason=payload.reason,
        actor=actor,
    )
    return EventResponse.model_validate(event)


@router.post("/{event_id}/split", response_model=EventResponse, status_code=201)
async def split_event(
    event_id: UUID,
    payload: EventSplitRequest,
    session: Session,
    actor: Actor,
) -> EventResponse:
    event = await EventClusterMaintenanceService(session).split(
        event_id=event_id,
        signal_ids=payload.signal_ids,
        title=payload.title,
        reason=payload.reason,
        actor=actor,
    )
    return EventResponse.model_validate(event)
