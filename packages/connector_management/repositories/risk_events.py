from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.repositories.base import Page
from packages.database.models import PlatformRiskEvent


class PlatformRiskEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: UUID) -> PlatformRiskEvent | None:
        return await self.session.get(PlatformRiskEvent, event_id)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        platform: str | None = None,
        platform_account_id: UUID | None = None,
        risk_level: str | None = None,
        resolved: bool | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
    ) -> Page[PlatformRiskEvent]:
        filters = []
        if platform is not None:
            filters.append(PlatformRiskEvent.platform == platform)
        if platform_account_id is not None:
            filters.append(PlatformRiskEvent.platform_account_id == platform_account_id)
        if risk_level is not None:
            filters.append(PlatformRiskEvent.risk_level == risk_level)
        if resolved is True:
            filters.append(PlatformRiskEvent.resolved_at.is_not(None))
        elif resolved is False:
            filters.append(PlatformRiskEvent.resolved_at.is_(None))
        if occurred_from is not None:
            filters.append(PlatformRiskEvent.occurred_at >= occurred_from)
        if occurred_to is not None:
            filters.append(PlatformRiskEvent.occurred_at <= occurred_to)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(PlatformRiskEvent).where(*filters)
            )
            or 0
        )
        statement = (
            select(PlatformRiskEvent)
            .where(*filters)
            .order_by(PlatformRiskEvent.occurred_at.desc(), PlatformRiskEvent.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)
