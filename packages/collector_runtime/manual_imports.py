from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from packages.collector_runtime.context import RuntimeResult
from packages.collector_runtime.exceptions import PreflightRejectedError
from packages.collector_runtime.protocols import CollectionTask, TriggerType
from packages.collector_runtime.runtime import CollectorRuntime
from packages.connector_management.exceptions import ConflictError
from packages.database.models import ConnectorInstance, Source
from packages.signals.repositories import SourceRepository
from packages.signals.services import SourceService
from packages.signals.urls import normalize_http_url


@dataclass(slots=True, frozen=True)
class ManualImportOutcome:
    source_id: UUID
    normalized_url: str
    runtime: RuntimeResult


class ManualImportService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        runtime: CollectorRuntime,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime

    async def execute(
        self,
        *,
        connector_instance_id: UUID,
        url: str,
        title: str | None,
        text: str | None,
        note: str | None,
        fetch_metadata: bool,
        actor: str,
    ) -> ManualImportOutcome:
        normalized_url = normalize_http_url(url)
        await self._validate_instance(connector_instance_id)
        source = await self._ensure_source(
            connector_instance_id=connector_instance_id,
            normalized_url=normalized_url,
            title=title,
            text=text,
            note=note,
            fetch_metadata=fetch_metadata,
            actor=actor,
        )
        result = await self.runtime.execute(
            CollectionTask(
                task_id=uuid4(),
                connector_instance_id=connector_instance_id,
                source_id=source.id,
                platform_account_id=None,
                mode="manual_import",
                requested_limit=1,
                checkpoint_version=None,
                trigger_type=TriggerType.MANUAL,
                triggered_by=actor,
                created_at=datetime.now(UTC),
            )
        )
        return ManualImportOutcome(
            source_id=source.id,
            normalized_url=normalized_url,
            runtime=result,
        )

    async def _validate_instance(self, instance_id: UUID) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConnectorInstance)
                .options(selectinload(ConnectorInstance.definition))
                .where(ConnectorInstance.id == instance_id)
            )
            instance = result.scalar_one_or_none()
            if instance is None:
                raise PreflightRejectedError("连接器实例不存在")
            if instance.definition.connector_type != "manual":
                raise PreflightRejectedError("该接口只能使用手工 URL 连接器实例")

    async def _ensure_source(
        self,
        *,
        connector_instance_id: UUID,
        normalized_url: str,
        title: str | None,
        text: str | None,
        note: str | None,
        fetch_metadata: bool,
        actor: str,
    ) -> Source:
        config = {
            "url": normalized_url,
            "title": title,
            "text": text,
            "note": note,
            "fetch_metadata": fetch_metadata,
        }
        async with self.session_factory() as session:
            existing = await SourceRepository(session).get_by_scope(
                connector_instance_id,
                "manual_import",
                normalized_url,
            )
            existing_id = existing.id if existing is not None else None
        if existing_id is not None:
            async with self.session_factory() as session:
                return await SourceService(session).update(
                    source_id=existing_id,
                    changes={
                        "name": title or normalized_url,
                        "external_ref": normalized_url,
                        "config": config,
                        "enabled": True,
                    },
                    actor=actor,
                )
        try:
            async with self.session_factory() as session:
                return await SourceService(session).create(
                    connector_instance_id=connector_instance_id,
                    name=title or normalized_url,
                    source_type="manual",
                    mode="manual_import",
                    scope_key=normalized_url,
                    external_ref=normalized_url,
                    config=config,
                    enabled=True,
                    actor=actor,
                )
        except ConflictError:
            async with self.session_factory() as session:
                existing = await SourceRepository(session).get_by_scope(
                    connector_instance_id,
                    "manual_import",
                    normalized_url,
                )
                if existing is None:
                    raise
                return existing
