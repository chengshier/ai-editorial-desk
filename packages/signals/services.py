from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import ConflictError, ResourceNotFoundError
from packages.connector_management.repositories import (
    AuditLogRepository,
    ConnectorInstanceRepository,
    Page,
)
from packages.connector_management.validation import validate_no_sensitive_fields
from packages.database.models import RawSignalRecord, Source
from packages.signals.domain import IngestionResult, NormalizedSignal
from packages.signals.repositories import RawSignalRepository, SourceRepository
from packages.signals.urls import normalize_http_url

SOURCE_STATUSES = frozenset({"active", "archived"})


def _source_snapshot(source: Source) -> dict[str, Any]:
    return {
        "connector_instance_id": str(source.connector_instance_id),
        "name": source.name,
        "source_type": source.source_type,
        "mode": source.mode,
        "scope_key": source.scope_key,
        "external_ref": source.external_ref,
        "config": source.config,
        "enabled": source.enabled,
        "status": source.status,
        "updated_by": source.updated_by,
    }


class SourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SourceRepository(session)
        self.instances = ConnectorInstanceRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(
        self,
        *,
        connector_instance_id: UUID,
        name: str,
        source_type: str,
        mode: str,
        scope_key: str,
        external_ref: str | None,
        config: dict[str, Any],
        enabled: bool,
        actor: str,
    ) -> Source:
        validate_no_sensitive_fields(config, field_name="source.config")
        async with self.session.begin():
            instance = await self.instances.get(connector_instance_id)
            if instance is None:
                raise ResourceNotFoundError("连接器实例不存在")
            if instance.status == "archived":
                raise ConflictError("不能为已归档实例创建来源")
            if source_type != instance.definition.connector_type:
                raise ConflictError("来源类型必须与连接器定义类型一致")
            duplicate = await self.repository.get_by_scope(
                connector_instance_id,
                mode.strip(),
                scope_key.strip(),
            )
            if duplicate is not None:
                raise ConflictError("该实例、模式和 scope_key 的来源已存在")
            normalized_external_ref = (
                normalize_http_url(external_ref)
                if external_ref is not None and source_type in {"rss", "manual"}
                else external_ref
            )
            source = Source(
                connector_instance_id=connector_instance_id,
                name=name.strip(),
                source_type=source_type,
                mode=mode.strip(),
                scope_key=scope_key.strip(),
                external_ref=normalized_external_ref,
                config=config,
                enabled=enabled,
                status="active",
                updated_by=actor,
            )
            self.repository.add(source)
            await self.session.flush()
            self.audit.add(
                entity_type="source",
                entity_id=source.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_source_snapshot(source),
            )
        return source

    async def get(self, source_id: UUID) -> Source:
        source = await self.repository.get(source_id)
        if source is None:
            raise ResourceNotFoundError("来源不存在")
        return source

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None,
        source_type: str | None,
        enabled: bool | None,
        status: str | None,
    ) -> Page[Source]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            connector_instance_id=connector_instance_id,
            source_type=source_type,
            enabled=enabled,
            status=status,
        )

    async def update(
        self,
        *,
        source_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> Source:
        if "config" in changes:
            validate_no_sensitive_fields(changes["config"], field_name="source.config")
        async with self.session.begin():
            source = await self.repository.get(source_id)
            if source is None:
                raise ResourceNotFoundError("来源不存在")
            if source.status == "archived":
                raise ConflictError("已归档来源不允许修改")
            before = _source_snapshot(source)
            if "name" in changes and source.name != str(changes["name"]).strip():
                source.name = str(changes["name"]).strip()
            if "external_ref" in changes:
                external_ref = changes["external_ref"]
                normalized = (
                    normalize_http_url(external_ref)
                    if external_ref is not None and source.source_type in {"rss", "manual"}
                    else external_ref
                )
                if source.external_ref != normalized:
                    source.external_ref = normalized
            if "config" in changes and source.config != changes["config"]:
                source.config = changes["config"]
            if "enabled" in changes and source.enabled != changes["enabled"]:
                source.enabled = bool(changes["enabled"])
            if before == _source_snapshot(source):
                return source
            source.updated_by = actor
            self.audit.add(
                entity_type="source",
                entity_id=source.id,
                action="update",
                actor=actor,
                before_data=before,
                after_data=_source_snapshot(source),
            )
        return source

    async def archive(self, *, source_id: UUID, actor: str) -> Source:
        async with self.session.begin():
            source = await self.repository.get(source_id)
            if source is None:
                raise ResourceNotFoundError("来源不存在")
            if source.status == "archived":
                return source
            before = _source_snapshot(source)
            source.status = "archived"
            source.enabled = False
            source.updated_by = actor
            self.audit.add(
                entity_type="source",
                entity_id=source.id,
                action="archive",
                actor=actor,
                before_data=before,
                after_data=_source_snapshot(source),
            )
        return source

    async def mark_success(self, source_id: UUID) -> None:
        async with self.session.begin():
            source = await self.repository.get(source_id)
            if source is None:
                raise ResourceNotFoundError("来源不存在")
            source.last_collected_at = datetime.now(UTC)
            source.last_error_at = None
            source.last_error_code = None

    async def mark_error(self, source_id: UUID, error_code: str) -> None:
        async with self.session.begin():
            source = await self.repository.get(source_id)
            if source is None:
                raise ResourceNotFoundError("来源不存在")
            source.last_error_at = datetime.now(UTC)
            source.last_error_code = error_code


class RawSignalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RawSignalRepository(session)

    async def ingest_many(
        self,
        signals: list[NormalizedSignal],
    ) -> list[IngestionResult]:
        async with self.session.begin():
            return [await self.repository.insert(signal) for signal in signals]

    async def get(self, signal_id: UUID) -> RawSignalRecord:
        signal = await self.repository.get(signal_id)
        if signal is None:
            raise ResourceNotFoundError("原始信号不存在")
        return signal

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        source_id: UUID | None,
        connector_instance_id: UUID | None,
        connector_run_id: UUID | None,
        platform: str | None,
        published_from: datetime | None,
        published_to: datetime | None,
    ) -> Page[RawSignalRecord]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            source_id=source_id,
            connector_instance_id=connector_instance_id,
            connector_run_id=connector_run_id,
            platform=platform,
            published_from=published_from,
            published_to=published_to,
        )
