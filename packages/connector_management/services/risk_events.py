from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import (
    AuditLogRepository,
    Page,
    PlatformRiskEventRepository,
)
from packages.database.models import PlatformRiskEvent


class PlatformRiskEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PlatformRiskEventRepository(session)
        self.audit = AuditLogRepository(session)

    async def get(self, event_id: UUID) -> PlatformRiskEvent:
        event = await self.repository.get(event_id)
        if event is None:
            raise ResourceNotFoundError("风险事件不存在")
        return event

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        platform: str | None,
        platform_account_id: UUID | None,
        risk_level: str | None,
        resolved: bool | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> Page[PlatformRiskEvent]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            platform=platform,
            platform_account_id=platform_account_id,
            risk_level=risk_level,
            resolved=resolved,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )

    async def resolve(
        self,
        *,
        event_id: UUID,
        resolution_note: str,
        actor: str,
    ) -> PlatformRiskEvent:
        note = resolution_note.strip()
        if len(note) < 3:
            raise BusinessValidationError("处理风险事件必须填写处理说明")
        async with self.session.begin():
            event = await self.repository.get(event_id)
            if event is None:
                raise ResourceNotFoundError("风险事件不存在")
            if event.resolved_at is not None:
                raise ConflictError("风险事件已经处理")
            before = {
                "resolved_at": None,
                "resolved_by": None,
                "resolution_note": None,
            }
            event.resolved_at = datetime.now(UTC)
            event.resolved_by = actor
            event.resolution_note = note
            self.audit.add(
                entity_type="platform_risk_event",
                entity_id=event.id,
                action="resolve",
                actor=actor,
                before_data=before,
                after_data={
                    "resolved_at": event.resolved_at.isoformat(),
                    "resolved_by": actor,
                    "resolution_note": note,
                    "account_status_changed": False,
                },
            )
        return event
