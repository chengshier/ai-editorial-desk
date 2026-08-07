from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_admin_token
from apps.api.schemas.m1c import RawSignalPage, RawSignalResponse
from packages.database.session import get_database_session
from packages.signals.services import RawSignalService

router = APIRouter(
    prefix="/raw-signals",
    tags=["admin-raw-signals"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get("", response_model=RawSignalPage)
async def list_raw_signals(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    source_id: UUID | None = None,
    connector_instance_id: UUID | None = None,
    connector_run_id: UUID | None = None,
    platform: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
) -> RawSignalPage:
    result = await RawSignalService(session).list(
        page=page,
        page_size=page_size,
        source_id=source_id,
        connector_instance_id=connector_instance_id,
        connector_run_id=connector_run_id,
        platform=platform,
        published_from=published_from,
        published_to=published_to,
    )
    return RawSignalPage(
        items=[RawSignalResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{signal_id}", response_model=RawSignalResponse)
async def get_raw_signal(signal_id: UUID, session: Session) -> RawSignalResponse:
    return RawSignalResponse.from_orm_model(
        await RawSignalService(session).get(signal_id)
    )
