from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1c import (
    ManualImportRequest,
    ManualImportResponse,
    TestRunRequest,
    TestRunResponse,
)
from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.collector_runtime.manual_imports import ManualImportService
from packages.connector_management.exceptions import ConflictError
from packages.connectors.implementations import implementation_registry
from packages.database.session import get_async_sessionmaker, get_database_session
from packages.signals.services import SourceService

router = APIRouter(
    tags=["admin-collector-runtime"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


def get_collector_runtime() -> CollectorRuntime:
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=implementation_registry,
    )


Runtime = Annotated[CollectorRuntime, Depends(get_collector_runtime)]


@router.post(
    "/connector-instances/{instance_id}/test-runs",
    response_model=TestRunResponse,
)
async def run_connector_test(
    instance_id: UUID,
    payload: TestRunRequest,
    session: Session,
    actor: Actor,
    runtime: Runtime,
) -> TestRunResponse:
    source = await SourceService(session).get(payload.source_id)
    if source.connector_instance_id != instance_id:
        raise ConflictError("来源不属于指定连接器实例")
    mode = source.mode
    await session.rollback()
    result = await runtime.execute(
        CollectionTask(
            task_id=uuid4(),
            connector_instance_id=instance_id,
            source_id=payload.source_id,
            platform_account_id=payload.platform_account_id,
            mode=mode,
            requested_limit=payload.requested_limit,
            checkpoint_version=payload.expected_checkpoint_version,
            trigger_type=TriggerType.TEST,
            triggered_by=actor,
            created_at=datetime.now(UTC),
            dry_run=payload.dry_run,
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


@router.post("/manual-imports", response_model=ManualImportResponse)
async def import_manual_url(
    payload: ManualImportRequest,
    actor: Actor,
    runtime: Runtime,
) -> ManualImportResponse:
    outcome = await ManualImportService(
        session_factory=get_async_sessionmaker(),
        runtime=runtime,
    ).execute(
        connector_instance_id=payload.connector_instance_id,
        url=payload.url,
        title=payload.title,
        text=payload.text,
        note=payload.note,
        fetch_metadata=payload.fetch_metadata,
        actor=actor,
    )
    if not outcome.runtime.signal_ids:
        raise ConflictError("手工 URL 未生成可查询的原始信号")
    return ManualImportResponse(
        run_id=outcome.runtime.run_id,
        signal_id=outcome.runtime.signal_ids[0],
        duplicate=(
            outcome.runtime.inserted_count == 0
            and outcome.runtime.duplicate_count > 0
        ),
        normalized_url=outcome.normalized_url,
        fetch_status=outcome.runtime.fetch_status,
    )
