from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    MatchDecisionType,
    MatchOverrideDecision,
    MatchPrimaryMethod,
    RawSignalRecord,
    SignalEventSuppressionRecord,
    SignalFingerprintRecord,
    SignalMatchDecisionRecord,
    SignalMatchOverrideRecord,
)


def canonical_signal_pair(left_signal_id: UUID, right_signal_id: UUID) -> tuple[UUID, UUID]:
    if left_signal_id == right_signal_id:
        raise ValueError("signal pair must contain two different signals")
    ordered = sorted((left_signal_id, right_signal_id), key=lambda value: value.int)
    return ordered[0], ordered[1]


class FingerprintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, signal_id: UUID, fingerprint_version: str
    ) -> SignalFingerprintRecord | None:
        statement = select(SignalFingerprintRecord).where(
            SignalFingerprintRecord.signal_id == signal_id,
            SignalFingerprintRecord.fingerprint_version == fingerprint_version,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def insert_idempotently(
        self,
        *,
        signal_id: UUID,
        fingerprint_version: str,
        input_hash: str,
        simhash: str,
        token_count: int,
    ) -> tuple[SignalFingerprintRecord, bool]:
        statement = (
            insert(SignalFingerprintRecord)
            .values(
                signal_id=signal_id,
                fingerprint_version=fingerprint_version,
                input_hash=input_hash,
                simhash=simhash,
                token_count=token_count,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SignalFingerprintRecord.signal_id,
                    SignalFingerprintRecord.fingerprint_version,
                ]
            )
            .returning(SignalFingerprintRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(SignalFingerprintRecord, created_id)
            if created is None:
                raise RuntimeError("SignalFingerprint 写入成功后未找到记录")
            return created, True
        existing = await self.get(signal_id, fingerprint_version)
        if existing is None:
            raise RuntimeError("SignalFingerprint 幂等冲突后未找到既有记录")
        return existing, False


class MatchDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        left_signal_id: UUID,
        right_signal_id: UUID,
        algorithm_version: str,
    ) -> SignalMatchDecisionRecord | None:
        left_id, right_id = canonical_signal_pair(left_signal_id, right_signal_id)
        statement = select(SignalMatchDecisionRecord).where(
            SignalMatchDecisionRecord.left_signal_id == left_id,
            SignalMatchDecisionRecord.right_signal_id == right_id,
            SignalMatchDecisionRecord.algorithm_version == algorithm_version,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def insert_idempotently(
        self,
        *,
        left_signal_id: UUID,
        right_signal_id: UUID,
        decision: MatchDecisionType,
        primary_method: MatchPrimaryMethod,
        score: float,
        components: dict[str, object],
        algorithm_version: str,
    ) -> tuple[SignalMatchDecisionRecord, bool]:
        left_id, right_id = canonical_signal_pair(left_signal_id, right_signal_id)
        statement = (
            insert(SignalMatchDecisionRecord)
            .values(
                left_signal_id=left_id,
                right_signal_id=right_id,
                decision=decision,
                primary_method=primary_method,
                score=score,
                components=components,
                algorithm_version=algorithm_version,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SignalMatchDecisionRecord.left_signal_id,
                    SignalMatchDecisionRecord.right_signal_id,
                    SignalMatchDecisionRecord.algorithm_version,
                ]
            )
            .returning(SignalMatchDecisionRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(SignalMatchDecisionRecord, created_id)
            if created is None:
                raise RuntimeError("MatchDecision 写入成功后未找到记录")
            return created, True
        existing = await self.get(left_id, right_id, algorithm_version)
        if existing is None:
            raise RuntimeError("MatchDecision 幂等冲突后未找到既有记录")
        return existing, False


class MatchOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, left_signal_id: UUID, right_signal_id: UUID
    ) -> SignalMatchOverrideRecord | None:
        left_id, right_id = canonical_signal_pair(left_signal_id, right_signal_id)
        statement = select(SignalMatchOverrideRecord).where(
            SignalMatchOverrideRecord.left_signal_id == left_id,
            SignalMatchOverrideRecord.right_signal_id == right_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        left_signal_id: UUID,
        right_signal_id: UUID,
        decision: MatchOverrideDecision,
        reason: str,
        actor: str,
    ) -> SignalMatchOverrideRecord:
        left_id, right_id = canonical_signal_pair(left_signal_id, right_signal_id)
        statement = (
            insert(SignalMatchOverrideRecord)
            .values(
                left_signal_id=left_id,
                right_signal_id=right_id,
                decision=decision,
                reason=reason,
                actor=actor,
            )
            .on_conflict_do_update(
                index_elements=[
                    SignalMatchOverrideRecord.left_signal_id,
                    SignalMatchOverrideRecord.right_signal_id,
                ],
                set_={
                    "decision": decision,
                    "reason": reason,
                    "actor": actor,
                    "updated_at": func.now(),
                },
            )
            .returning(SignalMatchOverrideRecord.id)
        )
        override_id = (await self.session.execute(statement)).scalar_one()
        result = await self.session.get(SignalMatchOverrideRecord, override_id)
        if result is None:
            raise RuntimeError("MatchOverride upsert 后未找到记录")
        return result


class SignalEventSuppressionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_active(self, signal_id: UUID, event_id: UUID) -> bool:
        statement = select(SignalEventSuppressionRecord.id).where(
            SignalEventSuppressionRecord.signal_id == signal_id,
            SignalEventSuppressionRecord.event_id == event_id,
            SignalEventSuppressionRecord.active.is_(True),
        )
        return (await self.session.scalar(statement)) is not None

    async def upsert_active(
        self,
        *,
        signal_id: UUID,
        event_id: UUID,
        reason: str,
        actor: str,
    ) -> SignalEventSuppressionRecord:
        statement = (
            insert(SignalEventSuppressionRecord)
            .values(
                signal_id=signal_id,
                event_id=event_id,
                reason=reason,
                actor=actor,
                active=True,
            )
            .on_conflict_do_update(
                index_elements=[
                    SignalEventSuppressionRecord.signal_id,
                    SignalEventSuppressionRecord.event_id,
                ],
                set_={
                    "reason": reason,
                    "actor": actor,
                    "active": True,
                    "updated_at": func.now(),
                },
            )
            .returning(SignalEventSuppressionRecord.id)
        )
        suppression_id = (await self.session.execute(statement)).scalar_one()
        result = await self.session.get(SignalEventSuppressionRecord, suppression_id)
        if result is None:
            raise RuntimeError("SignalEventSuppression upsert 后未找到记录")
        return result

    async def deactivate_for_event(self, event_id: UUID) -> None:
        await self.session.execute(
            update(SignalEventSuppressionRecord)
            .where(
                SignalEventSuppressionRecord.event_id == event_id,
                SignalEventSuppressionRecord.active.is_(True),
            )
            .values(active=False, updated_at=func.now())
        )

    async def deactivate(self, signal_id: UUID, event_id: UUID) -> None:
        await self.session.execute(
            update(SignalEventSuppressionRecord)
            .where(
                SignalEventSuppressionRecord.signal_id == signal_id,
                SignalEventSuppressionRecord.event_id == event_id,
                SignalEventSuppressionRecord.active.is_(True),
            )
            .values(active=False, updated_at=func.now())
        )


class ClusteringQueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_signal_for_update(self, signal_id: UUID) -> RawSignalRecord | None:
        statement = (
            select(RawSignalRecord)
            .where(RawSignalRecord.id == signal_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def exact_candidates(
        self, target: RawSignalRecord, *, limit: int
    ) -> list[RawSignalRecord]:
        nonempty_text = or_(
            func.length(func.trim(func.coalesce(RawSignalRecord.title, ""))) > 0,
            func.length(func.trim(func.coalesce(RawSignalRecord.text, ""))) > 0,
        )
        rules = [RawSignalRecord.canonical_url == target.canonical_url]
        if (target.title or "").strip() or (target.text or "").strip():
            rules.append(and_(RawSignalRecord.content_hash == target.content_hash, nonempty_text))
        if target.external_id and target.external_id.strip():
            rules.append(
                and_(
                    RawSignalRecord.platform == target.platform,
                    RawSignalRecord.external_id == target.external_id,
                )
            )
        statement = (
            select(RawSignalRecord)
            .where(RawSignalRecord.id != target.id, or_(*rules))
            .order_by(RawSignalRecord.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def bounded_time_candidates(
        self,
        *,
        target: RawSignalRecord,
        max_time_gap: timedelta,
        limit: int,
    ) -> list[RawSignalRecord]:
        effective_time = func.coalesce(
            RawSignalRecord.published_at, RawSignalRecord.collected_at
        )
        target_time = target.published_at or target.collected_at
        start = target_time - max_time_gap
        end = target_time + max_time_gap
        distance_seconds = func.abs(func.extract("epoch", effective_time - target_time))
        statement = (
            select(RawSignalRecord)
            .where(
                RawSignalRecord.id != target.id,
                effective_time >= start,
                effective_time <= end,
            )
            .order_by(distance_seconds.asc(), RawSignalRecord.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def active_memberships(self, signal_id: UUID) -> list[EventSignalRecord]:
        statement = (
            select(EventSignalRecord)
            .join(EventRecord, EventRecord.id == EventSignalRecord.event_id)
            .where(
                EventSignalRecord.signal_id == signal_id,
                EventRecord.merged_into_event_id.is_(None),
            )
            .order_by(EventSignalRecord.event_id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def human_active_memberships(self, signal_id: UUID) -> list[EventSignalRecord]:
        statement = (
            select(EventSignalRecord)
            .join(EventRecord, EventRecord.id == EventSignalRecord.event_id)
            .where(
                EventSignalRecord.signal_id == signal_id,
                EventSignalRecord.attached_by == EventSignalAttachedBy.HUMAN,
                EventRecord.merged_into_event_id.is_(None),
            )
            .order_by(EventSignalRecord.event_id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def event_signal_ids(self, event_id: UUID) -> list[UUID]:
        statement = (
            select(EventSignalRecord.signal_id)
            .where(EventSignalRecord.event_id == event_id)
            .order_by(EventSignalRecord.signal_id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def lock_events(self, event_ids: list[UUID]) -> list[EventRecord]:
        if not event_ids:
            return []
        ordered = sorted(set(event_ids), key=lambda value: value.int)
        statement = (
            select(EventRecord)
            .where(EventRecord.id.in_(ordered))
            .order_by(EventRecord.id.asc())
            .with_for_update()
        )
        return list((await self.session.scalars(statement)).all())
