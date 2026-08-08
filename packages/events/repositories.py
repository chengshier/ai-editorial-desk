from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.repositories.base import Page
from packages.database.models import EventRecord, EventSignalRecord, RawSignalRecord
from packages.database.models.events import EventSignalAttachedBy, EventSignalRelation


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: UUID) -> EventRecord | None:
        return await self.session.get(EventRecord, event_id)

    async def get_for_update(self, event_id: UUID) -> EventRecord | None:
        statement = select(EventRecord).where(EventRecord.id == event_id).with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        include_merged: bool = False,
    ) -> Page[EventRecord]:
        filters = []
        if status is not None:
            filters.append(EventRecord.status == status)
        if not include_merged:
            filters.append(EventRecord.merged_into_event_id.is_(None))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(EventRecord).where(*filters)
            )
            or 0
        )
        statement = (
            select(EventRecord)
            .where(*filters)
            .order_by(
                EventRecord.last_updated_at.desc(),
                EventRecord.created_at.desc(),
                EventRecord.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def merged_children(self, event_id: UUID) -> Sequence[EventRecord]:
        statement = (
            select(EventRecord)
            .where(EventRecord.merged_into_event_id == event_id)
            .order_by(EventRecord.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    def add(self, event: EventRecord) -> None:
        self.session.add(event)


class EventSignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: UUID, signal_id: UUID) -> EventSignalRecord | None:
        statement = select(EventSignalRecord).where(
            EventSignalRecord.event_id == event_id,
            EventSignalRecord.signal_id == signal_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        *,
        event_id: UUID,
        page: int,
        page_size: int,
    ) -> Page[EventSignalRecord]:
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(EventSignalRecord)
                .where(EventSignalRecord.event_id == event_id)
            )
            or 0
        )
        statement = (
            select(EventSignalRecord)
            .where(EventSignalRecord.event_id == event_id)
            .order_by(EventSignalRecord.created_at.asc(), EventSignalRecord.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def list_all(self, event_id: UUID) -> Sequence[EventSignalRecord]:
        statement = (
            select(EventSignalRecord)
            .where(EventSignalRecord.event_id == event_id)
            .order_by(EventSignalRecord.signal_id.asc(), EventSignalRecord.id.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def attach(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
        relation: EventSignalRelation,
        confidence: float,
        attached_by: EventSignalAttachedBy,
    ) -> tuple[EventSignalRecord, bool]:
        statement = (
            insert(EventSignalRecord)
            .values(
                event_id=event_id,
                signal_id=signal_id,
                relation=relation,
                confidence=confidence,
                attached_by=attached_by,
            )
            .on_conflict_do_nothing(
                index_elements=[EventSignalRecord.event_id, EventSignalRecord.signal_id]
            )
            .returning(EventSignalRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EventSignalRecord, created_id)
            if created is None:
                raise RuntimeError("EventSignal 写入成功后未找到关联记录")
            return created, True

        existing = await self.get(event_id, signal_id)
        if existing is None:
            raise RuntimeError("EventSignal 幂等冲突后未找到既有关联")
        return existing, False

    async def aggregate_stats(
        self, event_id: UUID
    ) -> tuple[int, int, datetime | None]:
        effective_seen_at = func.coalesce(
            RawSignalRecord.published_at, RawSignalRecord.collected_at
        )
        statement = (
            select(
                func.count(func.distinct(RawSignalRecord.source_id)),
                func.count(func.distinct(RawSignalRecord.platform)),
                func.min(effective_seen_at),
            )
            .select_from(EventSignalRecord)
            .join(RawSignalRecord, RawSignalRecord.id == EventSignalRecord.signal_id)
            .where(EventSignalRecord.event_id == event_id)
        )
        row = (await self.session.execute(statement)).one()
        return int(row[0] or 0), int(row[1] or 0), row[2]

    async def delete(self, association: EventSignalRecord) -> None:
        await self.session.delete(association)
