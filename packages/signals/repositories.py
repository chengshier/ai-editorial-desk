from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.repositories.base import Page
from packages.database.models import RawSignalRecord, Source
from packages.database.types import sanitize_context
from packages.signals.domain import IngestionResult, NormalizedSignal
from packages.signals.idempotency import build_content_hash, build_idempotency_key


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, source_id: UUID) -> Source | None:
        return await self.session.get(Source, source_id)

    async def get_by_scope(
        self, connector_instance_id: UUID, mode: str, scope_key: str
    ) -> Source | None:
        statement = select(Source).where(
            Source.connector_instance_id == connector_instance_id,
            Source.mode == mode,
            Source.scope_key == scope_key,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None = None,
        source_type: str | None = None,
        enabled: bool | None = None,
        status: str | None = None,
    ) -> Page[Source]:
        filters = []
        if connector_instance_id is not None:
            filters.append(Source.connector_instance_id == connector_instance_id)
        if source_type is not None:
            filters.append(Source.source_type == source_type)
        if enabled is not None:
            filters.append(Source.enabled.is_(enabled))
        if status is not None:
            filters.append(Source.status == status)
        total = int(
            await self.session.scalar(select(func.count()).select_from(Source).where(*filters))
            or 0
        )
        statement = (
            select(Source)
            .where(*filters)
            .order_by(Source.created_at.desc(), Source.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    def add(self, source: Source) -> None:
        self.session.add(source)


class RawSignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, signal_id: UUID) -> RawSignalRecord | None:
        return await self.session.get(RawSignalRecord, signal_id)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        source_id: UUID | None = None,
        connector_instance_id: UUID | None = None,
        connector_run_id: UUID | None = None,
        platform: str | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
    ) -> Page[RawSignalRecord]:
        filters = []
        if source_id is not None:
            filters.append(RawSignalRecord.source_id == source_id)
        if connector_instance_id is not None:
            filters.append(RawSignalRecord.connector_instance_id == connector_instance_id)
        if connector_run_id is not None:
            filters.append(RawSignalRecord.connector_run_id == connector_run_id)
        if platform is not None:
            filters.append(RawSignalRecord.platform == platform)
        if published_from is not None:
            filters.append(RawSignalRecord.published_at >= published_from)
        if published_to is not None:
            filters.append(RawSignalRecord.published_at <= published_to)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(RawSignalRecord).where(*filters)
            )
            or 0
        )
        statement = (
            select(RawSignalRecord)
            .where(*filters)
            .order_by(
                RawSignalRecord.published_at.desc().nullslast(),
                RawSignalRecord.created_at.desc(),
                RawSignalRecord.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def insert(self, signal: NormalizedSignal) -> IngestionResult:
        content_hash = build_content_hash(title=signal.title, text=signal.text)
        idempotency_key = build_idempotency_key(
            connector_type=signal.connector_type,
            platform=signal.platform,
            source_id=signal.source_id,
            external_id=signal.external_id,
            canonical_url=signal.canonical_url,
            content_hash=content_hash,
            published_at=signal.published_at,
        )
        statement = (
            insert(RawSignalRecord)
            .values(
                source_id=signal.source_id,
                connector_instance_id=signal.connector_instance_id,
                connector_run_id=signal.connector_run_id,
                platform=signal.platform,
                external_id=signal.external_id,
                original_url=signal.original_url,
                canonical_url=signal.canonical_url,
                title=signal.title,
                text=signal.text,
                author_id=signal.author_id,
                author_name=signal.author_name,
                published_at=signal.published_at,
                metrics=signal.metrics,
                media=signal.media,
                raw_payload=sanitize_context(signal.raw_payload),
                language=signal.language,
                content_hash=content_hash,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=[RawSignalRecord.idempotency_key])
            .returning(RawSignalRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            return IngestionResult(signal_id=created_id, created=True, duplicate=False)
        existing_id = await self.session.scalar(
            select(RawSignalRecord.id).where(
                RawSignalRecord.idempotency_key == idempotency_key
            )
        )
        if existing_id is None:
            raise RuntimeError("幂等写入冲突后未找到既有 Raw Signal")
        return IngestionResult(signal_id=existing_id, created=False, duplicate=True)
