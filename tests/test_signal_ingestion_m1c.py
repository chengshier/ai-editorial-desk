import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import ConnectorDefinition, RawSignalRecord
from packages.database.session import get_async_sessionmaker
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url

SECRET_A = "token-value-that-must-not-appear"


async def _source(db_session):  # type: ignore[no-untyped-def]
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
        name="RSS 实例",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={},
        actor="admin",
    )
    return await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="示例 Feed",
        source_type="rss",
        mode="feed",
        scope_key="https://example.com/feed.xml",
        external_ref="https://example.com/feed.xml",
        config={"language": "zh-CN"},
        enabled=True,
        actor="admin",
    )


def _normalized(  # type: ignore[no-untyped-def]
    source,
    *,
    external_id: str | None,
    url: str,
    title: str = "标题",
):
    raw = RawSignal(
        platform="rss",
        external_id=external_id,
        url=url,
        title=title,
        text="正文",
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
        raw_payload={"authorization": SECRET_A, "safe": "value"},
        language="zh-CN",
    )
    return NormalizedSignal.from_connector_signal(
        source_id=source.id,
        connector_instance_id=source.connector_instance_id,
        connector_run_id=None,
        connector_type="rss",
        signal=raw,
        canonical_url=normalize_http_url(url),
    )


@pytest.mark.usefixtures("clean_database")
async def test_raw_signal_insert_duplicate_and_sanitization(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    source = await _source(db_session)
    first = await RawSignalService(db_session).ingest_many(
        [
            _normalized(
                source,
                external_id="entry-1",
                url="https://example.com/a?utm_source=x",
            )
        ]
    )
    second = await RawSignalService(db_session).ingest_many(
        [
            _normalized(
                source,
                external_id="entry-1",
                url="https://example.com/changed",
            )
        ]
    )

    assert first[0].created is True
    assert second[0].duplicate is True
    assert first[0].signal_id == second[0].signal_id
    stored = await db_session.get(RawSignalRecord, first[0].signal_id)
    assert stored is not None
    assert stored.original_url == "https://example.com/a?utm_source=x"
    assert stored.canonical_url == "https://example.com/a"
    assert stored.raw_payload["authorization"] == "[REDACTED]"
    assert SECRET_A not in str(stored.raw_payload)


@pytest.mark.usefixtures("clean_database")
async def test_canonical_url_fallback_is_idempotent(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    source = await _source(db_session)
    service = RawSignalService(db_session)
    first = await service.ingest_many(
        [
            _normalized(
                source,
                external_id=None,
                url="https://example.com/a?utm_campaign=x",
            )
        ]
    )
    second = await service.ingest_many(
        [_normalized(source, external_id=None, url="https://example.com/a")]
    )
    assert first[0].created is True
    assert second[0].duplicate is True


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_raw_signal_insert_creates_one_row(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    source = await _source(db_session)
    source_id = source.id
    instance_id = source.connector_instance_id
    await db_session.commit()

    signal = RawSignal(
        platform="rss",
        external_id="concurrent-entry",
        url="https://example.com/concurrent",
        title="并发条目",
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    normalized = NormalizedSignal.from_connector_signal(
        source_id=source_id,
        connector_instance_id=instance_id,
        connector_run_id=None,
        connector_type="rss",
        signal=signal,
        canonical_url=normalize_http_url(signal.url),
    )

    async def insert_once():  # type: ignore[no-untyped-def]
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            return (await RawSignalService(session).ingest_many([normalized]))[0]

    results = await asyncio.gather(insert_once(), insert_once())
    assert sum(result.created for result in results) == 1
    assert sum(result.duplicate for result in results) == 1

    count = int(
        await db_session.scalar(
            select(func.count()).select_from(RawSignalRecord).where(
                RawSignalRecord.external_id == "concurrent-entry"
            )
        )
        or 0
    )
    assert count == 1
