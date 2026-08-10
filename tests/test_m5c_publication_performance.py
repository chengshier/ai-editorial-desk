from __future__ import annotations

import asyncio
from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, func, select

from packages.database.models import (
    CandidateGroup,
    CandidateRunMode,
    CandidateRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    DraftCitationUsage,
    DraftType,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialRiskLevel,
    EventRecord,
    EventStatus,
)
from packages.database.models.publication import (
    PerformanceHorizon,
    PublicationMode,
    PublicationPerformanceSnapshotRecord,
    PublicationRecord,
)
from packages.database.session import get_async_engine, get_async_sessionmaker
from packages.editorial.drafts_services import DraftService, HumanDraftReference
from packages.editorial.performance_imports import PerformanceImportService
from packages.editorial.performance_queries import PerformanceFeedbackQueryService
from packages.editorial.publication_domain import (
    EditorialAdoptionRequiredError,
    PerformanceMetrics,
    PerformanceValidationError,
    PublicationEventMergedError,
    PublicationValidationError,
    normalize_public_url,
)
from packages.editorial.publication_services import (
    PublicationPerformanceService,
    PublicationService,
)
from packages.events.services import EventService
from tests.m4d_helpers import BASE_TIME, create_m4d_context

pytestmark = pytest.mark.usefixtures("clean_database")
ACTOR = "m5c-test"


async def _simple_event(title: str) -> EventRecord:
    factory = get_async_sessionmaker()
    async with factory() as session:
        return await EventService(session).create(
            title=title,
            summary=None,
            category="social",
            status=EventStatus.GROWING,
            primary_language="zh-CN",
            entities=[],
            keywords=[],
            actor=ACTOR,
        )


async def _backfill_publication(suffix: str) -> PublicationRecord:
    event_record = await _simple_event(f"Backfill {suffix}")
    outcome = await PublicationService().create(
        event_id=event_record.id,
        publication_mode=PublicationMode.MANUAL_BACKFILL,
        platform_key="test.platform",
        public_url=f"https://example.com/posts/{suffix}",
        external_post_id=f"post-{suffix}",
        published_at=BASE_TIME,
        actor=ACTOR,
        backfill_reason="Historical publication imported manually.",
    )
    return outcome.publication


async def _workflow_fixture() -> tuple[UUID, UUID, UUID, UUID]:
    factory = get_async_sessionmaker()
    async with factory() as session:
        context = await create_m4d_context(session, title="M5-C workflow event")
    draft = await DraftService().create_manual(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor=ACTOR,
        reason="Exact human draft for publication fixture",
        body="监管部门确认已启动调查，后续以正式结果为准。",
        references=[
            HumanDraftReference(
                claim_id=context.claims["confirmed"].id,
                section_key="main",
                usage=DraftCitationUsage.FACT,
            )
        ],
        title="M5-C workflow title",
    )
    async with factory() as session:
        async with session.begin():
            run = DailyCandidateRunRecord(
                business_date=date(2026, 8, 10),
                as_of_at=BASE_TIME,
                mode=CandidateRunMode.MANUAL,
                candidate_policy_version="candidate-ranking-v1",
                weights_version="editorial-score-v1",
                status=CandidateRunStatus.SUCCEEDED,
                candidate_count=1,
                run_hash="1" * 64,
                actor=ACTOR,
                failure_code=None,
                error_summary=None,
            )
            session.add(run)
            await session.flush()
            candidate = DailyCandidateRecord(
                run_id=run.id,
                event_id=context.event.id,
                candidate_group=CandidateGroup.TOP,
                rank=3,
                base_editorial_score_id=context.score.id,
                base_traffic_total=context.score.traffic_total,
                effective_assessment_hash="2" * 64,
                effective_traffic_total=context.score.traffic_total,
                effective_risk_level=context.score.risk_level,
                recommended_format=context.score.recommended_format,
                freshness_score=80.0,
                opportunity_score=75.0,
                rank_score=78.0,
                candidate_context_hash="3" * 64,
            )
            session.add(candidate)
            await session.flush()
            decision = EditorialDecisionRecord(
                event_id=context.event.id,
                candidate_id=candidate.id,
                decision=EditorialDecisionType.ADOPT,
                risk_level_snapshot=context.score.risk_level,
                effective_traffic_total_snapshot=context.score.traffic_total,
                actor=ACTOR,
                reason="Adopt for publication fixture",
            )
            session.add(decision)
            await session.flush()
            return context.event.id, draft.id, candidate.id, decision.id


@pytest.mark.asyncio
async def test_workflow_publication_freezes_exact_provenance() -> None:
    event_id, draft_id, candidate_id, decision_id = await _workflow_fixture()
    publication = (
        await PublicationService().create(
            event_id=event_id,
            publication_mode=PublicationMode.WORKFLOW,
            platform_key="video.example",
            public_url="https://video.example/p/123#ignored",
            external_post_id="123",
            published_at=BASE_TIME + timedelta(hours=1),
            actor=ACTOR,
            draft_id=draft_id,
        )
    ).publication
    assert publication.draft_id == draft_id
    assert publication.draft_version_snapshot == 1
    assert publication.candidate_id == candidate_id
    assert publication.candidate_rank_snapshot == 3
    assert publication.editorial_decision_id == decision_id
    assert publication.editorial_decision_snapshot == EditorialDecisionType.ADOPT
    assert publication.public_url == "https://video.example/p/123"
    factory = get_async_sessionmaker()
    async with factory() as session:
        async with session.begin():
            session.add(
                EditorialDecisionRecord(
                    event_id=event_id,
                    candidate_id=candidate_id,
                    decision=EditorialDecisionType.DROP,
                    risk_level_snapshot=EditorialRiskLevel.R4,
                    effective_traffic_total_snapshot=10.0,
                    actor=ACTOR,
                    reason="Later decision must not rewrite publication provenance",
                )
            )
    detail = await PerformanceFeedbackQueryService().get_publication(publication.id)
    frozen = detail["publication"]
    assert isinstance(frozen, PublicationRecord)
    assert frozen.candidate_rank_snapshot == 3
    assert frozen.editorial_decision_snapshot == EditorialDecisionType.ADOPT
    assert frozen.draft_version_snapshot == 1


@pytest.mark.asyncio
async def test_workflow_requires_current_adopt() -> None:
    event_id, draft_id, candidate_id, _decision_id = await _workflow_fixture()
    factory = get_async_sessionmaker()
    async with factory() as session:
        async with session.begin():
            session.add(
                EditorialDecisionRecord(
                    event_id=event_id,
                    candidate_id=candidate_id,
                    decision=EditorialDecisionType.WATCH,
                    risk_level_snapshot=EditorialRiskLevel.R2,
                    effective_traffic_total_snapshot=50.0,
                    actor=ACTOR,
                    reason="Watch after adopt",
                )
            )
    with pytest.raises(EditorialAdoptionRequiredError):
        await PublicationService().create(
            event_id=event_id,
            publication_mode=PublicationMode.WORKFLOW,
            platform_key="video.example",
            public_url="https://video.example/p/not-adopted",
            published_at=BASE_TIME + timedelta(hours=1),
            actor=ACTOR,
            draft_id=draft_id,
        )


@pytest.mark.asyncio
async def test_manual_backfill_and_merged_event_boundaries() -> None:
    publication = await _backfill_publication("history")
    assert publication.draft_id is None
    assert publication.candidate_id is None
    assert publication.editorial_decision_id is None
    assert publication.backfill_reason
    target = await _simple_event("Canonical target")
    source = await _simple_event("Merged source")
    factory = get_async_sessionmaker()
    async with factory() as session:
        async with session.begin():
            row = await session.get(EventRecord, source.id)
            assert row is not None
            row.merged_into_event_id = target.id
    with pytest.raises(PublicationEventMergedError) as exc_info:
        await PublicationService().create(
            event_id=source.id,
            publication_mode=PublicationMode.MANUAL_BACKFILL,
            platform_key="test.platform",
            public_url="https://example.com/merged",
            published_at=BASE_TIME,
            actor=ACTOR,
            backfill_reason="Historical record",
        )
    assert exc_info.value.details == {"target_event_id": str(target.id)}


@pytest.mark.asyncio
async def test_publication_concurrent_identity_is_database_safe() -> None:
    event_record = await _simple_event("Concurrent Publication")

    async def create_once() -> tuple[UUID, bool]:
        outcome = await PublicationService().create(
            event_id=event_record.id,
            publication_mode=PublicationMode.MANUAL_BACKFILL,
            platform_key="test.platform",
            public_url="https://example.com/concurrent",
            external_post_id="concurrent-post",
            published_at=BASE_TIME,
            actor=ACTOR,
            backfill_reason="Historical record",
        )
        return outcome.publication.id, outcome.reused

    first, second = await asyncio.gather(create_once(), create_once())
    assert first[0] == second[0]
    assert {first[1], second[1]} == {False, True}
    factory = get_async_sessionmaker()
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(PublicationRecord))
    assert count == 1


@pytest.mark.asyncio
async def test_performance_null_zero_signed_and_same_snapshot_idempotency() -> None:
    publication = await _backfill_publication("metrics")
    observed = BASE_TIME + timedelta(hours=1)

    async def submit() -> tuple[UUID, bool]:
        outcome = await PublicationPerformanceService().add_manual_snapshot(
            publication_id=publication.id,
            observed_at=observed,
            horizon=PerformanceHorizon.H1,
            metrics=PerformanceMetrics(
                views=0,
                completion_rate=1.0,
                likes=0,
                follower_delta=-2,
            ),
            actor=ACTOR,
        )
        return outcome.snapshot.id, outcome.reused

    first, second = await asyncio.gather(submit(), submit())
    assert first[0] == second[0]
    factory = get_async_sessionmaker()
    async with factory() as session:
        snapshot = await session.get(PublicationPerformanceSnapshotRecord, first[0])
        assert snapshot is not None
        assert snapshot.views == 0
        assert snapshot.completion_rate == 1.0
        assert snapshot.comments is None
        assert snapshot.favorites is None
        assert snapshot.follower_delta == -2
        count = await session.scalar(
            select(func.count()).select_from(PublicationPerformanceSnapshotRecord)
        )
    assert count == 1
    with pytest.raises(PerformanceValidationError):
        PerformanceMetrics(views=-1).validate()
    with pytest.raises(PerformanceValidationError):
        PerformanceMetrics(completion_rate=1.01).validate()
    with pytest.raises(PerformanceValidationError):
        PerformanceMetrics().validate()


@pytest.mark.asyncio
async def test_performance_correction_is_append_only_and_effective() -> None:
    publication = await _backfill_publication("correction")
    service = PublicationPerformanceService()
    observed = BASE_TIME + timedelta(hours=24)
    original = await service.add_manual_snapshot(
        publication_id=publication.id,
        observed_at=observed,
        horizon=PerformanceHorizon.H24,
        metrics=PerformanceMetrics(
            views=100, likes=10, comments=1, shares=1, favorites=1
        ),
        actor=ACTOR,
    )
    corrected = await service.add_manual_snapshot(
        publication_id=publication.id,
        observed_at=observed,
        horizon=PerformanceHorizon.H24,
        metrics=PerformanceMetrics(
            views=120, likes=12, comments=1, shares=1, favorites=1
        ),
        actor=ACTOR,
        supersedes_snapshot_id=original.snapshot.id,
        correction_reason="Dashboard value was refreshed.",
    )
    timeline = await PerformanceFeedbackQueryService().performance_timeline(publication.id)
    assert len(timeline) == 2
    assert timeline[0]["is_effective"] is False
    assert timeline[1]["is_effective"] is True
    assert corrected.snapshot.supersedes_snapshot_id == original.snapshot.id


@pytest.mark.asyncio
async def test_csv_preview_apply_blank_null_percent_and_file_idempotency() -> None:
    publication = await _backfill_publication("csv")
    csv_text = (
        "publication_id,platform_key,external_post_id,public_url,observed_at,horizon,"
        "views,completion_rate_percent,average_watch_seconds,likes,comments,shares,"
        "favorites,follower_delta\n"
        f"{publication.id},test.platform,post-csv,https://example.com/posts/csv,"
        "2026-08-10T06:00:00+00:00,h1,100,68.3,,10,2,1,,\n"
    )
    service = PerformanceImportService()
    preview = await service.preview(csv_text=csv_text)
    assert preview.valid_rows == 1
    assert preview.invalid_rows == 0
    metrics = preview.normalized_rows[0]["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["completion_rate"] == 0.683
    assert metrics["average_watch_seconds"] is None
    assert metrics["favorites"] is None
    applied = await service.apply(
        csv_text=csv_text,
        file_name="performance.csv",
        actor=ACTOR,
        confirmation=True,
    )
    repeated = await service.apply(
        csv_text=csv_text,
        file_name="performance.csv",
        actor=ACTOR,
        confirmation=True,
    )
    assert applied.run.inserted_count == 1
    assert repeated.reused is True
    assert repeated.run.id == applied.run.id


@pytest.mark.asyncio
async def test_csv_invalid_and_concurrent_apply() -> None:
    unknown_id = "11111111-1111-1111-1111-111111111111"
    header = (
        "publication_id,platform_key,external_post_id,public_url,observed_at,horizon,"
        "views,completion_rate_percent,average_watch_seconds,likes,comments,shares,"
        "favorites,follower_delta\n"
    )
    service = PerformanceImportService()
    preview = await service.preview(
        csv_text=header
        + f"{unknown_id},,,,2026-08-10T06:00:00+00:00,h1,10,,,,,,,\n"
    )
    assert preview.invalid_rows == 1
    assert preview.errors[0].code == "PUBLICATION_NOT_FOUND"
    preview = await service.preview(
        csv_text=header
        + f"{unknown_id},,,,2026-08-10T06:00:00,h1,10,,,,,,,\n"
    )
    assert any(error.code == "TIMEZONE_REQUIRED" for error in preview.errors)
    publication = await _backfill_publication("csv-concurrent")
    csv_text = (
        header
        + f"{publication.id},test.platform,post-csv-concurrent,"
        "https://example.com/posts/csv-concurrent,2026-08-10T07:00:00+00:00,h1,"
        "200,50,,20,4,2,,\n"
    )

    async def apply_once() -> UUID:
        outcome = await PerformanceImportService().apply(
            csv_text=csv_text,
            file_name="same.csv",
            actor=ACTOR,
            confirmation=True,
        )
        return outcome.run.id

    first, second = await asyncio.gather(apply_once(), apply_once())
    assert first == second


@pytest.mark.asyncio
async def test_publication_list_query_count_is_bounded() -> None:
    for index in range(5):
        publication = await _backfill_publication(f"bounded-{index}")
        await PublicationPerformanceService().add_manual_snapshot(
            publication_id=publication.id,
            observed_at=BASE_TIME + timedelta(hours=index + 1),
            horizon=PerformanceHorizon.CUSTOM,
            metrics=PerformanceMetrics(views=index * 10),
            actor=ACTOR,
        )
    statements: list[str] = []
    engine = get_async_engine().sync_engine

    def before_cursor_execute(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = await PerformanceFeedbackQueryService().list_publications(page_size=20)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert result.total == 5
    assert len(result.items) == 5
    assert len(statements) <= 2


def test_url_and_metric_validation() -> None:
    assert (
        normalize_public_url("HTTPS://Example.COM/post/1#fragment")
        == "https://example.com/post/1"
    )
    for unsafe in (
        "custom-scheme://example.com/post",
        "ftp://example.com/post",
        "https://user:secret@example.com/post",
    ):
        with pytest.raises(PublicationValidationError):
            normalize_public_url(unsafe)
