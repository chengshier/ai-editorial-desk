from datetime import UTC, datetime, timedelta

import pytest

from packages.clustering.repositories import (
    MatchDecisionRepository,
    MatchOverrideRepository,
    canonical_signal_pair,
)
from packages.clustering.services import SignalMatchService
from packages.database.models import (
    MatchDecisionType,
    MatchOverrideDecision,
    MatchPrimaryMethod,
    RawSignalRecord,
)
from tests.m3c_helpers import add_test_embeddings, create_m3c_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_exact_duplicate_uses_canonical_url_without_deleting_raw_signals(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="exact-url-a",
        title="标题甲",
        text="正文甲",
        url="https://example.com/shared?utm_source=test",
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="exact-url-b",
        title="完全不同标题",
        text="完全不同正文",
        url="https://example.com/shared",
    )
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.EXACT_DUPLICATE
    assert decision.primary_method is MatchPrimaryMethod.CANONICAL_URL
    assert await db_session.get(RawSignalRecord, left.id) is not None
    assert await db_session.get(RawSignalRecord, right.id) is not None


@pytest.mark.usefixtures("clean_database")
async def test_exact_duplicate_uses_nonempty_content_hash(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="hash-a",
        title="相同标题",
        text="相同正文",
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="hash-b",
        title="相同标题",
        text="相同正文",
    )
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.EXACT_DUPLICATE
    assert decision.primary_method is MatchPrimaryMethod.CONTENT_HASH


@pytest.mark.usefixtures("clean_database")
async def test_exact_duplicate_uses_same_platform_external_id_across_connector_identity(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="stable-external",
        title="来源一",
        text="正文一",
        connector_type="rss",
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="stable-external",
        title="来源二",
        text="正文二",
        connector_type="manual",
    )
    assert left.id != right.id
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.EXACT_DUPLICATE
    assert decision.primary_method is MatchPrimaryMethod.EXTERNAL_ID


@pytest.mark.usefixtures("clean_database")
async def test_empty_text_hash_is_not_used_as_exact_duplicate(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session, source, external_id="empty-a", title=" ", text=""
    )
    right = await create_m3c_signal(
        db_session, source, external_id="empty-b", title=None, text=None
    )
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    assert all(item.candidate_signal_id != right.id for item in preview.decisions)


@pytest.mark.usefixtures("clean_database")
async def test_near_duplicate_uses_simhash_without_embedding(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="near-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="near-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营。最新",
    )
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.NEAR_DUPLICATE
    assert decision.primary_method is MatchPrimaryMethod.SIMHASH
    assert 0 <= int(decision.components["simhash_distance"]) <= 6


@pytest.mark.usefixtures("clean_database")
async def test_embedding_and_simhash_combined_can_make_same_event_decision(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="same-event-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="same-event-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营消息",
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-embedding-v1",
        vectors={left.id: (1.0, 0.0), right.id: (0.99, 0.05)},
    )
    preview = await SignalMatchService(db_session).preview(
        signal_id=left.id,
        embedding_version="m3c-embedding-v1",
    )
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.SAME_EVENT
    assert decision.primary_method is MatchPrimaryMethod.COMBINED
    assert float(decision.components["embedding_similarity"]) > 0.9


@pytest.mark.usefixtures("clean_database")
async def test_middle_embedding_similarity_remains_ambiguous(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session, source, external_id="amb-a", title="地铁暴雨停运", text="乘客等待恢复"
    )
    right = await create_m3c_signal(
        db_session, source, external_id="amb-b", title="暴雨交通消息", text="道路积水严重"
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-embedding-v1",
        vectors={left.id: (1.0, 0.0), right.id: (0.75, 0.66)},
    )
    preview = await SignalMatchService(db_session).preview(
        signal_id=left.id,
        embedding_version="m3c-embedding-v1",
    )
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.AMBIGUOUS


@pytest.mark.usefixtures("clean_database")
async def test_low_embedding_and_unrelated_text_is_distinct(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session, source, external_id="distinct-a", title="地铁暴雨停运", text="乘客等待恢复"
    )
    right = await create_m3c_signal(
        db_session, source, external_id="distinct-b", title="球队夺冠", text="球迷庆祝冠军"
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-embedding-v1",
        vectors={left.id: (1.0, 0.0), right.id: (-1.0, 0.0)},
    )
    preview = await SignalMatchService(db_session).preview(
        signal_id=left.id,
        embedding_version="m3c-embedding-v1",
    )
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.DISTINCT


@pytest.mark.usefixtures("clean_database")
async def test_time_penalty_keeps_high_semantic_candidate_ambiguous(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    base_time = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
    left = await create_m3c_signal(
        db_session,
        source,
        external_id="time-a",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营",
        published_at=base_time,
    )
    right = await create_m3c_signal(
        db_session,
        source,
        external_id="time-b",
        title="暴雨导致地铁临时停运",
        text="官方称三号线将在晚间恢复运营消息",
        published_at=base_time + timedelta(hours=70),
    )
    await add_test_embeddings(
        db_session,
        embedding_version="m3c-embedding-v1",
        vectors={left.id: (1.0, 0.0), right.id: (0.99, 0.05)},
    )
    preview = await SignalMatchService(db_session).preview(
        signal_id=left.id,
        embedding_version="m3c-embedding-v1",
    )
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.AMBIGUOUS
    assert float(decision.components["time_component"]) < 0.05


@pytest.mark.usefixtures("clean_database")
async def test_pair_canonicalization_and_decision_idempotency(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(db_session, source, external_id="pair-a", title="甲", text="内容甲")
    right = await create_m3c_signal(db_session, source, external_id="pair-b", title="乙", text="内容乙")
    canonical_left, canonical_right = canonical_signal_pair(right.id, left.id)
    assert canonical_left.int < canonical_right.int
    repository = MatchDecisionRepository(db_session)
    async with db_session.begin():
        first, first_created = await repository.insert_idempotently(
            left_signal_id=left.id,
            right_signal_id=right.id,
            decision=MatchDecisionType.AMBIGUOUS,
            primary_method=MatchPrimaryMethod.COMBINED,
            score=0.6,
            components={"test": True},
            algorithm_version="event-match-v1",
        )
        second, second_created = await repository.insert_idempotently(
            left_signal_id=right.id,
            right_signal_id=left.id,
            decision=MatchDecisionType.DISTINCT,
            primary_method=MatchPrimaryMethod.COMBINED,
            score=0.1,
            components={"test": False},
            algorithm_version="event-match-v1",
        )
    assert first.id == second.id
    assert first_created is True
    assert second_created is False


@pytest.mark.usefixtures("clean_database")
async def test_human_distinct_override_wins_over_exact_rule(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    left = await create_m3c_signal(
        db_session, source, external_id="override-a", title="相同", text="完全相同内容"
    )
    right = await create_m3c_signal(
        db_session, source, external_id="override-b", title="相同", text="完全相同内容"
    )
    async with db_session.begin():
        await MatchOverrideRepository(db_session).upsert(
            left_signal_id=left.id,
            right_signal_id=right.id,
            decision=MatchOverrideDecision.DISTINCT,
            reason="人工确认是不同事件",
            actor="editor",
        )
    preview = await SignalMatchService(db_session).preview(signal_id=left.id)
    decision = next(item for item in preview.decisions if item.candidate_signal_id == right.id)
    assert decision.decision is MatchDecisionType.DISTINCT
    assert decision.primary_method is MatchPrimaryMethod.HUMAN
    assert decision.components["human_override"] is True
