from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.exceptions import (
    BudgetExceededError,
    PreflightRejectedError,
)
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.connectors.base import CollectedComment
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorRunStatus,
    RawSignalCommentRecord,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.signals.comment_service import RawSignalCommentService
from packages.signals.services import SourceService


class CommentFixtureAdapter:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(mediacrawler_timeout_seconds=30)
        self.calls = 0

    async def health_check(self):  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    async def invoke(
        self,
        invocation: MediaCrawlerInvocation,
    ) -> MediaCrawlerResultEnvelope:
        self.calls += 1
        now = datetime.now(UTC)
        return MediaCrawlerResultEnvelope(
            protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=MediaCrawlerResultStatus.SUCCESS,
            items=[
                {
                    "note_id": "comment-post-1",
                    "content": "主内容成功",
                    "create_time": 1786086000,
                    "note_url": "https://m.weibo.cn/detail/comment-post-1",
                    "creator_hash": "author-hash",
                    "nickname": "测***户",
                }
            ],
            comments=[
                {
                    "comment_id": "comment-1",
                    "create_time": 1786086010,
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


def _runtime(connector: MediaCrawlerConnector) -> CollectorRuntime:
    registry = ConnectorRegistry()
    registry.register("mediacrawler", lambda: connector)
    return CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )


def _task(
    instance_id,
    source_id,
    account_id,
    *,
    mode: str = "search",
):  # type: ignore[no-untyped-def]
    return CollectionTask(
        task_id=uuid4(),
        connector_instance_id=instance_id,
        source_id=source_id,
        platform_account_id=account_id,
        mode=mode,
        requested_limit=5,
        checkpoint_version=None,
        trigger_type=TriggerType.TEST,
        triggered_by="m2b-tester",
        created_at=datetime.now(UTC),
    )


@pytest.mark.usefixtures("clean_database")
async def test_comments_persist_idempotently_without_rolling_back_signal(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        source_config={
            "keyword": "AI 编辑部",
            "include_comments": True,
            "comment_limit": 2,
            "include_subcomments": False,
        },
    )
    await CollectionBudgetService(db_session).create(
        scope_type="connector",
        scope_key=str(instance_id),
        values={
            "max_runs_per_day": 10,
            "max_items_per_run": 10,
            "max_items_per_day": 100,
            "max_comments_per_run": 10,
            "max_comments_per_day": 100,
            "max_concurrency": 1,
            "timezone": "UTC",
            "enabled": True,
        },
        actor="admin",
    )
    adapter = CommentFixtureAdapter()
    runtime = _runtime(
        MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
    )
    first = await runtime.execute(_task(instance_id, source_id, account_id))
    second = await runtime.execute(_task(instance_id, source_id, account_id))

    assert first.status is ConnectorRunStatus.PARTIAL
    assert second.status is ConnectorRunStatus.PARTIAL
    assert int(
        await db_session.scalar(select(func.count()).select_from(RawSignalRecord)) or 0
    ) == 1
    assert int(
        await db_session.scalar(
            select(func.count()).select_from(RawSignalCommentRecord)
        )
        or 0
    ) == 1
    stored = await db_session.scalar(select(RawSignalCommentRecord))
    assert stored is not None
    assert stored.parent_comment_id == "parent-fixture"
    assert stored.raw_payload["cookie"] == "[REDACTED]"
    checkpoint = await db_session.scalar(
        select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.source_id == source_id
        )
    )
    assert checkpoint is not None
    assert checkpoint.checkpoint_data == {}
    assert checkpoint.version == 1


@pytest.mark.usefixtures("clean_database")
async def test_comment_database_concurrency_fk_and_cascade(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(db_session)
    runtime = _runtime(
        MediaCrawlerConnector(  # type: ignore[arg-type]
            adapter=CommentFixtureAdapter()
        )
    )
    result = await runtime.execute(_task(instance_id, source_id, account_id))
    assert result.status is ConnectorRunStatus.PARTIAL
    signal = await db_session.scalar(select(RawSignalRecord))
    assert signal is not None

    concurrent = CollectedComment(
        platform="weibo",
        content_external_id="comment-post-1",
        external_comment_id="concurrent-comment",
        author_id="author",
        author_name="name",
        text="并发评论",
        published_at=datetime.now(UTC),
        like_count=1,
        parent_comment_id=None,
        raw_payload={"token": "fixture-value-token"},
    )

    async def insert_once():  # type: ignore[no-untyped-def]
        async with get_async_sessionmaker()() as session:
            return await RawSignalCommentService(session).ingest(
                raw_signal_id=signal.id,
                comment=concurrent,
            )

    outcomes = await asyncio.gather(insert_once(), insert_once())
    assert sum(1 for item in outcomes if item.created) == 1
    assert sum(1 for item in outcomes if item.duplicate) == 1
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(RawSignalCommentRecord)
            .where(
                RawSignalCommentRecord.external_comment_id
                == "concurrent-comment"
            )
        )
        or 0
    ) == 1

    missing_parent = CollectedComment(
        platform="weibo",
        content_external_id="missing-post",
        external_comment_id="missing-parent-comment",
        author_id=None,
        author_name=None,
        text="FK fixture",
        published_at=datetime.now(UTC),
        like_count=None,
        parent_comment_id=None,
    )
    with pytest.raises(IntegrityError):
        async with get_async_sessionmaker()() as session:
            await RawSignalCommentService(session).ingest(
                raw_signal_id=uuid4(),
                comment=missing_parent,
            )

    async with get_async_sessionmaker()() as session:
        async with session.begin():
            await session.execute(
                delete(RawSignalRecord).where(RawSignalRecord.id == signal.id)
            )
    assert int(
        await db_session.scalar(
            select(func.count()).select_from(RawSignalCommentRecord)
        )
        or 0
    ) == 0


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
    adapter = CommentFixtureAdapter()
    with pytest.raises(PreflightRejectedError):
        await _runtime(
            MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
        ).execute(
            _task(instance_id, source_id, account_id, mode="comments")
        )
    assert adapter.calls == 0


@pytest.mark.usefixtures("clean_database")
async def test_comment_budget_multiplies_per_item_limit_before_adapter(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance_id, source_id, account_id = await _setup(
        db_session,
        source_config={
            "keyword": "AI 编辑部",
            "include_comments": True,
            "comment_limit": 3,
            "include_subcomments": False,
        },
    )
    await CollectionBudgetService(db_session).create(
        scope_type="connector",
        scope_key=str(instance_id),
        values={
            "max_runs_per_day": 10,
            "max_items_per_run": 10,
            "max_items_per_day": 100,
            "max_comments_per_run": 10,
            "max_comments_per_day": 100,
            "max_concurrency": 1,
            "timezone": "UTC",
            "enabled": True,
        },
        actor="admin",
    )
    adapter = CommentFixtureAdapter()
    with pytest.raises(BudgetExceededError):
        await _runtime(
            MediaCrawlerConnector(adapter=adapter)  # type: ignore[arg-type]
        ).execute(_task(instance_id, source_id, account_id))
    assert adapter.calls == 0
