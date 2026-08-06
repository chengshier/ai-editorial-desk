from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_admin_token
from apps.api.schemas.admin import ConnectorRunPage, ConnectorRunResponse
from packages.connector_management.services import ConnectorRunService
from packages.database.models import ConnectorRunStatus
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/connector-runs",
    tags=["admin-connector-runs"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get("", response_model=ConnectorRunPage)
async def list_runs(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_instance_id: UUID | None = None,
    platform_account_id: UUID | None = None,
    status: ConnectorRunStatus | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> ConnectorRunPage:
    result = await ConnectorRunService(session).list(
        page=page,
        page_size=page_size,
        connector_instance_id=connector_instance_id,
        platform_account_id=platform_account_id,
        status=status,
        started_from=started_from,
        started_to=started_to,
    )
    return ConnectorRunPage(
        items=[ConnectorRunResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{run_id}", response_model=ConnectorRunResponse)
async def get_run(run_id: UUID, session: Session) -> ConnectorRunResponse:
    run = await ConnectorRunService(session).get(run_id)
    return ConnectorRunResponse.from_orm_model(run)
