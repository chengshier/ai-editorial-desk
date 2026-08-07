from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.exceptions import BudgetExceededError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorRunStatus,
    PlatformRiskEvent,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.signals.services import SourceService


class FakeAdapter:
    def __init__(self, *, invalid_url: bool = False) -> None:
        self.settings = SimpleNamespace(mediacrawler_timeout_seconds=30)
        self.invalid_url = invalid_url
        self.calls = 0
        self.invocations: list[MediaCrawlerInvocation] = []

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        self.calls += 1
        self.invocations.append(invocation)
        now = datetime.now(UTC)
        return MediaCrawlerResultEnvelope(
            protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=MediaCrawlerResultStatus.SUCCESS,
            items=[
                {
                    "external_id": "fixture-post",
                    "url": "not-a-url"
                    if self.invalid_url
                    else "https://example.com/fixture-post",
                    "title": "M2-A fixture",
                    "published_at": "2026-08-07T07:00:00+00:00",
                }
            ],
            comments=[],
            checkpoint={"cursor": "fixture-next"},
            counters=MediaCrawlerCounters(items=1),
            warnings=[],
            risk_events=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )


class ErrorRunner:
    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        del invocation
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.CAPTCHA_REQUIRED,
            "MediaCrawler platform requires CAPTCHA review",
        )


async def _enabled_mediacrawler_source(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "mediacrawler",
            ConnectorDefinition.platform == "weibo",
        )
    )
    assert definition is not None
    definition_id = definition.id
    await db_session.commit()

    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"m2a-weibo-{uuid4()}",
        config={
            "modes": ["search"],
            "keywords": ["AI 编辑部"],
            "include_comments": False,
        },
        schedule_config={},
        actor="admin",
    )
    instance = await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M2-A 微博 fixture",
        source_type="mediacrawler",
        mode="search",
        scope_key=f"weibo:fixture:{uuid4()}",
        external_ref="AI 编辑部",
        config={
            "keywords": ["AI 编辑部"],
            "include_comments": False,
        },
        enabled=True,
        actor="admin",
    )
    account = await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform="weibo",
        display_name="fixture account",
        account_identifier=f"fixture-{uuid4()}",
        credential_ref=None,
        browser_profile_ref="profile-ref-fixture",
        actor="admin",
    )
    ids = (instance.id, source.id, account.id)
    await db_session.rollback()
    return ids


def _task(instance_id, source_id, account_id, **overrides):  # type: ignore[no-untyped-def]
    values = {
        "task_id": uuid4(),
        "connector_instance_id": instance_id,
        "source_id": source_id,
        "platform_account_id": account_id,
        "mode": "search",
        "requested_limit": 5,
        "checkpoint_version": None,
        "trigger_type": TriggerType.TEST,
        "triggered_by": "m2a-tester",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return CollectionTask(**values)


def _runtime(connector: MediaCrawlerConnector) -> CollectorRuntime:
    registry = ConnectorRegistry()
    registry.register("mediacrawler", lambda: connector)
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )


@pytest.mark.usefixtures("clean_database")
async def test_mediacrawler_runtime_ingests_idempotently_and_advances_checkpoint(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_mediacrawler_source(db_session)
    adapter = FakeAdapter()
    runtime = _runtime(MediaCrawlerConnector(adapter=adapter))  # type: ignore[arg-type]

    first = await runtime.execute(_task(instance_id, source_id, account_id))
    second = await runtime.execute(_task(instance_id, source_id, account_id))

    assert first.status is ConnectorRunStatus.SUCCEEDED
    assert (first.inserted_count, first.duplicate_count) == (1, 0)
    assert second.status is ConnectorRunStatus.SUCCEEDED
    assert (second.inserted_count, second.duplicate_count) == (0, 1)
    assert adapter.calls == 2
    assert adapter.invocations[0].platform.value == "weibo"
    assert adapter.invocations[0].account_ref == str(account_id)
    assert adapter.invocations[0].browser_profile_ref == "profile-ref-fixture"

    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id,
        )
    )
    assert checkpoint is not None
    assert checkpoint.checkpoint_data == {"cursor": "fixture-next"}
    assert checkpoint.version == 3
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(RawSignalRecord)
            .where(RawSignalRecord.source_id == source_id)
        )
        or 0
    ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_mediacrawler_checkpoint_does_not_advance_when_ingestion_fails(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_mediacrawler_source(db_session)
    connector = MediaCrawlerConnector(adapter=FakeAdapter(invalid_url=True))  # type: ignore[arg-type]
    runtime = _runtime(connector)

    result = await runtime.execute(_task(instance_id, source_id, account_id))
    assert result.status is ConnectorRunStatus.FAILED

    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id,
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 1
    assert checkpoint.checkpoint_data == {}


@pytest.mark.usefixtures("clean_database")
async def test_mediacrawler_risk_enters_paused_risk(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_mediacrawler_source(db_session)
    adapter = MediaCrawlerAdapter(
        runner=ErrorRunner(),
        settings=SimpleNamespace(  # type: ignore[arg-type]
            mediacrawler_home="third_party/MediaCrawler",
            mediacrawler_python="python",
            mediacrawler_timeout_seconds=30,
        ),
    )
    result = await _runtime(MediaCrawlerConnector(adapter=adapter)).execute(
        _task(instance_id, source_id, account_id)
    )

    assert result.status is ConnectorRunStatus.PAUSED_RISK
    assert int(
        await db_session.scalar(select(func.count()).select_from(PlatformRiskEvent)) or 0
    ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_mediacrawler_budget_rejects_before_adapter(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_mediacrawler_source(db_session)
    adapter = FakeAdapter()
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

    with pytest.raises(BudgetExceededError):
        connector = MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
        await _runtime(connector).execute(
            _task(instance_id, source_id, account_id, requested_limit=2)
        )
    assert adapter.calls == 0
