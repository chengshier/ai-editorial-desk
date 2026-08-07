from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.routers.admin.collector_runtime import get_collector_runtime
from apps.api.schemas.m1c import (
    ConnectorRunRuntimePage,
    ConnectorRunRuntimeResponse,
    TestRunResponse,
)
from apps.api.schemas.m1d import RunActionRequest, RunDebugPage, RunDebugResponse
from packages.collector_runtime import CollectorRuntime
from packages.connector_management.services import ConnectorRunService
from packages.database.models import ConnectorRunStatus
from packages.database.session import get_database_session
from packages.scheduling.admin import RunRecoveryService

router = APIRouter(
    prefix="/connector-runs",
    tags=["admin-connector-runs"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]
Runtime = Annotated[CollectorRuntime, Depends(get_collector_runtime)]


@router.get("", response_model=ConnectorRunRuntimePage)
async def list_runs(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_instance_id: UUID | None = None,
    platform_account_id: UUID | None = None,
    source_id: UUID | None = None,
    status: ConnectorRunStatus | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> ConnectorRunRuntimePage:
    result = await ConnectorRunService(session).list(
        page=page,
        page_size=page_size,
        connector_instance_id=connector_instance_id,
        platform_account_id=platform_account_id,
        source_id=source_id,
        status=status,
        started_from=started_from,
        started_to=started_to,
    )
    return ConnectorRunRuntimePage(
        items=[ConnectorRunRuntimeResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/stale", response_model=RunDebugPage)
async def list_stale_runs(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    stale_seconds: Annotated[int, Query(ge=300, le=86400)] = 1800,
) -> RunDebugPage:
    result = await RunRecoveryService(session).list_stale(
        page=page, page_size=page_size, stale_seconds=stale_seconds
    )
    return RunDebugPage(
        items=[RunDebugResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{run_id}", response_model=RunDebugResponse)
async def get_run(run_id: UUID, session: Session) -> RunDebugResponse:
    return RunDebugResponse.from_orm_model(await ConnectorRunService(session).get(run_id))


@router.post("/{run_id}/retry", response_model=TestRunResponse)
async def retry_run(
    run_id: UUID,
    session: Session,
    actor: Actor,
    runtime: Runtime,
) -> TestRunResponse:
    task = await RunRecoveryService(session).build_retry_task(run_id=run_id, actor=actor)
    await session.rollback()
    result = await runtime.execute(task)
    return TestRunResponse(
        run_id=result.run_id,
        status=result.status,
        signal_ids=list(result.signal_ids),
        collected_count=result.collected_count,
        inserted_count=result.inserted_count,
        duplicate_count=result.duplicate_count,
        failed_count=result.failed_count,
        fetch_status=result.fetch_status,
    )


@router.post("/{run_id}/cancel", response_model=RunDebugResponse)
async def cancel_run(
    run_id: UUID, payload: RunActionRequest, session: Session, actor: Actor
) -> RunDebugResponse:
    del actor
    run = await ConnectorRunService(session).get(run_id)
    await session.rollback()
    cancelled = await ConnectorRunService(session).finalize(
        run_id=run.id,
        target_status=ConnectorRunStatus.CANCELLED,
        error_code="cancelled_by_admin",
        error_message=payload.reason,
    )
    return RunDebugResponse.from_orm_model(cancelled)


@router.post("/{run_id}/mark-failed", response_model=RunDebugResponse)
async def mark_run_failed(
    run_id: UUID, payload: RunActionRequest, session: Session, actor: Actor
) -> RunDebugResponse:
    del actor
    failed = await RunRecoveryService(session).mark_failed(
        run_id=run_id, reason=payload.reason
    )
    return RunDebugResponse.from_orm_model(failed)
