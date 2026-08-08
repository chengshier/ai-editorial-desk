import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from packages.clustering.services import ClusterOutcomeStatus, EventClusteringService
from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.events.services import EventService
from tests.m3c_helpers import add_test_embeddings, auto_cluster, create_m3c_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_clustering_create_attach_distinct_and_ambiguous_flow(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    base_time = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    signal_a = await create_m3c_signal(
        db_session,
        source,
        external_id="cluster-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
        platform="rss",
        published_at=base_time,
    )
    outcome_a = await auto_cluster(db_session, signal_a.id)
    assert outcome_a.status is ClusterOutcomeStatus.CREATED_EVENT
    assert outcome_a.event_id is not None

    signal_b = await create_m3c_signal(
        db_session,
        source,
        external_id="cluster-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营。最新",
        platform="weibo",
        published_at=base_time + timedelta(minutes=10),
    )
    outcome_b = await auto_cluster(db_session, signal_b.id)
    assert outcome_b.status is ClusterOutcomeStatus.ATTACHED
    assert outcome_b.event_id == outcome_a.event_id

    association_b = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == signal_b.id)
    )
    assert association_b is not None
    assert association_b.relation is EventSignalRelation.RELATED
    assert association_b.attached_by is EventSignalAttachedBy.RULE

    event_one = await db_session.get(EventRecord, outcome_a.event_id)
    assert event_one is not None
    assert event_one.source_count == 1
    assert event_one.platform_count == 2
    assert event_one.first_seen_at == base_time
    await db_session.commit()

    signal_c = await create_m3c_signal(
        db_session,
        source,
        external_id="cluster-c",
        title="本地球队夺得联赛冠军",
        text="球迷在主场庆祝赛季冠军",
        published_at=base_time + timedelta(minutes=20),
    )
    outcome_c = await auto_cluster(db_session, signal_c.id)
    assert outcome_c.status is ClusterOutcomeStatus.CREATED_EVENT
    assert outcome_c.event_id is not None
    assert outcome_c.event_id != outcome_a.event_id

    signal_d = await create_m3c_signal(
        db_session,
        source,
        external_id="cluster-d",
        title="三号线暴雨后交通受阻",
        text="道路积水和轨道交通都受到影响",
        published_at=base_time + timedelta(minutes=30),
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-cluster-v1",
        vectors={signal_a.id: (1.0, 0.0), signal_d.id: (0.99, 0.05)},
    )
    outcome_d = await auto_cluster(
        db_session, signal_d.id, embedding_version="m3c-cluster-v1"
    )
    assert outcome_d.status is ClusterOutcomeStatus.AMBIGUOUS
    assert await db_session.scalar(
        select(func.count())
        .select_from(EventSignalRecord)
        .where(EventSignalRecord.signal_id == signal_d.id)
    ) == 0


@pytest.mark.usefixtures("clean_database")
async def test_combined_embedding_path_attaches_with_embedding_provenance(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="embedding-cluster-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    first_outcome = await auto_cluster(db_session, first.id)
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="embedding-cluster-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营消息",
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-cluster-v1",
        vectors={first.id: (1.0, 0.0), second.id: (0.99, 0.05)},
    )
    outcome = await auto_cluster(
        db_session, second.id, embedding_version="m3c-cluster-v1"
    )
    assert outcome.status is ClusterOutcomeStatus.ATTACHED
    assert outcome.event_id == first_outcome.event_id
    association = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == second.id)
    )
    assert association is not None
    assert association.relation is EventSignalRelation.RELATED
    assert association.attached_by is EventSignalAttachedBy.EMBEDDING


@pytest.mark.usefixtures("clean_database")
async def test_human_membership_is_never_overwritten_by_clustering(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session, source, external_id="human-member", title="人工事件", text="人工确认内容"
    )
    event = await EventService(db_session).create(
        title="人工建立的 Event",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="editor",
    )
    await EventService(db_session).attach_signal(
        event_id=event.id,
        signal_id=signal.id,
        relation=EventSignalRelation.REPORT,
        confidence=0.8,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )
    outcome = await auto_cluster(db_session, signal.id)
    assert outcome.status is ClusterOutcomeStatus.SKIPPED
    assert outcome.code == "HUMAN_MEMBERSHIP_PRESERVED"
    association = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == signal.id)
    )
    assert association is not None
    assert association.relation is EventSignalRelation.REPORT
    assert association.attached_by is EventSignalAttachedBy.HUMAN
    assert association.confidence == 0.8


@pytest.mark.usefixtures("clean_database")
async def test_multiple_candidate_events_stays_ambiguous(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    candidate_a = await create_m3c_signal(
        db_session, source, external_id="multi-a", title="同一标题", text="同一正文"
    )
    candidate_b = await create_m3c_signal(
        db_session, source, external_id="multi-b", title="同一标题", text="同一正文"
    )
    target = await create_m3c_signal(
        db_session, source, external_id="multi-target", title="同一标题", text="同一正文"
    )
    event_service = EventService(db_session)
    event_a = await event_service.create(
        title="人工 Event A",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )
    await event_service.attach_signal(
        event_id=event_a.id,
        signal_id=candidate_a.id,
        relation=EventSignalRelation.RELATED,
        confidence=1.0,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )
    event_b = await event_service.create(
        title="人工 Event B",
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language=None,
        entities=[],
        keywords=[],
        actor="editor",
    )
    await event_service.attach_signal(
        event_id=event_b.id,
        signal_id=candidate_b.id,
        relation=EventSignalRelation.RELATED,
        confidence=1.0,
        attached_by=EventSignalAttachedBy.HUMAN,
        actor="editor",
    )
    outcome = await auto_cluster(db_session, target.id)
    assert outcome.status is ClusterOutcomeStatus.AMBIGUOUS
    assert outcome.code == "MULTIPLE_CANDIDATE_EVENTS"
    assert set(outcome.candidate_event_ids) == {event_a.id, event_b.id}


@pytest.mark.usefixtures("clean_database")
async def test_two_workers_clustering_same_signal_produces_one_membership_and_event(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session,
        source,
        external_id="concurrent-cluster",
        title="独立事件",
        text="这是没有候选的独立事件正文",
    )
    signal_id = signal.id

    async def cluster_once():  # type: ignore[no-untyped-def]
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            return await EventClusteringService(session).cluster_signal(
                signal_id=signal_id,
                embedding_version=None,
                actor="concurrent-test",
            )

    first, second = await asyncio.gather(cluster_once(), cluster_once())
    statuses = {first.status, second.status}
    assert ClusterOutcomeStatus.CREATED_EVENT in statuses
    assert ClusterOutcomeStatus.SKIPPED in statuses
    assert int(
        await db_session.scalar(
            select(func.count())
            .select_from(EventSignalRecord)
            .where(EventSignalRecord.signal_id == signal_id)
        )
        or 0
    ) == 1
    assert int(await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0) == 1


@pytest.mark.usefixtures("clean_database")
async def test_clustering_does_not_modify_raw_signal_fields(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session,
        source,
        external_id="raw-immutable-cluster",
        title="不可变标题",
        text="不可变正文",
        platform="rss",
    )
    snapshot = (
        signal.original_url,
        signal.canonical_url,
        signal.external_id,
        signal.collected_at,
        dict(signal.raw_payload),
        signal.platform,
        signal.source_id,
        signal.content_hash,
    )
    await auto_cluster(db_session, signal.id)
    await db_session.refresh(signal)
    assert (
        signal.original_url,
        signal.canonical_url,
        signal.external_id,
        signal.collected_at,
        dict(signal.raw_payload),
        signal.platform,
        signal.source_id,
        signal.content_hash,
    ) == snapshot
    assert await db_session.get(RawSignalRecord, signal.id) is not None
