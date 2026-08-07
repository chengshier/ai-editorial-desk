from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_admin_token
from apps.api.schemas.m1d import SchedulerStatusResponse
from packages.database.session import get_database_session
from packages.scheduling.admin import SchedulerStatusService

router = APIRouter(
    prefix="/scheduler",
    tags=["admin-scheduler"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get("/status", response_model=SchedulerStatusResponse)
async def scheduler_status(session: Session) -> SchedulerStatusResponse:
    return SchedulerStatusResponse.model_validate(
        await SchedulerStatusService(session).snapshot()
    )
