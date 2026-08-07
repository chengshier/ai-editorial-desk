from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1c import TestRunResponse
from apps.api.schemas.m1d import (
    PauseScheduleRequest,
    RunNowRequest,
    ScheduleCreate,
    SchedulePage,
    ScheduleResponse,
    ScheduleUpdate,
)
from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.connectors.implementations import implementation_registry
from packages.database.models import Source
from packages.database.session import get_async_sessionmaker, get_database_session
from packages.scheduling.admin import ScheduleAdminService

router = APIRouter(
    prefix="/schedules",
    tags=["admin-schedules"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


def get_runtime() -> CollectorRuntime:
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(), registry=implementation_registry
    )


Runtime = Annotated[CollectorRuntime, Depends(get_runtime)]


@router.get("", response_model=SchedulePage)
async def list_schedules(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    enabled: bool | None = None,
    source_id: UUID | None = None,
) -> SchedulePage:
    result = await ScheduleAdminService(session).list(
        page=page, page_size=page_size, enabled=enabled, source_id=source_id
    )
    return SchedulePage(
        items=[ScheduleResponse.model_validate(item, from_attributes=True) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(schedule_id: UUID, session: Session) -> ScheduleResponse:
    return ScheduleResponse.model_validate(
        await ScheduleAdminService(session).get(schedule_id), from_attributes=True
    )


@router.post("", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    payload: ScheduleCreate, session: Session, actor: Actor
) -> ScheduleResponse:
    schedule = await ScheduleAdminService(session).create(
        connector_instance_id=payload.connector_instance_id,
        source_id=payload.source_id,
        platform_account_id=payload.platform_account_id,
        name=payload.name,
        schedule_type=payload.schedule_type,
        interval_seconds=payload.interval_seconds,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        requested_limit=payload.requested_limit,
        actor=actor,
    )
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID, payload: ScheduleUpdate, session: Session, actor: Actor
) -> ScheduleResponse:
    schedule = await ScheduleAdminService(session).update(
        schedule_id=schedule_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.post("/{schedule_id}/pause", response_model=ScheduleResponse)
async def pause_schedule(
    schedule_id: UUID, payload: PauseScheduleRequest, session: Session, actor: Actor
) -> ScheduleResponse:
    schedule = await ScheduleAdminService(session).pause(
        schedule_id=schedule_id, actor=actor, reason=payload.reason
    )
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.post("/{schedule_id}/resume", response_model=ScheduleResponse)
async def resume_schedule(schedule_id: UUID, session: Session, actor: Actor) -> ScheduleResponse:
    schedule = await ScheduleAdminService(session).resume(schedule_id=schedule_id, actor=actor)
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.post("/{schedule_id}/run-now", response_model=TestRunResponse)
async def run_schedule_now(
    schedule_id: UUID,
    payload: RunNowRequest,
    session: Session,
    actor: Actor,
    runtime: Runtime,
) -> TestRunResponse:
    schedule = await ScheduleAdminService(session).get(schedule_id)
    source = await session.get(Source, schedule.source_id)
    if source is None:
        from packages.connector_management.exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("调度对应 Source 不存在")
    requested_limit = payload.requested_limit or schedule.requested_limit
    await session.rollback()
    result = await runtime.execute(
        CollectionTask(
            task_id=uuid4(),
            connector_instance_id=schedule.connector_instance_id,
            source_id=schedule.source_id,
            platform_account_id=schedule.platform_account_id,
            mode=source.mode,
            requested_limit=requested_limit,
            checkpoint_version=None,
            trigger_type=TriggerType.MANUAL,
            triggered_by=actor,
            created_at=datetime.now(UTC),
        )
    )
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
