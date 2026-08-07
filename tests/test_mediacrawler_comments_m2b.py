from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.connectors.base import BaseConnector, CollectionResult, CollectRequest
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    CollectionBudget,
    ConnectorDefinition,
    ConnectorRun,
    ConnectorRunStatus,
    RawSignalCommentRecord,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.signals.services import SourceService


class CommentEnvelopeAdapter:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(mediacrawler_timeout_seconds=30)
        self.calls = 0

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        self.calls += 1
        now = datetime.now(UTC)
        return MediaCrawlerResultEnvelope(
            protocol_version="1.1",
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=MediaCrawlerResultStatus.SUCCESS,
            items=[
                {
                    "note_id": "comment-post-1",
                    "content": "主内容",
                    "create_time": 1786086000,
                    "liked_count": "3",
                    "comments_count": "2",
                    "shared_count": "1",
                    "note_url": "https://m.weibo.cn/detail/comment-post-1",
                    "creator_hash": "creator-hash",
                    "nickname": "作***者",
                }
            ],
            comments=[
                {
                    "comment_id": "comment-1",
                    "note_id": "comment-post-1",
                    "content": "一级评论",
                    "creator_hash": "commenter-hash",
                    "nickname": "评***者",
                    "comment_like_count": "2",
                    "parent_comment_id": "parent-fixture",
                    "cookie": "fixture-value-cookie",
                },
                {"comment_id": "broken-comment", "content": "缺少 note_id"},
            ],
            checkpoint=MediaCrawlerCheckpoint(
                platform=invocation.platform,
                mode=MediaCrawlerMode.SEARCH,
                page=2,
                last_external_id="comment-post-1",
                metadata={"legacy_test": "m2b-comments"},
            ),
            counters=MediaCrawlerCounters(items=1, comments=2),
            warnings=[],
            risk_events=[],
            errors=[],
            started_at=now,
            finished_at=now,
        )


async def _setup(
    db_session,  # type: ignore[no-untyped-def]
    *,
    platform: str = "weibo",
    source_mode: str = "search",
    source_config: dict[str, object] | None = None,
):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "mediacrawler",
            ConnectorDefinition.platform == platform,
        )
    )
    assert definition is not None
    if not definition.is_enabled:
        definition.is_enabled = True
    definition_id = definition.id
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"m2b-{platform}-{uuid4()}",
        config={
            "modes": ["search"],
            "keyword": "AI 编辑部",
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
        name="M2-B fixture source",
        source_type="mediacrawler",
        mode=source_mode,
        scope_key=f"{platform}:{source_mode}:{uuid4()}",
        external_ref="AI 编辑部",
        config=source_config
        or {"keyword": "AI 编辑部", "include_comments": False},
        enabled=True,
        actor="admin",
    )
    account = await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform=platform,
        display_name="fixture account",
        account_identifier=f"fixture-{uuid4()}",
        credential_ref=None,
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
        "requested_limit": 1,
        "checkpoint_version": None,
        "trigger_type": TriggerType.TEST,
        "triggered_by": "m2b-comment-tester",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return CollectionTask(**values)


def _runtime(adapter: CommentEnvelopeAdapter) -> CollectorRuntime:
    connector = MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
    registry = ConnectorRegistry()
    registry.register("mediacrawler", lambda: connector)
    return CollectorRuntime(session_factory=get_async_sessionmaker(), registry=registry)


async def _enable_comment_budget(db_session, instance_id) -> None:  # type: ignore[no-untyped-def]
    budget = await db_session.scalar(
        select(CollectionBudget).where(
            CollectionBudget.scope_type == "connector",
            CollectionBudget.scope_key == str(instance_id),
        )
    )
    if budget is None:
        budget = CollectionBudget(
            scope_type="connector",
            scope_key=str(instance_id),
            max_requests_per_minute=10,
            max_requests_per_day=100,
            max_items_per_run=10,
            max_items_per_day=100,
            max_comments_per_run=10,
            max_comments_per_day=100,
            timezone="UTC",
            enabled=True,
            updated_by="test",
        )
        db_session.add(budget)
    else:
        budget.max_comments_per_run = 10
        budget.max_comments_per_day = 100
    await db_session.commit()


@pytest.mark.usefixtures("clean_database")
async def test_m2b_comments_persist_partial_and_sanitize(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        source_config={
            "keyword": "AI 编辑部",
            "include_comments": True,
            "comment_limit": 2,
        },
    )
    await _enable_comment_budget(db_session, instance_id)
    adapter = CommentEnvelopeAdapter()
    result = await _runtime(adapter).execute(_task(instance_id, source_id, account_id))

    assert result.status is ConnectorRunStatus.PARTIAL
    assert result.inserted_count == 1
    assert result.failed_count == 1
    assert len(result.signal_ids) == 1
    assert adapter.calls == 1

    raw = await db_session.scalar(
        select(RawSignalRecord).where(RawSignalRecord.id == result.signal_ids[0])
    )
    assert raw is not None
    comment = await db_session.scalar(
        select(RawSignalCommentRecord).where(
            RawSignalCommentRecord.raw_signal_id == raw.id
        )
    )
    assert comment is not None
    assert comment.external_comment_id == "comment-1"
    assert comment.parent_comment_id == "parent-fixture"
    assert comment.raw_payload["cookie"] == "***REDACTED***"


@pytest.mark.usefixtures("clean_database")
async def test_m2b_comments_duplicate_is_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        source_config={
            "keyword": "AI 编辑部",
            "include_comments": True,
            "comment_limit": 2,
        },
    )
    await _enable_comment_budget(db_session, instance_id)
    adapter = CommentEnvelopeAdapter()
    runtime = _runtime(adapter)

    first = await runtime.execute(_task(instance_id, source_id, account_id))
    second = await runtime.execute(_task(instance_id, source_id, account_id))

    assert first.inserted_count == 1
    assert second.duplicate_count == 1
    assert int(
        await db_session.scalar(
            select(func.count()).select_from(RawSignalCommentRecord)
        )
        or 0
    ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_xhs_comments_mode_rejected_by_allowed_modes_before_adapter(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        platform="xiaohongshu",
        source_mode="comments",
        source_config={
            "content_ids": ["xhs-unsafe-comments"],
            "include_comments": True,
            "comment_limit": 1,
        },
    )
    adapter = CommentEnvelopeAdapter()

    with pytest.raises(ValueError, match="does not allow mode comments"):
        await _runtime(adapter).execute(
            _task(
                instance_id,
                source_id,
                account_id,
                mode="comments",
            )
        )
    assert adapter.calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_m2b_comment_budget_rejects_before_adapter(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        source_config={
            "keyword": "AI 编辑部",
            "include_comments": True,
            "comment_limit": 5,
        },
    )
    adapter = CommentEnvelopeAdapter()

    with pytest.raises(Exception, match="comment_limit 超过单次评论预算"):
        await _runtime(adapter).execute(
            _task(instance_id, source_id, account_id, requested_limit=10)
        )
    assert adapter.calls == 0


class CommentOnlyConnector(BaseConnector):
    connector_type = "mediacrawler"

    async def health_check(self) -> dict[str, object]:
        return {"status": "ok"}

    async def collect(self, request: CollectRequest) -> CollectionResult:
        del request
        return CollectionResult()


@pytest.mark.usefixtures("clean_database")
async def test_m2b_comment_run_metadata_has_no_raw_credentials(db_session) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(db_session)
    registry = ConnectorRegistry()
    registry.register("mediacrawler", CommentOnlyConnector)
    result = await CollectorRuntime(
        session_factory=get_async_sessionmaker(), registry=registry
    ).execute(_task(instance_id, source_id, account_id))
    run = await db_session.get(ConnectorRun, result.run_id)
    assert run is not None
    assert "credential" not in str(run.run_metadata).casefold()
