from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.exceptions import BudgetExceededError, PreflightRejectedError
from packages.connector_management.exceptions import (
    BusinessValidationError,
    VersionConflictError,
)
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    ConnectorRunService,
    PlatformAccountService,
)
from packages.connectors.base import BaseConnector, CollectionResult, CollectRequest, RawSignal
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    CollectionSchedule,
    CollectionScheduleTrigger,
    ConfigurationChangeLog,
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorValidationStatus,
    RawSignalRecord,
    SchedulerInstance,
    ScheduleType,
)
from packages.database.session import get_async_sessionmaker
from packages.risk_guard.models import AccountStatus
from packages.scheduling.admin import (
    CheckpointDebugService,
    ConnectorValidationService,
    RunRecoveryService,
    ScheduleAdminService,
)
from packages.scheduling.repository import ScheduleRepository
from packages.signals.services import SourceService


class FakeRSSConnector(BaseConnector):
    connector_type = "rss"

    def __init__(self, result: CollectionResult | None = None) -> None:
        self.result = result or CollectionResult(signals=())
        self.calls = 0

    async def health_check(self) -> dict[str, object]:
        return {"implemented": True}

    async def collect(self, request: CollectRequest) -> CollectionResult:
        del request
        self.calls += 1
        return self.result


async def _enabled_rss_source(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    definition_id = definition.id
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"m1d-rss-{uuid4()}",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={},
        actor="admin",
    )
    instance = await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M1-D RSS",
        source_type="rss",
        mode="feed",
        scope_key=f"feed:{uuid4()}",
        external_ref="https://example.com/feed.xml",
        config={"feed_url": "https://example.com/feed.xml"},
        enabled=True,
        actor="admin",
    )
    return definition, instance, source


def _runtime(fake: FakeRSSConnector) -> CollectorRuntime:
    registry = ConnectorRegistry()
    registry.register("rss", lambda: fake)
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )


async def _failed_run(db_session, *, instance_id, source_id, account_id=None, limit=2):  # type: ignore[no-untyped-def]
    service = ConnectorRunService(db_session)
    run = await service.create_pending(
        connector_instance_id=instance_id,
        source_id=source_id,
        platform_account_id=account_id,
        mode="feed",
        requested_limit=limit,
    )
    run_id = run.id
    await service.claim(run_id=run_id)
    return await service.finalize(
        run_id=run_id,
        target_status=ConnectorRunStatus.FAILED,
        failed_count=1,
        error_code="fixture_failure",
        error_message="fixture failure",
    )


@pytest.mark.usefixtures("clean_database")
async def test_schedule_lease_has_one_winner_and_expired_lease_is_reclaimable(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    _, instance, source = await _enabled_rss_source(db_session)
    schedule = await ScheduleAdminService(db_session).create(
        connector_instance_id=instance.id,
        source_id=source.id,
        platform_account_id=None,
        name="lease-test",
        schedule_type=ScheduleType.INTERVAL,
        interval_seconds=300,
        cron_expression=None,
        timezone="UTC",
        requested_limit=5,
        actor="admin",
    )
    schedule_id = schedule.id
    due_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.execute(
        update(CollectionSchedule)
        .where(CollectionSchedule.id == schedule_id)
        .values(next_run_at=due_at)
    )
    await db_session.commit()

    session_factory = get_async_sessionmaker()
    claim_now = datetime.now(UTC)

    async def claim(owner: str):  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            async with session.begin():
                return await ScheduleRepository(session).claim_schedule(
                    schedule_id=schedule_id,
                    owner=owner,
                    now=claim_now,
                    lease_expires_at=claim_now + timedelta(seconds=120),
                )

    first, second = await asyncio.gather(claim("scheduler-a"), claim("scheduler-b"))
    winners = [item for item in (first, second) if item is not None]
    assert len(winners) == 1
    assert winners[0].lease_owner in {"scheduler-a", "scheduler-b"}

    reclaim_at = claim_now + timedelta(seconds=121)
    async with session_factory() as session:
        async with session.begin():
            reclaimed = await ScheduleRepository(session).claim_schedule(
                schedule_id=schedule_id,
                owner="scheduler-recovery",
                now=reclaim_at,
                lease_expires_at=reclaim_at + timedelta(seconds=120),
            )
    assert reclaimed is not None
    assert reclaimed.lease_owner == "scheduler-recovery"


@pytest.mark.usefixtures("clean_database")
async def test_schedule_slot_is_unique_and_schedule_survives_new_session(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    _, instance, source = await _enabled_rss_source(db_session)
    schedule = await ScheduleAdminService(db_session).create(
        connector_instance_id=instance.id,
        source_id=source.id,
        platform_account_id=None,
        name="slot-test",
        schedule_type=ScheduleType.INTERVAL,
        interval_seconds=600,
        cron_expression=None,
        timezone="Asia/Shanghai",
        requested_limit=5,
        actor="admin",
    )
    schedule_id = schedule.id
    scheduled_for = schedule.next_run_at
    await db_session.commit()
    session_factory = get_async_sessionmaker()

    async with session_factory() as session:
        async with session.begin():
            persisted = await session.get(CollectionSchedule, schedule_id)
            assert persisted is not None
            assert persisted.next_run_at == scheduled_for
            first = await ScheduleRepository(session).claim_slot(
                schedule=persisted,
                owner="scheduler-a",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=120),
            )
        assert first is not None
        first_id = first.id

    async with session_factory() as session:
        async with session.begin():
            persisted = await session.get(CollectionSchedule, schedule_id)
            assert persisted is not None
            second = await ScheduleRepository(session).claim_slot(
                schedule=persisted,
                owner="scheduler-b",
                now=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=120),
            )
        assert second is not None
        assert second.id == first_id
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(CollectionScheduleTrigger)
                .where(CollectionScheduleTrigger.schedule_id == schedule_id)
            )
            or 0
        )
        assert count == 1


@pytest.mark.usefixtures("clean_database")
async def test_scheduler_heartbeat_is_persisted(db_session) -> None:  # type: ignore[no-untyped-def]
    del db_session
    session_factory = get_async_sessionmaker()
    started = datetime.now(UTC) - timedelta(seconds=10)
    heartbeat = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await ScheduleRepository(session).heartbeat(
                instance_key="scheduler-heartbeat-test",
                started_at=started,
                now=heartbeat,
                recent_trigger_failures=2,
            )
    async with session_factory() as session:
        stored = await session.scalar(
            select(SchedulerInstance).where(
                SchedulerInstance.instance_key == "scheduler-heartbeat-test"
            )
        )
        assert stored is not None
        assert stored.started_at == started
        assert stored.last_heartbeat == heartbeat
        assert stored.recent_trigger_failures == 2


@pytest.mark.usefixtures("clean_database")
async def test_stale_run_is_only_identified_then_retry_creates_new_run(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    _, instance, source = await _enabled_rss_source(db_session)
    instance_id = instance.id
    source_id = source.id
    service = ConnectorRunService(db_session)
    run = await service.create_pending(
        connector_instance_id=instance_id,
        source_id=source_id,
        platform_account_id=None,
        mode="feed",
        requested_limit=2,
    )
    run_id = run.id
    await service.claim(run_id=run_id)
    old_progress = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(ConnectorRun)
        .where(ConnectorRun.id == run_id)
        .values(progress_updated_at=old_progress)
    )
    await db_session.commit()

    stale = await RunRecoveryService(db_session).list_stale(
        page=1,
        page_size=20,
        stale_seconds=300,
    )
    assert [item.id for item in stale.items] == [run_id]
    unchanged = await db_session.get(ConnectorRun, run_id)
    assert unchanged is not None
    await db_session.refresh(unchanged)
    assert unchanged.status is ConnectorRunStatus.RUNNING

    failed = await RunRecoveryService(db_session).mark_failed(
        run_id=run_id,
        reason="人工确认进程已崩溃",
    )
    old_run_id = failed.id
    assert failed.status is ConnectorRunStatus.FAILED
    retry_task = await RunRecoveryService(db_session).build_retry_task(
        run_id=old_run_id,
        actor="reviewer",
    )
    assert retry_task.parent_run_id == old_run_id
    assert retry_task.retry_count == 1

    fake = FakeRSSConnector()
    result = await _runtime(fake).execute(retry_task)
    assert result.status is ConnectorRunStatus.SUCCEEDED
    assert fake.calls == 1
    retry_run = await db_session.get(ConnectorRun, result.run_id)
    original = await db_session.get(ConnectorRun, old_run_id)
    assert retry_run is not None
    assert original is not None
    await db_session.refresh(retry_run)
    await db_session.refresh(original)
    assert retry_run.parent_run_id == old_run_id
    assert retry_run.retry_count == 1
    assert original.status is ConnectorRunStatus.FAILED


@pytest.mark.usefixtures("clean_database")
async def test_retry_reenters_budget_and_risk_guard(db_session) -> None:  # type: ignore[no-untyped-def]
    _, instance, source = await _enabled_rss_source(db_session)
    instance_id = instance.id
    source_id = source.id
    old = await _failed_run(
        db_session,
        instance_id=instance_id,
        source_id=source_id,
        limit=2,
    )
    old_run_id = old.id
    await CollectionBudgetService(db_session).create(
        scope_type="connector",
        scope_key=str(instance_id),
        values={
            "max_runs_per_day": 10,
            "max_items_per_run": 1,
            "max_items_per_day": 10,
            "max_comments_per_run": 0,
            "max_comments_per_day": 0,
            "max_concurrency": 1,
            "timezone": "UTC",
            "enabled": True,
        },
        actor="admin",
    )
    task = await RunRecoveryService(db_session).build_retry_task(
        run_id=old_run_id,
        actor="reviewer",
    )
    fake = FakeRSSConnector()
    with pytest.raises(BudgetExceededError):
        await _runtime(fake).execute(task)
    assert fake.calls == 0
    original = await db_session.get(ConnectorRun, old_run_id)
    assert original is not None
    await db_session.refresh(original)
    assert original.status is ConnectorRunStatus.FAILED

    await db_session.rollback()
    account = await PlatformAccountService(db_session).create(
        connector_instance_id=instance_id,
        platform="rss",
        display_name="risk account",
        account_identifier=f"risk-{uuid4()}",
        credential_ref=None,
        browser_profile_ref=None,
        actor="admin",
    )
    account_id = account.id
    await PlatformAccountService(db_session).transition_status(
        account_id=account_id,
        target_status=AccountStatus.REVIEW_REQUIRED,
        reason="人工复核",
        cooldown_until=None,
        override_cooldown=False,
        actor="admin",
    )
    risk_old = await _failed_run(
        db_session,
        instance_id=instance_id,
        source_id=source_id,
        account_id=account_id,
        limit=1,
    )
    risk_old_id = risk_old.id
    risk_task = await RunRecoveryService(db_session).build_retry_task(
        run_id=risk_old_id,
        actor="reviewer",
    )
    risk_fake = FakeRSSConnector()
    with pytest.raises(PreflightRejectedError):
        await _runtime(risk_fake).execute(risk_task)
    assert risk_fake.calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_checkpoint_reset_is_optimistic_audited_and_keeps_raw_signals(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    _, instance, source = await _enabled_rss_source(db_session)
    instance_id = instance.id
    source_id = source.id
    fake = FakeRSSConnector(
        CollectionResult(
            signals=(
                RawSignal(
                    platform="rss",
                    external_id="m1d-checkpoint-signal",
                    url="https://example.com/checkpoint-item",
                    title="checkpoint item",
                ),
            ),
            checkpoint={"cursor": "after-one"},
        )
    )
    run = await _runtime(fake).execute(
        CollectionTask(
            task_id=uuid4(),
            connector_instance_id=instance_id,
            source_id=source_id,
            platform_account_id=None,
            mode="feed",
            requested_limit=1,
            checkpoint_version=None,
            trigger_type=TriggerType.TEST,
            triggered_by="tester",
            created_at=datetime.now(UTC),
        )
    )
    assert run.status is ConnectorRunStatus.SUCCEEDED
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(ConnectorCheckpoint.source_id == source_id)
    )
    assert checkpoint is not None
    checkpoint_id = checkpoint.id
    expected_version = checkpoint.version
    raw_before = int(
        await db_session.scalar(select(func.count()).select_from(RawSignalRecord)) or 0
    )
    await db_session.rollback()

    session_factory = get_async_sessionmaker()

    async def reset_once(actor: str) -> str:
        async with session_factory() as session:
            try:
                await CheckpointDebugService(session).reset(
                    checkpoint_id=checkpoint_id,
                    expected_version=expected_version,
                    reason=f"{actor} reset test",
                    actor=actor,
                )
            except VersionConflictError:
                return "conflict"
            return "reset"

    outcomes = await asyncio.gather(reset_once("reviewer-a"), reset_once("reviewer-b"))
    assert sorted(outcomes) == ["conflict", "reset"]
    async with session_factory() as session:
        refreshed = await session.get(ConnectorCheckpoint, checkpoint_id)
        assert refreshed is not None
        assert refreshed.version == expected_version + 1
        assert refreshed.checkpoint_data == {}
        raw_after = int(
            await session.scalar(select(func.count()).select_from(RawSignalRecord)) or 0
        )
        audit_count = int(
            await session.scalar(
                select(func.count())
                .select_from(ConfigurationChangeLog)
                .where(
                    ConfigurationChangeLog.entity_type == "connector_checkpoint",
                    ConfigurationChangeLog.entity_id == checkpoint_id,
                    ConfigurationChangeLog.action == "reset",
                )
            )
            or 0
        )
    assert raw_after == raw_before == 1
    assert audit_count == 1


@pytest.mark.usefixtures("clean_database")
async def test_connector_validation_requires_real_smoke_and_expires_on_version_change(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    definition, _, _ = await _enabled_rss_source(db_session)
    connector_type = definition.connector_type
    platform = definition.platform
    version = definition.implementation_version
    definition_id = definition.id
    service = ConnectorValidationService(db_session)
    assert await service.effective_status(definition) is ConnectorValidationStatus.NOT_TESTED
    await db_session.rollback()

    with pytest.raises(BusinessValidationError, match="不能写入真实 PASSED"):
        await service.record(
            connector_type=connector_type,
            platform=platform,
            implementation_version=version,
            environment="ci",
            status=ConnectorValidationStatus.PASSED,
            actor="ci",
            notes="mock only",
            safe_evidence={"fixture": True},
            real_smoke_test=False,
        )

    failed = await service.record(
        connector_type=connector_type,
        platform=platform,
        implementation_version=version,
        environment="local",
        status=ConnectorValidationStatus.FAILED,
        actor="reviewer",
        notes="真实低量验收失败",
        safe_evidence={"reason": "safe fixture"},
        real_smoke_test=True,
    )
    assert failed.status is ConnectorValidationStatus.FAILED
    passed = await service.record(
        connector_type=connector_type,
        platform=platform,
        implementation_version=version,
        environment="local",
        status=ConnectorValidationStatus.PASSED,
        actor="reviewer",
        notes="真实低量验收通过",
        safe_evidence={"items": 1, "token": "must-redact"},
        real_smoke_test=True,
    )
    await db_session.refresh(passed)
    assert passed.safe_evidence["token"] == "[REDACTED]"
    current = await db_session.get(ConnectorDefinition, definition_id)
    assert current is not None
    assert await service.effective_status(current) is ConnectorValidationStatus.PASSED
    await db_session.rollback()

    next_version = f"{version}-next"
    await db_session.execute(
        update(ConnectorDefinition)
        .where(ConnectorDefinition.id == definition_id)
        .values(implementation_version=next_version)
    )
    await db_session.commit()
    current = await db_session.get(ConnectorDefinition, definition_id)
    assert current is not None
    assert await service.effective_status(current) is ConnectorValidationStatus.EXPIRED
