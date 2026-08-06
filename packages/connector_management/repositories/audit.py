from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import ConfigurationChangeLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: str,
        before_data: dict[str, Any],
        after_data: dict[str, Any],
    ) -> ConfigurationChangeLog:
        log = ConfigurationChangeLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            before_data=before_data,
            after_data=after_data,
        )
        self.session.add(log)
        return log
