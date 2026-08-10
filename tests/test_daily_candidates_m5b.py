from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from packages.database.models import (
    AIInvocationRecord,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EventRecord,
    EventStatus,
    EventTrendSnapshotRecord,
)
from packages.editorial.candidates import (
    CANDIDATE_RANKING_VERSION,
    CandidateGenerationRequest,
    DailyCandidateService,
)
from packages.editorial.decisions import EditorialDecisionService
from packages.editorial.domain import stable_hash
from packages.editorial.services import EditorialScoringService
from packages.editorial.workflow_errors import (
    CandidateRunStaleError,
    EditorialDecisionConflictError,
    RiskAcknowledgementRequiredError,
    StaleCandidateContextError,
    WorkflowEventMergedError,
)
from packages.events.services import EventService
from packages.evidence.services import EventEvidenceService

AS_OF = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
EVENT_TIME = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 10, 11, 0, tzinfo=UTC)


async def _event(
    session,  # type: ignore[no-untyped-def]
    *,
    title: str,
    score: int | None,
    risk: EditorialRiskLevel = EditorialRiskLevel.R2,
    status: EventStatus = EventStatus.GROWING,
    update_value: float | None = None,
    signal_velocity: float | None = None,
) -> tuple[EventRecord, object | None]:
    event = await EventService(session).create(
        title=title,
        summary=None,
        category="social",
        status=status,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m5b-fixture",
    )
    async with session.begin():
        row = await session.get(EventRecord, event.id)
        assert row is not None
        row.last_updated_at = EVENT_TIME
    trend = None
    if update_value is not None or signal_velocity is not None:
        trend = EventTrendSnapshotRecord(
            event_id=event.id,
            calculation_version="trend-calculation-v1",
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END,
            signal_count=1,
            new_signal_count=1,
            source_count=1,
            platform_count=1,
            signal_velocity=signal_velocity,
            interaction_velocity=None,
            cross_source=False,
            cross_platform=False,
            semantic_novelty=None,
            cn_gap=None,
            update_value=update_value,
            feature_availability={},
            component_metrics={},
            input_hash=stable_hash({"event_id": str(event.id), "title": title}),
            created_at=EVENT_TIME,
        )
        async with session.begin():
            session.add(trend)
            await session.flush()
    editorial_score = None
    if score is not None:
        editorial_score = await EditorialScoringService().create_manual_score(
            event_id=event.id,
            trend_snapshot_id=trend.id if trend is not None else None,
            actor="m5b-fixture",
            reason="fixed M5-B ranking fixture",
            dimensions={
                "emotion": score,
                "information_gap": score,
                "visual_value": score,
                "user_relevance": score,
                "discussion": score,
                "novelty": score,
                "extendability": score,
            },
            risk_level=risk,
            recommended_format=(
                EditorialRecommendedFormat.FACT_CHECK
                if risk is EditorialRiskLevel.R4
                else EditorialRecommendedFormat.QUICK_EXPLAINER
            ),
            model_reason="offline fixture",
        )
    return event, editorial_score


def _request(limit: int = 20) -> CandidateGenerationRequest:
    return CandidateGenerationRequest(
        business_date=AS_OF.date(),
        timezone="UTC",
        as_of_at=AS_OF,
        lookback_hours=24,
        requested_limit=limit,
    )


@pytest.mark.usefixtures("clean_database")
async def test_candidate_ranking_v1_fixture_is_deterministic_and_explainable(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    high, _ = await _event(
        db_session,
        title="high normal",
        score=90,
        update_value=10,
        signal_velocity=1,
    )
    r3, _ = await _event(
        db_session,
        title="high R3 review",
        score=99,
        risk=EditorialRiskLevel.R3,
        update_value=100,
        signal_velocity=20,
    )
    r4, _ = await _event(
        db_session,
        title="R4 fact check",
        score=98,
        risk=EditorialRiskLevel.R4,
        update_value=90,
        signal_velocity=10,
    )
    update_high, _ = await _event(
        db_session,
        title="same score update high",
        score=70,
        update_value=80,
        signal_velocity=1,
    )
    update_low, _ = await _event(
        db_session,
        title="same score update low",
        score=70,
        update_value=20,
        signal_velocity=100,
    )
    velocity_high, _ = await _event(
        db_session,
        title="velocity high",
        score=60,
        update_value=30,
        signal_velocity=9,
    )
    velocity_low, _ = await _event(
        db_session,
        title="velocity low",
        score=60,
        update_value=30,
        signal_velocity=1,
    )
    tie_a, _ = await _event(db_session, title="full tie A", score=50)
    tie_b, _ = await _event(db_session, title="full tie B", score=50)
    no_trend, _ = await _event(db_session, title="no trend allowed", score=40)
    no_score, _ = await _event(db_session, title="no score skipped", score=None)
    merged, _ = await _event(db_session, title="merged skipped", score=100)
    merge_target, _ = await _event(db_session, title="merge target", score=20)
    resolved, _ = await _event(
        db_session,
        title="resolved skipped",
        score=100,
        status=EventStatus.RESOLVED,
    )
    archived, _ = await _event(db_session, title="archived skipped", score=100)
    dropped, _ = await _event(db_session, title="dropped still eligible", score=65)
    watched, _ = await _event(db_session, title="watched still eligible", score=64)
    overridden, overridden_score = await _event(
        db_session,
        title="human override",
        score=10,
    )
    assert overridden_score is not None

    async with db_session.begin():
        merged_row = await db_session.get(EventRecord, merged.id)
        assert merged_row is not None
        merged_row.merged_into_event_id = merge_target.id

    decisions = EditorialDecisionService()
    archive_decision = await decisions.decide(
        event_id=archived.id,
        decision=EditorialDecisionType.ARCHIVE,
        actor="editor",
        reason="not for future pools",
        confirmation=True,
    )
    assert archive_decision.decision.decision is EditorialDecisionType.ARCHIVE
    await decisions.decide(
        event_id=dropped.id,
        decision=EditorialDecisionType.DROP,
        actor="editor",
        reason="not today",
    )
    await decisions.decide(
        event_id=watched.id,
        decision=EditorialDecisionType.WATCH,
        actor="editor",
        reason="keep watching",
    )
    await EditorialScoringService().override_score(
        event_id=overridden.id,
        score_id=overridden_score.id,  # type: ignore[union-attr]
        actor="editor",
        reason="human raises editorial value",
        overridden_fields={
            "emotion": 95,
            "information_gap": 95,
            "visual_value": 95,
            "user_relevance": 95,
            "discussion": 95,
            "novelty": 95,
            "extendability": 95,
        },
    )

    before_ai = await db_session.scalar(select(func.count(AIInvocationRecord.id)))
    service = DailyCandidateService()
    first = await service.preview(_request())
    second = await service.preview(_request())
    after_ai = await db_session.scalar(select(func.count(AIInvocationRecord.id)))
    assert before_ai == after_ai
    assert first.input_hash == second.input_hash
    assert [item.event_id for item in first.candidates] == [
        item.event_id for item in second.candidates
    ]
    assert first.ranking_version == CANDIDATE_RANKING_VERSION

    by_event = {item.event_id: item for item in first.candidates}
    ids = [item.event_id for item in first.candidates]
    assert ids.index(high.id) < ids.index(update_high.id)
    assert ids.index(update_high.id) < ids.index(update_low.id)
    assert ids.index(velocity_high.id) < ids.index(velocity_low.id)
    assert ids.index(overridden.id) < ids.index(high.id)
    assert ids.index(r3.id) > ids.index(no_trend.id)
    assert ids.index(r4.id) > ids.index(no_trend.id)
    assert by_event[r3.id].candidate_group.value == "review_required"
    assert by_event[r4.id].candidate_group.value == "review_required"
    assert by_event[r4.id].recommended_format.value == "fact_check"
    assert by_event[no_trend.id].ranking_components["update_value"] is None
    assert dropped.id in by_event
    assert watched.id in by_event
    assert no_score.id not in by_event
    assert merged.id not in by_event
    assert resolved.id not in by_event
    assert archived.id not in by_event
    assert first.skip_summary["NO_EDITORIAL_ASSESSMENT"] == 1
    assert first.skip_summary["MERGED_EVENT"] == 1
    assert first.skip_summary["RESOLVED_EVENT"] == 1
    assert first.skip_summary["EDITORIALLY_ARCHIVED"] == 1

    tied = [
        item
        for item in first.candidates
        if item.event_id in {tie_a.id, tie_b.id}
    ]
    assert [str(item.event_id) for item in tied] == sorted(
        [str(tie_a.id), str(tie_b.id)]
    )


@pytest.mark.usefixtures("clean_database")
async def test_candidate_apply_is_idempotent_and_concurrent_safe(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    await _event(db_session, title="concurrent pool", score=80)
    service = DailyCandidateService()
    first, second = await asyncio.gather(
        service.apply(_request(), actor="editor-a", confirmed=True),
        service.apply(_request(), actor="editor-b", confirmed=True),
    )
    assert first.run.id == second.run.id
    assert {first.reused, second.reused} == {False, True}
    assert await db_session.scalar(
        select(func.count(DailyCandidateRunRecord.id))
    ) == 1
    assert await db_session.scalar(select(func.count(DailyCandidateRecord.id))) == 1


@pytest.mark.usefixtures("clean_database")
async def test_decision_risk_archive_restore_drop_and_stale_protection(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    risky, risky_score = await _event(
        db_session,
        title="R3 candidate",
        score=90,
        risk=EditorialRiskLevel.R3,
    )
    dropped, _ = await _event(db_session, title="drop reentry", score=70)
    archived, _ = await _event(db_session, title="archive restore", score=60)
    service = DailyCandidateService()
    applied = await service.apply(_request(), actor="editor", confirmed=True)
    candidates = {item.event_id: item for item in applied.candidates}
    decisions = EditorialDecisionService()

    with pytest.raises(RiskAcknowledgementRequiredError):
        await decisions.decide(
            event_id=risky.id,
            candidate_id=candidates[risky.id].id,
            decision=EditorialDecisionType.ADOPT,
            actor="editor",
            reason="accept risky fact check",
            risk_acknowledged=False,
        )
    adopted = await decisions.decide(
        event_id=risky.id,
        candidate_id=candidates[risky.id].id,
        decision=EditorialDecisionType.ADOPT,
        actor="editor",
        reason="accept risky fact check",
        risk_acknowledged=True,
    )
    assert adopted.decision.risk_level_snapshot is EditorialRiskLevel.R3

    dropped_decision = await decisions.decide(
        event_id=dropped.id,
        candidate_id=candidates[dropped.id].id,
        decision=EditorialDecisionType.DROP,
        actor="editor",
        reason="drop for now",
    )
    preview_after_drop = await service.preview(_request())
    assert dropped.id in {item.event_id for item in preview_after_drop.candidates}

    archived_decision = await decisions.decide(
        event_id=archived.id,
        candidate_id=candidates[archived.id].id,
        decision=EditorialDecisionType.ARCHIVE,
        actor="editor",
        reason="archive deliberately",
        confirmation=True,
    )
    preview_archived = await service.preview(_request())
    assert archived.id not in {
        item.event_id for item in preview_archived.candidates
    }
    restored = await decisions.decide(
        event_id=archived.id,
        decision=EditorialDecisionType.WATCH,
        expected_previous_decision_id=archived_decision.decision.id,
        actor="editor",
        reason="restore from archive",
        confirmation=True,
    )
    assert restored.decision.previous_decision_id == archived_decision.decision.id
    restored_preview = await service.preview(_request())
    assert archived.id in {item.event_id for item in restored_preview.candidates}

    assert risky_score is not None
    await EditorialScoringService().override_score(
        event_id=risky.id,
        score_id=risky_score.id,  # type: ignore[union-attr]
        actor="editor",
        reason="risk changed",
        overridden_fields={"risk_level": "R4"},
    )
    with pytest.raises(StaleCandidateContextError):
        await decisions.decide(
            event_id=risky.id,
            candidate_id=candidates[risky.id].id,
            decision=EditorialDecisionType.WATCH,
            expected_previous_decision_id=adopted.decision.id,
            actor="editor",
            reason="old candidate must be stale",
        )
    assert dropped_decision.decision.decision is EditorialDecisionType.DROP


@pytest.mark.usefixtures("clean_database")
async def test_candidate_evidence_merge_old_run_and_decision_concurrency(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    event, score = await _event(db_session, title="stale context", score=80)
    target, _ = await _event(db_session, title="merge target", score=20)
    service = DailyCandidateService()
    run1 = await service.apply(_request(), actor="editor", confirmed=True)
    candidate1 = next(
        item for item in run1.candidates if item.event_id == event.id
    )

    await EventEvidenceService().create_unknown(
        event_id=event.id,
        unknown_text="new unresolved detail",
        actor="editor",
    )
    with pytest.raises(StaleCandidateContextError):
        await EditorialDecisionService().decide(
            event_id=event.id,
            candidate_id=candidate1.id,
            decision=EditorialDecisionType.WATCH,
            actor="editor",
            reason="must refresh evidence",
        )

    assert score is not None
    await EditorialScoringService().override_score(
        event_id=event.id,
        score_id=score.id,  # type: ignore[union-attr]
        actor="editor",
        reason="new score context",
        overridden_fields={"emotion": 81},
    )
    run2 = await service.apply(_request(), actor="editor", confirmed=True)
    assert run2.run.id != run1.run.id
    with pytest.raises(CandidateRunStaleError):
        await EditorialDecisionService().decide(
            event_id=event.id,
            candidate_id=candidate1.id,
            decision=EditorialDecisionType.DROP,
            actor="editor",
            reason="old run is read only",
        )

    candidate2 = next(
        item for item in run2.candidates if item.event_id == event.id
    )
    async with db_session.begin():
        row = await db_session.get(EventRecord, event.id)
        assert row is not None
        row.merged_into_event_id = target.id
    with pytest.raises(WorkflowEventMergedError) as merged_error:
        await EditorialDecisionService().decide(
            event_id=event.id,
            candidate_id=candidate2.id,
            decision=EditorialDecisionType.ADOPT,
            actor="editor",
            reason="merged must be rejected",
            risk_acknowledged=True,
        )
    assert merged_error.value.details == {"target_event_id": str(target.id)}

    concurrent, _ = await _event(
        db_session,
        title="decision concurrency",
        score=75,
    )
    run3 = await service.apply(_request(), actor="editor", confirmed=True)
    candidate3 = next(
        item for item in run3.candidates if item.event_id == concurrent.id
    )

    async def decide(value: EditorialDecisionType) -> object:
        try:
            return await EditorialDecisionService().decide(
                event_id=concurrent.id,
                candidate_id=candidate3.id,
                decision=value,
                actor=f"editor-{value.value}",
                reason=f"concurrent {value.value}",
            )
        except Exception as exc:  # noqa: BLE001 - exact conflict asserted below
            return exc

    outcomes = await asyncio.gather(
        decide(EditorialDecisionType.ADOPT),
        decide(EditorialDecisionType.DROP),
    )
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    conflicts = [
        item
        for item in outcomes
        if isinstance(item, EditorialDecisionConflictError)
    ]
    assert len(conflicts) == 1
    history = list(
        await db_session.scalars(
            select(EditorialDecisionRecord)
            .where(EditorialDecisionRecord.event_id == concurrent.id)
            .order_by(
                EditorialDecisionRecord.created_at,
                EditorialDecisionRecord.id,
            )
        )
    )
    assert len(history) == 1
