from sqlalchemy import func, select

from packages.clustering.repositories import MatchDecisionRepository
from packages.database.models import (
    MatchDecisionType,
    MatchPrimaryMethod,
    SignalMatchDecisionRecord,
)
from tests.m3c_helpers import create_m3c_signal, create_source


async def test_match_decisions_are_isolated_by_algorithm_version_and_old_rows_are_retained(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="version-a",
        title="算法版本隔离",
        text="旧判断必须保留",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="version-b",
        title="算法版本隔离",
        text="新算法不得覆盖旧判断",
    )

    async with db_session.begin():
        repository = MatchDecisionRepository(db_session)
        v1, v1_created = await repository.insert_idempotently(
            left_signal_id=first.id,
            right_signal_id=second.id,
            decision=MatchDecisionType.AMBIGUOUS,
            primary_method=MatchPrimaryMethod.COMBINED,
            score=0.70,
            components={"baseline": True},
            algorithm_version="event-match-v1",
        )
        v2, v2_created = await repository.insert_idempotently(
            left_signal_id=first.id,
            right_signal_id=second.id,
            decision=MatchDecisionType.SAME_EVENT,
            primary_method=MatchPrimaryMethod.COMBINED,
            score=0.92,
            components={"candidate_policy": True},
            algorithm_version="event-match-v2",
        )
        repeated_v1, repeated_created = await repository.insert_idempotently(
            left_signal_id=first.id,
            right_signal_id=second.id,
            decision=MatchDecisionType.DISTINCT,
            primary_method=MatchPrimaryMethod.COMBINED,
            score=0.10,
            components={"must_not_overwrite": True},
            algorithm_version="event-match-v1",
        )

    assert v1_created is True
    assert v2_created is True
    assert repeated_created is False
    assert repeated_v1.id == v1.id
    assert v1.id != v2.id
    assert v1.algorithm_version == "event-match-v1"
    assert v1.decision is MatchDecisionType.AMBIGUOUS
    assert v1.score == 0.70
    assert v2.algorithm_version == "event-match-v2"
    assert v2.decision is MatchDecisionType.SAME_EVENT
    assert int(
        await db_session.scalar(
            select(func.count()).select_from(SignalMatchDecisionRecord).where(
                SignalMatchDecisionRecord.left_signal_id.in_([first.id, second.id]),
                SignalMatchDecisionRecord.right_signal_id.in_([first.id, second.id]),
            )
        )
        or 0
    ) == 2
