from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
    VersionConflictError,
)
from packages.connector_management.repositories import ConnectorCheckpointRepository
from packages.connector_management.validation import validate_no_sensitive_fields
from packages.database.models import ConnectorCheckpoint


class ConnectorCheckpointService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConnectorCheckpointRepository(session)

    async def get_or_create(
        self,
        *,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        mode: str,
        scope_key: str,
    ) -> ConnectorCheckpoint:
        async with self.session.begin():
            return await self.repository.get_or_create(
                connector_instance_id=connector_instance_id,
                platform_account_id=platform_account_id,
                mode=mode,
                scope_key=scope_key,
            )

    async def update(
        self,
        *,
        checkpoint_id: UUID,
        expected_version: int,
        cursor: dict[str, Any] | None,
        watermark: str | None,
        last_external_id: str | None,
        last_published_at: datetime | None,
        checkpoint_data: dict[str, Any],
    ) -> ConnectorCheckpoint:
        if expected_version < 1:
            raise BusinessValidationError("expected_version 必须大于等于 1")
        if last_published_at is not None and (
            last_published_at.tzinfo is None or last_published_at.utcoffset() is None
        ):
            raise BusinessValidationError("last_published_at 必须包含时区")
        validate_no_sensitive_fields(cursor or {}, field_name="cursor")
        validate_no_sensitive_fields(checkpoint_data, field_name="checkpoint_data")
        async with self.session.begin():
            updated = await self.repository.optimistic_update(
                checkpoint_id=checkpoint_id,
                expected_version=expected_version,
                cursor=cursor,
                watermark=watermark,
                last_external_id=last_external_id,
                last_published_at=last_published_at,
                checkpoint_data=checkpoint_data,
            )
            if updated is not None:
                return updated
            existing = await self.repository.get(checkpoint_id)
            if existing is None:
                raise ResourceNotFoundError("Checkpoint 不存在")
            raise VersionConflictError(
                "Checkpoint 版本冲突",
                details={
                    "expected_version": expected_version,
                    "current_version": existing.version,
                },
            )
