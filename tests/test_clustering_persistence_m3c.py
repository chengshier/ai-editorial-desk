import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.clustering.fingerprints import FingerprintInputBuilder
from packages.clustering.repositories import FingerprintRepository, MatchDecisionRepository
from packages.database.models import (
    MatchDecisionType,
    MatchPrimaryMethod,
    SignalFingerprintRecord,
    SignalMatchDecisionRecord,
)
from packages.database.session import get_async_sessionmaker
from tests.m3c_helpers import create_m3c_signal, create_source


@pytest.mark.usefixtures("clean_database")
async def test_fingerprint_insert_is_idempotent_and_cascades_with_raw_signal(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    signal = await create_m3c_signal(
        db_session,
        source,
        external_id="fingerprint-persist",
        title="地铁暴雨停运",
        text="官方公布恢复时间",
    )
    fingerprint = FingerprintInputBuilder().fingerprint(signal)
    assert fingerprint is not None
    repository = FingerprintRepository(db_session)
    async with db_session.begin():
        first, first_created = await repository.insert_idempotently(
            signal_id=signal.id,
            fingerprint_version=fingerprint.fingerprint_version,
            input_hash=fingerprint.input_hash,
            simhash=fingerprint.simhash,
            token_count=fingerprint.token_count,
        )
        second, second_created = await repository.insert_idempotently(
            signal_id=signal.id,
            fingerprint_version=fingerprint.fingerprint_version,
            input_hash=fingerprint.input_hash,
            simhash=fingerprint.simhash,
            token_count=fingerprint.token_count,
        )
    fingerprint_id = first.id
    assert first.id == second.id
    assert first_created is True
    assert second_created is False

    async with db_session.begin():
        await db_session.delete(signal)
    assert await db_session.get(SignalFingerprintRecord, fingerprint_id) is None


@pytest.mark.usefixtures("clean_database")
async def test_fingerprint_foreign_key_rejects_missing_raw_signal(db_session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrityError):
        async with db_session.begin():
            db_session.add(
                SignalFingerprintRecord(
                    signal_id=uuid4(),
                    fingerprint_version="signal-fingerprint-v1",
                    input_hash="a" * 64,
                    simhash="0f" * 8,
                    token_count=1,
                )
            )
            await db_session.flush()


@pytest.mark.usefixtures("clean_database")
async def test_database_rejects_noncanonical_match_pair(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session, source, external_id="canonical-db-a", title="A", text="正文 A"
    )
    second = await create_m3c_signal(
        db_session, source, external_id="canonical-db-b", title="B", text="正文 B"
    )
    left, right = sorted((first.id, second.id), key=lambda value: value.int)
    with pytest.raises(IntegrityError):
        async with db_session.begin():
            db_session.add(
                SignalMatchDecisionRecord(
                    left_signal_id=right,
                    right_signal_id=left,
                    decision=MatchDecisionType.AMBIGUOUS,
                    primary_method=MatchPrimaryMethod.COMBINED,
                    score=0.5,
                    components={},
                    algorithm_version="event-match-v1",
                )
            )
            await db_session.flush()


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_reversed_pair_decision_produces_one_row(db_session) -> None:  # type: ignore[no-untyped-def]
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session, source, external_id="decision-concurrent-a", title="A", text="正文 A"
    )
    second = await create_m3c_signal(
        db_session, source, external_id="decision-concurrent-b", title="B", text="正文 B"
    )
    first_id = first.id
    second_id = second.id

    async def insert_once(left_id, right_id):  # type: ignore[no-untyped-def]
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            async with session.begin():
                record, created = await MatchDecisionRepository(session).insert_idempotently(
                    left_signal_id=left_id,
                    right_signal_id=right_id,
                    decision=MatchDecisionType.AMBIGUOUS,
                    primary_method=MatchPrimaryMethod.COMBINED,
                    score=0.6,
                    components={"concurrent": True},
                    algorithm_version="event-match-v1",
                )
                return record.id, created

    left_result, right_result = await asyncio.gather(
        insert_once(first_id, second_id),
        insert_once(second_id, first_id),
    )
    assert left_result[0] == right_result[0]
    assert sum((left_result[1], right_result[1])) == 1
    assert int(
        await db_session.scalar(select(func.count()).select_from(SignalMatchDecisionRecord)) or 0
    ) == 1
