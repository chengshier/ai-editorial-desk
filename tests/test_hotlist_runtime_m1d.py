from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import BaseConnector, CollectionResult, CollectRequest, RawSignal
from packages.connectors.registry import ConnectorRegistry
from packages.database.models import ConnectorDefinition, ConnectorRunStatus, RawSignalRecord
from packages.database.session import get_async_sessionmaker
from packages.signals.services import SourceService


class StableHotlistConnector(BaseConnector):
    connector_type = "hotlist"

    async def health_check(self) -> dict[str, object]:
        return {"implemented": True}

    async def collect(self, request: CollectRequest) -> CollectionResult:
        del request
        return CollectionResult(
            signals=(
                RawSignal(
                    platform="baidu_hot_search",
                    external_id="baidu-realtime:stable-topic",
                    url="https://www.baidu.com/s?wd=stable-topic",
                    title="稳定热榜话题",
                    metrics={"rank": 1, "hot_score": 123456},
                    raw_payload={"source": "baidu_realtime", "rank": 1},
                    language="zh-CN",
                ),
            ),
            checkpoint={"source": "baidu_realtime", "top_external_ids": ["stable-topic"]},
        )


@pytest.mark.usefixtures("clean_database")
async def test_hotlist_repeated_runtime_runs_are_raw_signal_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "hotlist",
            ConnectorDefinition.platform == "hotlist",
        )
    )
    assert definition is not None
    definition_id = definition.id
    await db_session.commit()

    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"m1d-hotlist-{uuid4()}",
        config={"sources": ["baidu_realtime"]},
        schedule_config={},
        actor="admin",
    )
    instance = await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="百度实时热榜",
        source_type="hotlist",
        mode="hotlist",
        scope_key=f"baidu-realtime:{uuid4()}",
        external_ref="https://top.baidu.com/board?tab=realtime",
        config={"sources": ["baidu_realtime"]},
        enabled=True,
        actor="admin",
    )
    instance_id = instance.id
    source_id = source.id
    await db_session.rollback()

    registry = ConnectorRegistry()
    registry.register("hotlist", StableHotlistConnector)
    runtime = CollectorRuntime(
        session_factory=get_async_sessionmaker(),
        registry=registry,
    )

    async def execute_once() -> object:
        return await runtime.execute(
            CollectionTask(
                task_id=uuid4(),
                connector_instance_id=instance_id,
                source_id=source_id,
                platform_account_id=None,
                mode="hotlist",
                requested_limit=5,
                checkpoint_version=None,
                trigger_type=TriggerType.TEST,
                triggered_by="tester",
                created_at=datetime.now(UTC),
            )
        )

    first = await execute_once()
    second = await execute_once()
    assert first.status is ConnectorRunStatus.SUCCEEDED
    assert first.inserted_count == 1
    assert first.duplicate_count == 0
    assert second.status is ConnectorRunStatus.SUCCEEDED
    assert second.inserted_count == 0
    assert second.duplicate_count == 1

    await db_session.rollback()
    count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(RawSignalRecord)
            .where(RawSignalRecord.source_id == source_id)
        )
        or 0
    )
    assert count == 1
