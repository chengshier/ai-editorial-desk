from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.connector_management.exceptions import VersionConflictError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
    MediaCrawlerRiskSeverity,
    PlatformRiskSignal,
)
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorRunStatus,
    PlatformAccount,
    PlatformRiskEvent,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.risk_guard.models import AccountStatus
from packages.signals.services import SourceService


def _item(external_id: str) -> dict[str, object]:
    return {
        "note_id": external_id,
        "content": f"fixture {external_id}",
        "create_time": 1786086000,
        "liked_count": "1",
        "comments_count": "1",
        "shared_count": "1",
        "note_url": f"https://m.weibo.cn/detail/{external_id}",
        "creator_hash": "creator-fixture",
        "nickname": "测***户",
    }


def _checkpoint(page: int, external_id: str) -> MediaCrawlerCheckpoint:
    return MediaCrawlerCheckpoint(
        platform=MediaCrawlerPlatform.WEIBO,
        mode="search",
        page=page,
        last_external_id=external_id,
        latest_published_at=datetime(2026, 8, 7, 10, tzinfo=UTC),
        last_completed_scope=f"search:page:{max(1, page - 1)}",
        metadata={"strategy": "page_resume_replay_window"},
    )


class ResumeAdapter:
    def __init__(self, plans: list[dict[str, object] | Exception]) -> None:
        self.settings = SimpleNamespace(mediacrawler_timeout_seconds=30)
        self.plans = list(plans)
        self.invocations: list[MediaCrawlerInvocation] = []

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"status": "ok", "protocol_version": "1.1"}

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        self.invocations.append(invocation)
        if not self.plans:
            raise AssertionError("unexpected adapter call")
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        now = datetime.now(UTC)
        return MediaCrawlerResultEnvelope(
            protocol_version="1.1",
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=plan.get("status", MediaCrawlerResultStatus.SUCCESS),
            items=plan.get("items", []),  # type: ignore[arg-type]
            comments=plan.get("comments", []),  # type: ignore[arg-type]
            checkpoint=plan.get("checkpoint"),  # type: ignore[arg-type]
            counters=MediaCrawlerCounters(
                items=len(plan.get("items", [])),  # type: ignore[arg-type]
                comments=len(plan.get("comments", [])),  # type: ignore[arg-type]
            ),
            risk_events=plan.get("risk_events", []),  # type: ignore[arg-type]
            started_at=now,
            finished_at=now,
        )


async def _enabled_source(db_session, *, include_comments: bool = False):  # type: ignore[no-untyped-def]
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
        name=f"m2c-weibo-{uuid4()}",
        config={
            "modes": ["search"],
            "keyword": "AI 编辑部",
            "include_comments": include_comments,
            "comment_limit": 5 if include_comments else 0,
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
        name="M2-C 微博 fixture",
        source_type="mediacrawler",
        mode="search",
        scope_key=f"weibo:m2c:{uuid4()}",
        external_ref="AI 编辑部",
        config={
            "keyword": "AI 编辑部",
            "include_comments": include_comments,
            "comment_limit": 5 if include_comments else 0,
        },
        enabled=True,
        actor="admin",
    )
    account = await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform="weibo",
        display_name="M2-C fixture account",
        account_identifier=f"fixture-{uuid4()}",
        credential_ref="credential-ref-fixture",
        browser_profile_ref=None,
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
        "requested_limit": 10,
        "checkpoint_version": None,
        "trigger_type": TriggerType.TEST,
        "triggered_by": "m2c-tester",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return CollectionTask(**values)


def _runtime(adapter: ResumeAdapter, runtime_cls=CollectorRuntime):  # type: ignore[no-untyped-def]
    connector = MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
    registry = ConnectorRegistry()
    registry.register("mediacrawler", lambda: connector)
    return runtime_cls(session_factory=get_async_sessionmaker(), registry=registry)


@pytest.mark.usefixtures("clean_database")
async def test_first_run_resume_and_duplicate_are_checkpoint_safe(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_source(db_session)
    adapter = ResumeAdapter(
        [
            {"items": [_item("post-1")], "checkpoint": _checkpoint(2, "post-1")},
            {"items": [_item("post-2")], "checkpoint": _checkpoint(1, "post-2")},
            {"items": [_item("post-2")], "checkpoint": _checkpoint(1, "post-2")},
        ]
    )
    runtime = _runtime(adapter)

    first = await runtime.execute(_task(instance_id, source_id, account_id))
    second = await runtime.execute(_task(instance_id, source_id, account_id))
    duplicate = await runtime.execute(_task(instance_id, source_id, account_id))

    assert first.status is ConnectorRunStatus.SUCCEEDED
    assert second.status is ConnectorRunStatus.SUCCEEDED
    assert duplicate.status is ConnectorRunStatus.SUCCEEDED
    assert (first.inserted_count, second.inserted_count, duplicate.duplicate_count) == (1, 1, 1)
    assert adapter.invocations[0].checkpoint is not None
    assert adapter.invocations[0].checkpoint.page is None
    assert adapter.invocations[1].checkpoint is not None
    assert adapter.invocations[1].checkpoint.page == 2
    assert adapter.invocations[1].profile_context.account_configured is True
    assert adapter.invocations[1].profile_context.browser_profile_configured is False
    assert "credential-ref-fixture" not in adapter.invocations[1].model_dump_json()

    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.checkpoint_data["page"] == 1
    assert checkpoint.cursor == {"page": 1}
    assert checkpoint.last_external_id == "post-2"
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(RawSignalRecord)
            .where(RawSignalRecord.source_id == source_id)
        )
        or 0
    ) == 2


@pytest.mark.usefixtures("clean_database")
async def test_crash_before_ingestion_does_not_advance_checkpoint(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_source(db_session)
    adapter = ResumeAdapter(
        [ConnectorFetchError("NETWORK_TIMEOUT", "fixture timeout", retryable=True)]
    )
    result = await _runtime(adapter).execute(_task(instance_id, source_id, account_id))
    assert result.status is ConnectorRunStatus.FAILED
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 1
    assert checkpoint.checkpoint_data == {}


@pytest.mark.usefixtures("clean_database")
async def test_comment_mapping_partial_keeps_main_signal_but_not_checkpoint(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_source(
        db_session,
        include_comments=True,
    )
    adapter = ResumeAdapter(
        [
            {
                "items": [_item("post-comment")],
                "comments": [
                    {
                        "note_id": "post-comment",
                        "comment_id": "broken-comment",
                        "content": "",
                    }
                ],
                "checkpoint": _checkpoint(2, "post-comment"),
            }
        ]
    )
    result = await _runtime(adapter).execute(_task(instance_id, source_id, account_id))
    assert result.status is ConnectorRunStatus.PARTIAL
    assert result.inserted_count == 1
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 1
    assert checkpoint.checkpoint_data == {}


@pytest.mark.usefixtures("clean_database")
async def test_safe_partial_risk_commits_watermark_then_pauses_account(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_source(db_session)
    risk = PlatformRiskSignal(
        platform=MediaCrawlerPlatform.WEIBO,
        source_error_code="429",
        standard_error_code="RATE_LIMITED",
        severity=MediaCrawlerRiskSeverity.ERROR,
        retryable=False,
        action_hint="manual_review",
        requires_manual_review=True,
        message="MediaCrawler platform rate limit detected",
        checkpoint_safe_to_commit=True,
    )
    adapter = ResumeAdapter(
        [
            {
                "status": MediaCrawlerResultStatus.PARTIAL,
                "items": [_item("post-risk")],
                "checkpoint": _checkpoint(2, "post-risk"),
                "risk_events": [risk],
            }
        ]
    )
    result = await _runtime(adapter).execute(_task(instance_id, source_id, account_id))

    assert result.status is ConnectorRunStatus.PAUSED_RISK
    assert result.inserted_count == 1
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 2
    assert checkpoint.checkpoint_data["page"] == 2
    assert int(
        await db_session.scalar(select(func.count()).select_from(PlatformRiskEvent)) or 0
    ) == 1
    account = await db_session.get(PlatformAccount, account_id)
    assert account is not None
    assert account.status is AccountStatus.REVIEW_REQUIRED
    assert account.manual_review_required is True


class ConflictRuntime(CollectorRuntime):
    async def advance_checkpoint(self, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise VersionConflictError("fixture checkpoint conflict")


@pytest.mark.usefixtures("clean_database")
async def test_optimistic_checkpoint_conflict_never_overwrites_authority(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _enabled_source(db_session)
    adapter = ResumeAdapter(
        [{"items": [_item("post-conflict")], "checkpoint": _checkpoint(2, "post-conflict")}]
    )
    result = await _runtime(adapter, ConflictRuntime).execute(
        _task(instance_id, source_id, account_id)
    )
    assert result.status is ConnectorRunStatus.PARTIAL
    assert result.inserted_count == 1
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == instance_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.version == 1
    assert checkpoint.checkpoint_data == {}
