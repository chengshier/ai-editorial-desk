from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    EventUnknownRecord,
    EventUnknownSourceType,
    EventUnknownStatus,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    EvidenceClaimType,
    EvidenceCreatedByType,
    EvidenceExtractionRunRecord,
    EvidenceSourceRole,
    EvidenceVerificationState,
)


class EvidenceExtractionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, run: EvidenceExtractionRunRecord) -> None:
        self.session.add(run)

    async def get(self, run_id: UUID) -> EvidenceExtractionRunRecord | None:
        return await self.session.get(EvidenceExtractionRunRecord, run_id)

    async def get_for_update(self, run_id: UUID) -> EvidenceExtractionRunRecord | None:
        statement = (
            select(EvidenceExtractionRunRecord)
            .where(EvidenceExtractionRunRecord.id == run_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()


class EvidenceClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, claim_id: UUID) -> EvidenceClaimRecord | None:
        return await self.session.get(EvidenceClaimRecord, claim_id)

    async def get_for_update(self, claim_id: UUID) -> EvidenceClaimRecord | None:
        statement = (
            select(EvidenceClaimRecord)
            .where(EvidenceClaimRecord.id == claim_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_by_fingerprint(
        self, event_id: UUID, fingerprint: str
    ) -> EvidenceClaimRecord | None:
        statement = select(EvidenceClaimRecord).where(
            EvidenceClaimRecord.event_id == event_id,
            EvidenceClaimRecord.claim_fingerprint == fingerprint,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_for_event(self, event_id: UUID) -> Sequence[EvidenceClaimRecord]:
        statement = (
            select(EvidenceClaimRecord)
            .where(EvidenceClaimRecord.event_id == event_id)
            .order_by(EvidenceClaimRecord.created_at.asc(), EvidenceClaimRecord.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def insert_if_absent(
        self,
        *,
        event_id: UUID,
        claim_text: str,
        claim_type: EvidenceClaimType,
        verification_state: EvidenceVerificationState,
        extraction_confidence: float | None,
        claim_fingerprint: str,
        extraction_version: str,
        extraction_run_id: UUID | None,
        ai_invocation_id: UUID | None,
        created_by_type: EvidenceCreatedByType,
        created_by_actor: str | None,
        editor_note: str | None,
    ) -> tuple[EvidenceClaimRecord, bool]:
        statement = (
            insert(EvidenceClaimRecord)
            .values(
                event_id=event_id,
                claim_text=claim_text,
                claim_type=claim_type,
                verification_state=verification_state,
                extraction_confidence=extraction_confidence,
                claim_fingerprint=claim_fingerprint,
                extraction_version=extraction_version,
                extraction_run_id=extraction_run_id,
                ai_invocation_id=ai_invocation_id,
                created_by_type=created_by_type,
                created_by_actor=created_by_actor,
                editor_note=editor_note,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    EvidenceClaimRecord.event_id,
                    EvidenceClaimRecord.claim_fingerprint,
                ]
            )
            .returning(EvidenceClaimRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EvidenceClaimRecord, created_id)
            if created is None:
                raise RuntimeError("EvidenceClaim 写入成功后未找到记录")
            return created, True
        existing = await self.get_by_fingerprint(event_id, claim_fingerprint)
        if existing is None:
            raise RuntimeError("EvidenceClaim 幂等冲突后未找到既有记录")
        return existing, False


class EvidenceClaimSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, claim_id: UUID, signal_id: UUID
    ) -> EvidenceClaimSourceRecord | None:
        statement = select(EvidenceClaimSourceRecord).where(
            EvidenceClaimSourceRecord.claim_id == claim_id,
            EvidenceClaimSourceRecord.signal_id == signal_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_for_claim(self, claim_id: UUID) -> Sequence[EvidenceClaimSourceRecord]:
        statement = (
            select(EvidenceClaimSourceRecord)
            .where(EvidenceClaimSourceRecord.claim_id == claim_id)
            .order_by(
                EvidenceClaimSourceRecord.role.asc(),
                EvidenceClaimSourceRecord.created_at.asc(),
                EvidenceClaimSourceRecord.signal_id.asc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def attach_if_absent(
        self,
        *,
        claim_id: UUID,
        signal_id: UUID,
        role: EvidenceSourceRole,
    ) -> tuple[EvidenceClaimSourceRecord, bool]:
        statement = (
            insert(EvidenceClaimSourceRecord)
            .values(claim_id=claim_id, signal_id=signal_id, role=role)
            .on_conflict_do_nothing(
                index_elements=[
                    EvidenceClaimSourceRecord.claim_id,
                    EvidenceClaimSourceRecord.signal_id,
                ]
            )
            .returning(EvidenceClaimSourceRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EvidenceClaimSourceRecord, created_id)
            if created is None:
                raise RuntimeError("Evidence source 写入成功后未找到记录")
            return created, True
        existing = await self.get(claim_id, signal_id)
        if existing is None:
            raise RuntimeError("Evidence source 幂等冲突后未找到既有记录")
        return existing, False

    async def delete(self, source: EvidenceClaimSourceRecord) -> None:
        await self.session.delete(source)


class EventUnknownRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, unknown_id: UUID) -> EventUnknownRecord | None:
        return await self.session.get(EventUnknownRecord, unknown_id)

    async def get_for_update(self, unknown_id: UUID) -> EventUnknownRecord | None:
        statement = (
            select(EventUnknownRecord)
            .where(EventUnknownRecord.id == unknown_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_by_fingerprint(
        self, event_id: UUID, fingerprint: str
    ) -> EventUnknownRecord | None:
        statement = select(EventUnknownRecord).where(
            EventUnknownRecord.event_id == event_id,
            EventUnknownRecord.unknown_fingerprint == fingerprint,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_for_event(self, event_id: UUID) -> Sequence[EventUnknownRecord]:
        statement = (
            select(EventUnknownRecord)
            .where(EventUnknownRecord.event_id == event_id)
            .order_by(EventUnknownRecord.created_at.asc(), EventUnknownRecord.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def insert_if_absent(
        self,
        *,
        event_id: UUID,
        unknown_text: str,
        unknown_fingerprint: str,
        status: EventUnknownStatus,
        source_type: EventUnknownSourceType,
        extraction_run_id: UUID | None,
        ai_invocation_id: UUID | None,
        created_by_actor: str | None,
    ) -> tuple[EventUnknownRecord, bool]:
        statement = (
            insert(EventUnknownRecord)
            .values(
                event_id=event_id,
                unknown_text=unknown_text,
                unknown_fingerprint=unknown_fingerprint,
                status=status,
                source_type=source_type,
                extraction_run_id=extraction_run_id,
                ai_invocation_id=ai_invocation_id,
                created_by_actor=created_by_actor,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    EventUnknownRecord.event_id,
                    EventUnknownRecord.unknown_fingerprint,
                ]
            )
            .returning(EventUnknownRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EventUnknownRecord, created_id)
            if created is None:
                raise RuntimeError("EventUnknown 写入成功后未找到记录")
            return created, True
        existing = await self.get_by_fingerprint(event_id, unknown_fingerprint)
        if existing is None:
            raise RuntimeError("EventUnknown 幂等冲突后未找到既有记录")
        return existing, False
