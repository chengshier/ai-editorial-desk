from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.clustering.reprocessing import ClusteringReprocessService
from packages.clustering.repositories import (
    MatchOverrideRepository,
    SignalEventSuppressionRepository,
)
from packages.connector_management.exceptions import BusinessValidationError
from packages.database.models import (
    ClusteringProcessingRunRecord,
    EventAssignmentRecord,
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    MatchOverrideDecision,
    SignalFingerprintRecord,
    SignalMatchDecisionRecord,
)
from packages.events.services import EventService
from tests.m3c_helpers import create_m3c_signal, create_source


async def _event_with_signal(
    db_session,  # type: ignore[no-untyped-def]
    signal_id,
    *,
    title: str,
    attached_by: EventSignalAttachedBy = EventSignalAttachedBy.RULE,
    relation: EventSignalRelation = EventSignalRelation.RELATED,
    confidence: float = 1.0,
):  # type: ignore[no-untyped-def]
    service = EventService(db_session)
    event = await service.create(
        title=title,
        summary=None,
        category=None,
        status=EventStatus.EMERGING,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="test-editor",
    )
    await service.attach_signal(
        event_id=event.id,
        signal_id=signal_id,
        relation=relation,
        confidence=confidence,
        attached_by=attached_by,
        actor="test-editor",
    )
    return event


async def _membership_map(db_session, signal_ids):  # type: ignore[no-untyped-def]
    rows = list(
        (
            await db_session.execute(
                select(EventSignalRecord.signal_id, EventSignalRecord.event_id).where(
                    EventSignalRecord.signal_id.in_(signal_ids)
                )
            )
        ).all()
    )
    result = {signal_id: event_id for signal_id, event_id in rows}
    await db_session.rollback()
    return result


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_dry_run_changes_only_processing_audit(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="dry-a",
        title="同一事件",
        text="同一正文",
        url="https://example.com/dry/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="dry-b",
        title="同一事件",
        text="同一正文",
        url="https://example.com/dry/b",
    )
    await _event_with_signal(db_session, first.id, title="Fragment A")
    await _event_with_signal(db_session, second.id, title="Fragment B")
    signal_ids = [first.id, second.id]
    before_memberships = await _membership_map(db_session, signal_ids)
    before_event_count = int(
        await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0
    )
    before_decision_count = int(
        await db_session.scalar(select(func.count()).select_from(SignalMatchDecisionRecord)) or 0
    )
    before_fingerprint_count = int(
        await db_session.scalar(select(func.count()).select_from(SignalFingerprintRecord)) or 0
    )
    await db_session.rollback()

    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=signal_ids,
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=2,
        actor=None,
        apply=False,
        confirmed=False,
    )
    assert summary.dry_run is True
    assert summary.scanned == 2
    assert summary.would_move == 1
    assert summary.unchanged == 1
    assert summary.would_detach == 0
    assert await _membership_map(db_session, signal_ids) == before_memberships
    assert (
        int(await db_session.scalar(select(func.count()).select_from(EventRecord)) or 0)
        == before_event_count
    )
    assert int(
        await db_session.scalar(select(func.count()).select_from(SignalMatchDecisionRecord)) or 0
    ) == before_decision_count
    assert int(
        await db_session.scalar(select(func.count()).select_from(SignalFingerprintRecord)) or 0
    ) == before_fingerprint_count
    assert int(
        await db_session.scalar(select(func.count()).select_from(ClusteringProcessingRunRecord))
        or 0
    ) == 1


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_apply_converges_fragment_and_replay_is_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="apply-a",
        title="同一事件",
        text="同一正文",
        url="https://example.com/apply/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="apply-b",
        title="同一事件",
        text="同一正文",
        url="https://example.com/apply/b",
    )
    await _event_with_signal(db_session, first.id, title="Fragment A")
    await _event_with_signal(db_session, second.id, title="Fragment B")
    signal_ids = [first.id, second.id]

    first_run = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=signal_ids,
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=2,
        actor="m3d-test",
        apply=True,
        confirmed=True,
    )
    assert first_run.would_move == 1
    memberships = await _membership_map(db_session, signal_ids)
    assert len(set(memberships.values())) == 1
    assignment_count = int(
        await db_session.scalar(select(func.count()).select_from(EventAssignmentRecord)) or 0
    )
    await db_session.rollback()
    assert assignment_count == 1

    second_run = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=signal_ids,
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=2,
        actor="m3d-test",
        apply=True,
        confirmed=True,
    )
    assert second_run.would_move == 0
    assert second_run.would_attach == 0
    assert second_run.would_create_event == 0
    assert second_run.unchanged == 2
    assert int(
        await db_session.scalar(select(func.count()).select_from(EventAssignmentRecord)) or 0
    ) == assignment_count


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_never_changes_human_membership_relation_or_confidence(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    human_signal = await create_m3c_signal(
        db_session,
        source,
        external_id="human-protected",
        title="人工归属事件",
        text="人工确认正文",
    )
    event = await _event_with_signal(
        db_session,
        human_signal.id,
        title="Human Event",
        attached_by=EventSignalAttachedBy.HUMAN,
        relation=EventSignalRelation.REPORT,
        confidence=0.73,
    )
    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=[human_signal.id],
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=1,
        actor="m3d-test",
        apply=True,
        confirmed=True,
    )
    assert summary.skipped_human == 1
    await db_session.rollback()
    association = await db_session.scalar(
        select(EventSignalRecord).where(
            EventSignalRecord.event_id == event.id,
            EventSignalRecord.signal_id == human_signal.id,
        )
    )
    assert association is not None
    assert association.attached_by is EventSignalAttachedBy.HUMAN
    assert association.relation is EventSignalRelation.REPORT
    assert association.confidence == 0.73


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_respects_human_distinct_override_and_suppression(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="protect-a",
        title="同一标题",
        text="同一正文",
        url="https://example.com/protect/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="protect-b",
        title="同一标题",
        text="同一正文",
        url="https://example.com/protect/b",
    )
    first_event = await _event_with_signal(db_session, first.id, title="First")
    second_event = await _event_with_signal(db_session, second.id, title="Second")
    async with db_session.begin():
        await MatchOverrideRepository(db_session).upsert(
            left_signal_id=first.id,
            right_signal_id=second.id,
            decision=MatchOverrideDecision.DISTINCT,
            reason="人工确认不同现实事件",
            actor="editor",
        )
        await SignalEventSuppressionRepository(db_session).upsert_active(
            signal_id=first.id,
            event_id=second_event.id,
            reason="manual_split",
            actor="editor",
        )

    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=[first.id],
        time_from=None,
        time_to=None,
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=1,
        actor="m3d-test",
        apply=True,
        confirmed=True,
    )
    assert summary.would_move == 0
    assert summary.would_detach == 0
    membership = await db_session.scalar(
        select(EventSignalRecord).where(EventSignalRecord.signal_id == first.id)
    )
    assert membership is not None
    assert membership.event_id == first_event.id


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_is_bounded_and_rejects_unregistered_algorithm(db_session) -> None:  # type: ignore[no-untyped-def]
    service = ClusteringReprocessService(db_session)
    with pytest.raises(BusinessValidationError):
        await service.reprocess(
            signal_ids=None,
            time_from=None,
            time_to=None,
            algorithm_version="event-match-v1",
            embedding_version=None,
            max_items=10,
            actor=None,
        )
    with pytest.raises(BusinessValidationError):
        await service.reprocess(
            signal_ids=[],
            time_from=datetime(2026, 8, 8, tzinfo=UTC),
            time_to=datetime(2026, 8, 9, tzinfo=UTC),
            algorithm_version="event-match-v2",
            embedding_version=None,
            max_items=10,
            actor=None,
        )
    with pytest.raises(BusinessValidationError):
        await service.reprocess(
            signal_ids=[uuid4(), uuid4()],
            time_from=None,
            time_to=None,
            algorithm_version="event-match-v1",
            embedding_version=None,
            max_items=1,
            actor=None,
        )


@pytest.mark.usefixtures("clean_database")
async def test_reprocess_time_range_honors_max_items(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    base = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    for index in range(3):
        await create_m3c_signal(
            db_session,
            source,
            external_id=f"range-{index}",
            title=f"Range {index}",
            text=f"正文 {index}",
            published_at=base + timedelta(minutes=index),
        )
    summary = await ClusteringReprocessService(db_session).reprocess(
        signal_ids=None,
        time_from=base - timedelta(minutes=1),
        time_to=base + timedelta(minutes=5),
        algorithm_version="event-match-v1",
        embedding_version=None,
        max_items=2,
        actor=None,
        apply=False,
        confirmed=False,
    )
    assert summary.scanned == 2
