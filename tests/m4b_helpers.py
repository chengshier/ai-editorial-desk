from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import (
    ConnectorDefinition,
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRelation,
    EventStatus,
    RawSignalRecord,
)
from packages.events.services import EventService
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url


async def create_event_context(
    session: AsyncSession,
    *,
    texts: list[str],
    title: str = "M4-B Evidence Event",
) -> tuple[EventRecord, list[RawSignalRecord]]:
    await ConnectorDefinitionSyncService(session).sync()
    definition = await session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    await session.commit()

    suffix = uuid4().hex[:8]
    instance = await ConnectorInstanceService(session).create(
        definition_id=definition.id,
        name=f"M4-B RSS {suffix}",
        config={"feed_urls": [f"https://example.com/{suffix}.xml"]},
        schedule_config={},
        actor="m4b-test",
    )
    source = await SourceService(session).create(
        connector_instance_id=instance.id,
        name=f"M4-B Source {suffix}",
        source_type="rss",
        mode="feed",
        scope_key=f"https://example.com/{suffix}.xml",
        external_ref=f"https://example.com/{suffix}.xml",
        config={},
        enabled=True,
        actor="m4b-test",
    )

    event = await EventService(session).create(
        title=title,
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m4b-test",
    )

    signals: list[RawSignalRecord] = []
    base_time = datetime(2026, 8, 9, 5, 0, tzinfo=UTC)
    for index, text in enumerate(texts):
        external_id = f"m4b-{suffix}-{index}"
        raw = RawSignal(
            platform="rss",
            external_id=external_id,
            url=f"https://example.com/{external_id}",
            title=f"Evidence signal {index}",
            text=text,
            published_at=base_time + timedelta(minutes=index),
            raw_payload={
                "authorization": "secret-that-must-not-enter-evidence",
                "raw_only": f"raw-{index}",
            },
            language="zh-CN",
        )
        normalized = NormalizedSignal.from_connector_signal(
            source_id=source.id,
            connector_instance_id=source.connector_instance_id,
            connector_run_id=None,
            connector_type="rss",
            signal=raw,
            canonical_url=normalize_http_url(raw.url),
        )
        ingestion = (await RawSignalService(session).ingest_many([normalized]))[0]
        stored = await session.get(RawSignalRecord, ingestion.signal_id)
        assert stored is not None
        signals.append(stored)
        await EventService(session).attach_signal(
            event_id=event.id,
            signal_id=stored.id,
            relation=EventSignalRelation.RELATED,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="m4b-test",
        )
    await session.commit()
    return event, signals
