import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
)
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import (
    ConfigurationChangeLog,
    ConnectorDefinition,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.events.services import EventService
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url

SECRET = "m3a-secret-that-must-remain-redacted"


async def _sources(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="M3-A RSS 实例",
        config={"feed_urls": ["https://example.com/m3a.xml"]},
        schedule_config={},
        actor="m3a-test",
    )
    first = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M3-A 来源一",
        source_type="rss",
        mode="feed",
        scope_key="https://example.com/m3a-1.xml",
        external_ref="https://example.com/m3a-1.xml",
        config={},
        enabled=True,
        actor="m3a-test",
    )
    second = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="M3-A 来源二",
        source_type="rss",
        mode="feed",
        scope_key="https://example.com/m3a-2.xml",
        external_ref="https://example.com/m3a-2.xml",
        config={},
        enabled=True,
        actor="m3a-test",
    )
    return first, second


async def _signal(
    db_session,  # type: ignore[no-untyped-def]
    source,  # type: ignore[no-untyped-def]
    *,
    external_id: str,
    platform: str = "rss",
    published_at: datetime | None,
    collected_at: datetime,
) -> RawSignalRecord:
    raw = RawSignal(
        platform=platform,
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=f"信号 {external_id}",
        text="原始信号正文",
        published_at=published_at,
        raw_payload={"authorization": SECRET, "safe": external_id},
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
    result = (await RawSignalService(db_session).ingest_many([normalized]))[0]
    stored = await db_session.get(RawSignalRecord, result.signal_id)
    assert stored is not None
    stored.collected_at = collected_at
    await db_session.commit()
    return stored


async def _event(
    session,  # type: ignore[no-untyped-def]
    *,
    title: str = "人工事件",
    status: EventStatus = EventStatus.EMERGING,
):
    return await EventService(session).create(
        title=title,
        summary=None,
        category=None,
        status=status,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )


@pytest.mark.usefixtures("clean_database")
async def test_event_create_read_list_status_utc_and_nullable_fields(db_session) -> None:  # type: ignore[no-untyped-def]
    first = await _event(db_session)
    second = await _event(db_session, title="稳定事件", status=EventStatus.STABLE)

    loaded = await EventService(db_session).get(first.id)
    assert loaded.id == first.id
    assert loaded.status is EventStatus.EMERGING
    assert loaded.summary is None
    assert loaded.category is None
    assert loaded.primary_language is None
    assert loaded.entities == []
    assert loaded.keywords == []
    assert loaded.first_seen_at is None
    assert loaded.source_count == 0
    assert loaded.platform_count == 0
    assert loaded.last_updated_at.tzinfo is not None
    assert loaded.last_updated_at.utcoffset() == timedelta(0)

    page = await EventService(db_session).list(page=1, page_size=1, status=None)
    assert page.total == 2
    assert page.has_next is True
    stable = await EventService(db_session).list(
        page=1, page_size=20, status=EventStatus.STABLE.value
    )
    assert [item.id for item in stable.items] == [second.id]


@pytest.mark.usefixtures("clean_database")
async def test_attach_is_idempotent_and_does_not_modify_raw_signal(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    published = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
    signal = await _signal(
        db_session,
        source,
        external_id="idempotent",
        published_at=published,
        collected_at=datetime(2026, 8, 7, 8, 5, tzinfo=UTC),
    )
    original = {
        "original_url": signal.original_url,
        "canonical_url": signal.canonical_url,
        "external_id": signal.external_id,
        "collected_at": signal.collected_at,
        "raw_payload": dict(signal.raw_payload),
        "platform": signal.platform,
        "source_id": signal.source_id,
    }
    event = await _event(db_session)
    service = EventService(db_session)

    association, created = await service.attach_signal(
        event_id=event.id,
        signal_id=signal.id,
        relation=EventSignalRelation.ORIGIN,
        confidence=0.9,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )
    after_first = (await service.get(event.id)).last_updated_at
    duplicate, duplicate_created = await service.attach_signal(
        event_id=event.id,
        signal_id=signal.id,
        relation=EventSignalRelation.REPORT,
        confidence=0.1,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == association.id
    assert duplicate.relation is EventSignalRelation.ORIGIN
    assert duplicate.confidence == pytest.approx(0.9)
    refreshed_event = await service.get(event.id)
    assert refreshed_event.source_count == 1
    assert refreshed_event.platform_count == 1
    assert refreshed_event.first_seen_at == published
    assert refreshed_event.last_updated_at == after_first

    refreshed_signal = await db_session.get(RawSignalRecord, signal.id)
    assert refreshed_signal is not None
    assert refreshed_signal.original_url == original["original_url"]
    assert refreshed_signal.canonical_url == original["canonical_url"]
    assert refreshed_signal.external_id == original["external_id"]
    assert refreshed_signal.collected_at == original["collected_at"]
    assert refreshed_signal.raw_payload == original["raw_payload"]
    assert refreshed_signal.platform == original["platform"]
    assert refreshed_signal.source_id == original["source_id"]
    assert SECRET not in str(refreshed_signal.raw_payload)


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_duplicate_attach_creates_one_relationship(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    signal = await _signal(
        db_session,
        source,
        external_id="concurrent",
        published_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 7, 9, 1, tzinfo=UTC),
    )
    event = await _event(db_session)
    event_id = event.id
    signal_id = signal.id

    async def attach_once() -> bool:
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            _, created = await EventService(session).attach_signal(
                event_id=event_id,
                signal_id=signal_id,
                relation=EventSignalRelation.REPORT,
                confidence=0.8,
                attached_by=EventSignalAttachedBy.HUMAN,
                actor="concurrent-editor",
            )
            return created

    results = await asyncio.gather(attach_once(), attach_once())
    assert sorted(results) == [False, True]
    count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(EventSignalRecord)
            .where(
                EventSignalRecord.event_id == event_id,
                EventSignalRecord.signal_id == signal_id,
            )
        )
        or 0
    )
    assert count == 1


@pytest.mark.usefixtures("clean_database")
async def test_attach_rejects_missing_event_and_missing_raw_signal(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    signal = await _signal(
        db_session,
        source,
        external_id="missing-targets",
        published_at=None,
        collected_at=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
    )
    event = await _event(db_session)
    signal_id = signal.id
    event_id = event.id
    service = EventService(db_session)

    with pytest.raises(ResourceNotFoundError):
        await service.attach_signal(
            event_id=signal_id,
            signal_id=signal_id,
            relation=EventSignalRelation.REPORT,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )
    with pytest.raises(ResourceNotFoundError):
        await service.attach_signal(
            event_id=event_id,
            signal_id=event_id,
            relation=EventSignalRelation.REPORT,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan"), float("inf")])
async def test_attach_rejects_invalid_confidence(db_session, confidence: float) -> None:  # type: ignore[no-untyped-def]
    event = await _event(db_session)
    with pytest.raises(BusinessValidationError):
        await EventService(db_session).attach_signal(
            event_id=event.id,
            signal_id=event.id,
            relation=EventSignalRelation.REPORT,
            confidence=confidence,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )


@pytest.mark.usefixtures("clean_database")
async def test_aggregates_first_seen_and_detach_recalculate_from_relationships(db_session) -> None:  # type: ignore[no-untyped-def]
    source_one, source_two = await _sources(db_session)
    signal_one = await _signal(
        db_session,
        source_one,
        external_id="aggregate-1",
        platform="rss",
        published_at=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 7, 10, 5, tzinfo=UTC),
    )
    signal_two = await _signal(
        db_session,
        source_one,
        external_id="aggregate-2",
        platform="rss",
        published_at=None,
        collected_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )
    signal_three = await _signal(
        db_session,
        source_two,
        external_id="aggregate-3",
        platform="bilibili",
        published_at=datetime(2026, 8, 7, 11, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 7, 11, 1, tzinfo=UTC),
    )
    event = await _event(db_session)
    service = EventService(db_session)

    for signal in (signal_one, signal_two, signal_three):
        await service.attach_signal(
            event_id=event.id,
            signal_id=signal.id,
            relation=EventSignalRelation.REPORT,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )

    aggregated = await service.get(event.id)
    assert aggregated.source_count == 2
    assert aggregated.platform_count == 2
    assert aggregated.first_seen_at == datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    before_detach = aggregated.last_updated_at

    assert await service.detach_signal(
        event_id=event.id, signal_id=signal_two.id, actor="editor"
    )
    after_detach = await service.get(event.id)
    assert after_detach.source_count == 2
    assert after_detach.platform_count == 2
    assert after_detach.first_seen_at == datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
    assert after_detach.last_updated_at > before_detach

    await service.detach_signal(event_id=event.id, signal_id=signal_one.id, actor="editor")
    await service.detach_signal(event_id=event.id, signal_id=signal_three.id, actor="editor")
    empty = await service.get(event.id)
    assert empty.source_count == 0
    assert empty.platform_count == 0
    assert empty.first_seen_at is None
    assert await db_session.get(RawSignalRecord, signal_one.id) is not None
    assert await db_session.get(RawSignalRecord, signal_two.id) is not None
    assert await db_session.get(RawSignalRecord, signal_three.id) is not None


@pytest.mark.usefixtures("clean_database")
async def test_same_raw_signal_can_belong_to_multiple_events(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    signal = await _signal(
        db_session,
        source,
        external_id="multi-event",
        published_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 7, 12, 1, tzinfo=UTC),
    )
    first = await _event(db_session, title="事件一")
    second = await _event(db_session, title="事件二")
    service = EventService(db_session)

    for event in (first, second):
        _, created = await service.attach_signal(
            event_id=event.id,
            signal_id=signal.id,
            relation=EventSignalRelation.REPORT,
            confidence=0.7,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )
        assert created is True

    count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(EventSignalRecord)
            .where(EventSignalRecord.signal_id == signal.id)
        )
        or 0
    )
    assert count == 2


@pytest.mark.usefixtures("clean_database")
async def test_failed_event_operation_does_not_pollute_raw_signal(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    signal = await _signal(
        db_session,
        source,
        external_id="failure-safety",
        published_at=None,
        collected_at=datetime(2026, 8, 7, 13, 0, tzinfo=UTC),
    )
    signal_id = signal.id
    before_payload = dict(signal.raw_payload)

    with pytest.raises(ResourceNotFoundError):
        await EventService(db_session).attach_signal(
            event_id=signal_id,
            signal_id=signal_id,
            relation=EventSignalRelation.REPORT,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="editor",
        )

    stored = await db_session.get(RawSignalRecord, signal_id)
    assert stored is not None
    assert stored.raw_payload == before_payload
    assert (
        int(
            await db_session.scalar(
                select(func.count())
                .select_from(EventSignalRecord)
                .where(EventSignalRecord.signal_id == signal_id)
            )
            or 0
        )
        == 0
    )


@pytest.mark.usefixtures("clean_database")
async def test_attach_and_detach_reuse_existing_audit_log(db_session) -> None:  # type: ignore[no-untyped-def]
    source, _ = await _sources(db_session)
    signal = await _signal(
        db_session,
        source,
        external_id="audit",
        published_at=datetime(2026, 8, 7, 14, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 7, 14, 1, tzinfo=UTC),
    )
    event = await _event(db_session)
    service = EventService(db_session)
    await service.attach_signal(
        event_id=event.id,
        signal_id=signal.id,
        relation=EventSignalRelation.OFFICIAL_RESPONSE,
        confidence=0.95,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="auditor",
    )
    await service.detach_signal(event_id=event.id, signal_id=signal.id, actor="auditor")

    actions = list(
        await db_session.scalars(
            select(ConfigurationChangeLog.action)
            .where(ConfigurationChangeLog.entity_id == event.id)
            .order_by(ConfigurationChangeLog.created_at)
        )
    )
    assert actions == ["create", "attach_signal", "detach_signal"]
