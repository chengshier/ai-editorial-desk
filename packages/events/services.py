from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import AuditLogRepository, Page
from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
)
from packages.database.types import utc_now
from packages.events.repositories import EventRepository, EventSignalRepository
from packages.signals.repositories import RawSignalRepository


def _event_snapshot(event: EventRecord) -> dict[str, Any]:
    return {
        "title": event.title,
        "summary": event.summary,
        "category": event.category,
        "status": event.status.value,
        "first_seen_at": event.first_seen_at.isoformat() if event.first_seen_at else None,
        "last_updated_at": event.last_updated_at.isoformat(),
        "primary_language": event.primary_language,
        "entities": event.entities,
        "keywords": event.keywords,
        "source_count": event.source_count,
        "platform_count": event.platform_count,
    }


def _association_snapshot(association: EventSignalRecord) -> dict[str, Any]:
    return {
        "signal_id": str(association.signal_id),
        "relation": association.relation.value,
        "confidence": association.confidence,
        "attached_by": association.attached_by.value,
    }


class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)
        self.event_signals = EventSignalRepository(session)
        self.raw_signals = RawSignalRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(
        self,
        *,
        title: str,
        summary: str | None,
        category: str | None,
        status: EventStatus,
        primary_language: str | None,
        entities: list[dict[str, Any]],
        keywords: list[str],
        actor: str,
    ) -> EventRecord:
        normalized_title = title.strip()
        if not normalized_title:
            raise BusinessValidationError("事件标题不能为空")
        now = utc_now()
        async with self.session.begin():
            event = EventRecord(
                title=normalized_title,
                summary=summary.strip() if summary is not None else None,
                category=category.strip() if category is not None else None,
                status=status,
                first_seen_at=None,
                last_updated_at=now,
                primary_language=(
                    primary_language.strip() if primary_language is not None else None
                ),
                entities=entities,
                keywords=keywords,
                source_count=0,
                platform_count=0,
            )
            self.events.add(event)
            await self.session.flush()
            self.audit.add(
                entity_type="event",
                entity_id=event.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_event_snapshot(event),
            )
        return event

    async def get(self, event_id: UUID) -> EventRecord:
        event = await self.events.get(event_id)
        if event is None:
            raise ResourceNotFoundError("事件不存在")
        return event

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> Page[EventRecord]:
        return await self.events.list(page=page, page_size=page_size, status=status)

    async def list_signals(
        self,
        *,
        event_id: UUID,
        page: int,
        page_size: int,
    ) -> Page[EventSignalRecord]:
        if await self.events.get(event_id) is None:
            raise ResourceNotFoundError("事件不存在")
        return await self.event_signals.list(
            event_id=event_id, page=page, page_size=page_size
        )

    async def attach_signal(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
        relation: EventSignalRelation,
        confidence: float,
        attached_by: EventSignalAttachedBy,
        actor: str,
    ) -> tuple[EventSignalRecord, bool]:
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise BusinessValidationError("confidence 必须是 0 到 1 之间的有限数值")

        async with self.session.begin():
            event = await self.events.get_for_update(event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            if await self.raw_signals.get(signal_id) is None:
                raise ResourceNotFoundError("原始信号不存在")

            before = _event_snapshot(event)
            association, created = await self.event_signals.attach(
                event_id=event_id,
                signal_id=signal_id,
                relation=relation,
                confidence=confidence,
                attached_by=attached_by,
            )
            if not created:
                return association, False

            await self._recalculate_aggregates(event)
            event.last_updated_at = utc_now()
            await self.session.flush()
            self.audit.add(
                entity_type="event",
                entity_id=event.id,
                action="attach_signal",
                actor=actor,
                before_data={"event": before},
                after_data={
                    "event": _event_snapshot(event),
                    "association": _association_snapshot(association),
                },
            )
            return association, True

    async def detach_signal(
        self,
        *,
        event_id: UUID,
        signal_id: UUID,
        actor: str,
    ) -> bool:
        async with self.session.begin():
            event = await self.events.get_for_update(event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            association = await self.event_signals.get(event_id, signal_id)
            if association is None:
                return False

            before_event = _event_snapshot(event)
            before_association = _association_snapshot(association)
            await self.event_signals.delete(association)
            await self.session.flush()
            await self._recalculate_aggregates(event)
            event.last_updated_at = utc_now()
            await self.session.flush()
            self.audit.add(
                entity_type="event",
                entity_id=event.id,
                action="detach_signal",
                actor=actor,
                before_data={
                    "event": before_event,
                    "association": before_association,
                },
                after_data={"event": _event_snapshot(event)},
            )
            return True

    async def _recalculate_aggregates(self, event: EventRecord) -> None:
        source_count, platform_count, first_seen_at = (
            await self.event_signals.aggregate_stats(event.id)
        )
        event.source_count = source_count
        event.platform_count = platform_count
        event.first_seen_at = first_seen_at
