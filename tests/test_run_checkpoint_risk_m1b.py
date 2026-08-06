import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    InvalidStateTransitionError,
    VersionConflictError,
)
from packages.connector_management.services import (
    ConnectorCheckpointService,
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    ConnectorRunService,
    PlatformRiskEventService,
)
from packages.database.models import (
    ConnectorDefinition,
    ConnectorRunStatus,
    PlatformRiskEvent,
)
from packages.risk_guard.models import RiskAction


async def _instance(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "rss")
    )
    assert definition is not None
    await db_session.commit()
    return await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="运行实例",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={},
        actor="admin",
    )


@pytest.mark.usefixtures("clean_database")
async def test_run_state_machine_progress_and_metadata_redaction(db_session) -> None:  # type: ignore[no-untyped-def]
    instance = await _instance(db_session)
    service = ConnectorRunService(db_session)
    run = await service.create_pending(
        connector_instance_id=instance.id,
        platform_account_id=None,
        mode="feed",
        requested_limit=20,
        metadata={"Authorization": "Bearer secret", "source": "test"},
    )
    assert run.run_metadata["Authorization"] == "[REDACTED]"
    await service.transition(run_id=run.id, target_status=ConnectorRunStatus.RUNNING)
    updated = await service.update_progress(
        run_id=run.id,
        collected_count=10,
        inserted_count=8,
        duplicate_count=2,
        retry_count=1,
    )
    assert updated.inserted_count == 8
    completed = await service.transition(
        run_id=run.id,
        target_status=ConnectorRunStatus.SUCCEEDED,
    )
    assert completed.finished_at is not None
    with pytest.raises(InvalidStateTransitionError):
        await service.update_progress(
            run_id=run.id,
            collected_count=11,
            inserted_count=9,
            duplicate_count=2,
            retry_count=1,
        )


@pytest.mark.usefixtures("clean_database")
async def test_run_rejects_completion_before_start(db_session) -> None:  # type: ignore[no-untyped-def]
    instance = await _instance(db_session)
    service = ConnectorRunService(db_session)
    run = await service.create_pending(
        connector_instance_id=instance.id,
        platform_account_id=None,
        mode="feed",
        requested_limit=1,
    )
    running = await service.transition(
        run_id=run.id, target_status=ConnectorRunStatus.RUNNING
    )
    assert running.started_at is not None
    with pytest.raises(BusinessValidationError, match="完成时间不能早于开始时间"):
        await service.transition(
            run_id=run.id,
            target_status=ConnectorRunStatus.FAILED,
            finished_at=running.started_at - timedelta(seconds=1),
        )


@pytest.mark.usefixtures("clean_database")
async def test_checkpoint_create_update_and_version_conflict(db_session) -> None:  # type: ignore[no-untyped-def]
    instance = await _instance(db_session)
    service = ConnectorCheckpointService(db_session)
    first = await service.get_or_create(
        connector_instance_id=instance.id,
        platform_account_id=None,
        mode="feed",
        scope_key="public-feed",
    )
    again = await service.get_or_create(
        connector_instance_id=instance.id,
        platform_account_id=None,
        mode="feed",
        scope_key="public-feed",
    )
    assert first.id == again.id
    updated = await service.update(
        checkpoint_id=first.id,
        expected_version=1,
        cursor={"page": 2},
        watermark="2026-08-06",
        last_external_id="item-2",
        last_published_at=datetime.now(UTC),
        checkpoint_data={"seen": 2},
    )
    assert updated.version == 2
    with pytest.raises(VersionConflictError):
        await service.update(
            checkpoint_id=first.id,
            expected_version=1,
            cursor={"page": 3},
            watermark=None,
            last_external_id=None,
            last_published_at=None,
            checkpoint_data={},
        )


@pytest.mark.usefixtures("clean_database")
async def test_checkpoint_concurrent_expected_version_has_one_winner(db_session) -> None:  # type: ignore[no-untyped-def]
    instance = await _instance(db_session)
    checkpoint = await ConnectorCheckpointService(db_session).get_or_create(
        connector_instance_id=instance.id,
        platform_account_id=None,
        mode="feed",
        scope_key="concurrent",
    )
    from packages.database.session import get_async_sessionmaker

    async def update_once(value: int) -> str:
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            try:
                await ConnectorCheckpointService(session).update(
                    checkpoint_id=checkpoint.id,
                    expected_version=1,
                    cursor={"value": value},
                    watermark=None,
                    last_external_id=None,
                    last_published_at=None,
                    checkpoint_data={},
                )
            except VersionConflictError:
                return "conflict"
            return "updated"

    results = await asyncio.gather(update_once(1), update_once(2))
    assert sorted(results) == ["conflict", "updated"]


@pytest.mark.usefixtures("clean_database")
async def test_risk_event_filter_resolve_and_no_account_recovery(db_session) -> None:  # type: ignore[no-untyped-def]
    instance = await _instance(db_session)
    event = PlatformRiskEvent(
        connector_instance_id=instance.id,
        platform="rss",
        risk_type="permission_denied",
        risk_level="high",
        raw_error_code="403",
        standard_error_code="platform_restricted",
        message="permission denied",
        action_taken=RiskAction.REQUIRE_REVIEW,
        retryable=False,
        request_context={"Cookie": "secret", "url": "https://example.com"},
        response_context={"Authorization": "secret"},
        manual_review_required=True,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    event_id = event.id
    assert event.request_context["Cookie"] == "[REDACTED]"

    service = PlatformRiskEventService(db_session)
    page = await service.list(
        page=1,
        page_size=10,
        platform="rss",
        platform_account_id=None,
        risk_level="high",
        resolved=False,
        occurred_from=None,
        occurred_to=None,
    )
    assert page.total == 1
    await db_session.rollback()
    resolved = await service.resolve(
        event_id=event_id,
        resolution_note="已人工核对来源，无需恢复任何账号",
        actor="reviewer",
    )
    assert resolved.resolved_by == "reviewer"
    with pytest.raises(ConflictError):
        await service.resolve(
            event_id=event_id,
            resolution_note="重复处理",
            actor="reviewer",
        )
