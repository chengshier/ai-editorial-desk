from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.exceptions import (
    BudgetExceededError,
    ConnectorImplementationUnavailableError,
    PreflightRejectedError,
)
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.connectors.base import (
    BaseConnector,
    CollectionItemError,
    CollectionResult,
    CollectRequest,
    RawSignal,
)
from packages.connectors.http import ConnectorFetchError
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorRun,
    ConnectorRunStatus,
    PlatformAccount,
    PlatformRiskEvent,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.risk_guard.models import (
    AccountStatus,
    ErrorDisposition,
    PlatformRiskError,
    RiskAction,
    RiskEvent,
)
from packages.signals.services import SourceService


class FakeConnector(BaseConnector):
    connector_type = "rss"

    def __init__(
        self,
        result: CollectionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result or CollectionResult(signals=())
        self.error = error
        self.calls = 0
        self.requests: list[CollectRequest] = []

    async def health_check(self) -> dict[str, object]:
        return {"implemented": True}

    async def collect(self, request: CollectRequest) -> CollectionResult:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


async def _enabled_source(  # type: ignore[no-untyped-def]
    db_session,
    *,
    connector_type: str = "rss",
):
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == connector_type
        )
    )
    assert definition is not None
    definition_id = definition.id
    platform = definition.platform
    await db_session.commit()
    config = (
        {"feed_urls": ["https://example.com/feed.xml"]}
        if connector_type == "rss"
        else {"subreddits": ["python"], "sort": "new"}
    )
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"{connector_type}-{uuid4()}",
        config=config,
        schedule_config={},
        actor="admin",
    )
    instance = await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name=f"{connector_type} source",
        source_type=connector_type,
        mode="feed",
        scope_key=f"{connector_type}:{uuid4()}",
        external_ref="https://example.com/feed.xml",
        config={"feed_url": "https://example.com/feed.xml"},
        enabled=True,
        actor="admin",
    )
    return instance, source, platform


def _task(instance_id, source_id, **overrides):  # type: ignore[no-untyped-def]
    values = {
        "task_id": uuid4(),
        "connector_instance_id": instance_id,
        "source_id": source_id,
        "platform_account_id": None,
        "mode": "feed",
        "requested_limit": 10,
        "checkpoint_version": None,
        "trigger_type": TriggerType.TEST,
        "triggered_by": "tester",
        "created_at": datetime.now(UTC),
        "dry_run": False,
    }
    values.update(overrides)
    return CollectionTask(**values)


def _runtime(fake: FakeConnector) -> CollectorRuntime:
    registry = ConnectorRegistry()
    registry.register("rss", lambda: fake)
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )


@pytest.mark.usefixtures("clean_database")
async def test_runtime_success_counts_checkpoint_and_duplicate(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source, _ = await _enabled_source(db_session)
    fake = FakeConnector(
        CollectionResult(
            signals=(
                RawSignal(
                    platform="rss",
                    external_id="same",
                    url="https://example.com/a",
                    title="A",
                    published_at=datetime(2026, 8, 6, tzinfo=UTC),
                ),
                RawSignal(
                    platform="rss",
                    external_id="same",
                    url="https://example.com/a?utm_source=x",
                    title="A duplicate",
                    published_at=datetime(2026, 8, 6, tzinfo=UTC),
                ),
            ),
            checkpoint={"etag": '"v1"', "parser_version": "test"},
            metadata={"fetch_status": "fetched"},
        )
    )
    result = await _runtime(fake).execute(_task(instance.id, source.id))
    assert result.status is ConnectorRunStatus.SUCCEEDED
    assert (result.collected_count, result.inserted_count, result.duplicate_count) == (2, 1, 1)
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance.id,
            ConnectorCheckpoint.scope_key == source.scope_key,
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 2
    assert checkpoint.checkpoint_data["etag"] == '"v1"'
    assert int(
        await db_session.scalar(select(func.count()).select_from(RawSignalRecord)) or 0
    ) == 1
    assert fake.requests[0].checkpoint == {}


@pytest.mark.usefixtures("clean_database")
async def test_runtime_partial_and_dry_run(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source, _ = await _enabled_source(db_session)
    partial = await _runtime(
        FakeConnector(
            CollectionResult(
                signals=(
                    RawSignal(
                        platform="rss",
                        external_id="ok",
                        url="https://example.com/ok",
                    ),
                ),
                checkpoint={"etag": '"partial"'},
                errors=(
                    CollectionItemError(
                        code="entry_parse_failed",
                        message="one failed",
                    ),
                ),
            )
        )
    ).execute(_task(instance.id, source.id))
    assert partial.status is ConnectorRunStatus.PARTIAL
    assert partial.failed_count == 1

    dry = await _runtime(
        FakeConnector(
            CollectionResult(
                signals=(
                    RawSignal(
                        platform="rss",
                        external_id="dry",
                        url="https://example.com/dry",
                    ),
                ),
                checkpoint={"etag": '"dry"'},
            )
        )
    ).execute(_task(instance.id, source.id, dry_run=True))
    assert dry.status is ConnectorRunStatus.SUCCEEDED
    assert dry.inserted_count == 0
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(RawSignalRecord)
            .where(RawSignalRecord.external_id == "dry")
        )
        or 0
    ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_ingestion_failure_does_not_advance_checkpoint(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source, _ = await _enabled_source(db_session)
    result = await _runtime(
        FakeConnector(
            CollectionResult(
                signals=(
                    RawSignal(
                        platform="rss",
                        external_id="invalid",
                        url="not-a-url",
                    ),
                ),
                checkpoint={"etag": '"must-not-advance"'},
            )
        )
    ).execute(_task(instance.id, source.id))
    assert result.status is ConnectorRunStatus.FAILED
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance.id
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 1
    assert checkpoint.checkpoint_data == {}


@pytest.mark.usefixtures("clean_database")
async def test_preflight_and_budget_rejections_happen_before_network(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source, _ = await _enabled_source(db_session, connector_type="reddit")
    with pytest.raises(ConnectorImplementationUnavailableError):
        await CollectorRuntime(
            session_factory=get_async_sessionmaker(),
            registry=ConnectorRegistry(),
        ).execute(_task(instance.id, source.id))
    assert int(
        await db_session.scalar(select(func.count()).select_from(ConnectorRun)) or 0
    ) == 0
    await db_session.rollback()

    rss_instance, rss_source, _ = await _enabled_source(db_session)
    fake = FakeConnector()
    await ConnectorInstanceService(db_session).disable(
        instance_id=rss_instance.id,
        actor="admin",
    )
    with pytest.raises(PreflightRejectedError):
        await _runtime(fake).execute(_task(rss_instance.id, rss_source.id))
    assert fake.calls == 0
    await ConnectorInstanceService(db_session).enable(
        instance_id=rss_instance.id,
        actor="admin",
    )
    await CollectionBudgetService(db_session).create(
        scope_type="connector",
        scope_key=str(rss_instance.id),
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
    with pytest.raises(BudgetExceededError):
        await _runtime(fake).execute(
            _task(rss_instance.id, rss_source.id, requested_limit=2)
        )
    assert fake.calls == 0
    cancelled = await db_session.scalar(
        select(ConnectorRun)
        .where(ConnectorRun.source_id == rss_source.id)
        .order_by(ConnectorRun.created_at.desc())
    )
    assert cancelled is not None
    assert cancelled.status is ConnectorRunStatus.CANCELLED
    assert cancelled.error_code == "budget_rejected"


@pytest.mark.usefixtures("clean_database")
async def test_runtime_risk_and_ordinary_http_error_are_distinct(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source, platform = await _enabled_source(db_session)
    account = await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform=platform,
        display_name="account",
        account_identifier="account-1",
        credential_ref=None,
        browser_profile_ref=None,
        actor="admin",
    )
    account_id = account.id
    risk_error = PlatformRiskError(
        RiskEvent.now(
            platform=platform,
            account_id=str(account_id),
            code="restricted",
            message="platform restriction",
            disposition=ErrorDisposition.MANUAL_REVIEW,
            action=RiskAction.REQUIRE_REVIEW,
        )
    )
    risk_result = await _runtime(FakeConnector(error=risk_error)).execute(
        _task(instance.id, source.id, platform_account_id=account_id)
    )
    assert risk_result.status is ConnectorRunStatus.PAUSED_RISK
    refreshed = await db_session.get(PlatformAccount, account_id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.status is AccountStatus.REVIEW_REQUIRED
    assert refreshed.manual_review_required is True
    assert int(
        await db_session.scalar(select(func.count()).select_from(PlatformRiskEvent)) or 0
    ) == 1
    await db_session.rollback()

    await PlatformAccountService(db_session).transition_status(
        account_id=account_id,
        target_status=AccountStatus.HEALTHY,
        reason="人工确认恢复",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    ordinary = FakeConnector(
        error=ConnectorFetchError(
            "http_404",
            "远程地址返回错误状态",
            retryable=False,
            status_code=404,
        )
    )
    ordinary_result = await _runtime(ordinary).execute(
        _task(instance.id, source.id, platform_account_id=account_id)
    )
    assert ordinary_result.status is ConnectorRunStatus.FAILED
    assert int(
        await db_session.scalar(select(func.count()).select_from(PlatformRiskEvent)) or 0
    ) == 1
