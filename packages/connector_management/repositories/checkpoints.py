from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import ConnectorCheckpoint
from packages.database.types import utc_now


class ConnectorCheckpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, checkpoint_id: UUID) -> ConnectorCheckpoint | None:
        return await self.session.get(ConnectorCheckpoint, checkpoint_id)

    async def get_by_scope(
        self,
        *,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        mode: str,
        scope_key: str,
    ) -> ConnectorCheckpoint | None:
        account_filter = (
            ConnectorCheckpoint.platform_account_id.is_(None)
            if platform_account_id is None
            else ConnectorCheckpoint.platform_account_id == platform_account_id
        )
        statement = select(ConnectorCheckpoint).where(
            ConnectorCheckpoint.connector_instance_id == connector_instance_id,
            account_filter,
            ConnectorCheckpoint.mode == mode,
            ConnectorCheckpoint.scope_key == scope_key,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        *,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        mode: str,
        scope_key: str,
    ) -> ConnectorCheckpoint:
        statement = (
            insert(ConnectorCheckpoint)
            .values(
                connector_instance_id=connector_instance_id,
                platform_account_id=platform_account_id,
                mode=mode,
                scope_key=scope_key,
                checkpoint_data={},
                version=1,
                updated_at=utc_now(),
            )
            .on_conflict_do_nothing(constraint="uq_connector_checkpoints_scope")
        )
        await self.session.execute(statement)
        checkpoint = await self.get_by_scope(
            connector_instance_id=connector_instance_id,
            platform_account_id=platform_account_id,
            mode=mode,
            scope_key=scope_key,
        )
        if checkpoint is None:
            raise RuntimeError("checkpoint insert did not produce a row")
        return checkpoint

    async def optimistic_update(
        self,
        *,
        checkpoint_id: UUID,
        expected_version: int,
        cursor: dict[str, Any] | None,
        watermark: str | None,
        last_external_id: str | None,
        last_published_at: datetime | None,
        checkpoint_data: dict[str, Any],
    ) -> ConnectorCheckpoint | None:
        statement = (
            update(ConnectorCheckpoint)
            .where(
                ConnectorCheckpoint.id == checkpoint_id,
                ConnectorCheckpoint.version == expected_version,
            )
            .values(
                cursor=cursor,
                watermark=watermark,
                last_external_id=last_external_id,
                last_published_at=last_published_at,
                checkpoint_data=checkpoint_data,
                version=ConnectorCheckpoint.version + 1,
                updated_at=utc_now(),
            )
            .returning(ConnectorCheckpoint)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()
