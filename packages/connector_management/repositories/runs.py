from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.repositories.base import Page
from packages.database.models import ConnectorRun, ConnectorRunStatus


class ConnectorRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, run_id: UUID) -> ConnectorRun | None:
        return await self.session.get(ConnectorRun, run_id)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None = None,
        platform_account_id: UUID | None = None,
        status: ConnectorRunStatus | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
    ) -> Page[ConnectorRun]:
        filters = []
        if connector_instance_id is not None:
            filters.append(ConnectorRun.connector_instance_id == connector_instance_id)
        if platform_account_id is not None:
            filters.append(ConnectorRun.platform_account_id == platform_account_id)
        if status is not None:
            filters.append(ConnectorRun.status == status)
        if started_from is not None:
            filters.append(ConnectorRun.started_at >= started_from)
        if started_to is not None:
            filters.append(ConnectorRun.started_at <= started_to)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ConnectorRun).where(*filters)
            )
            or 0
        )
        statement = (
            select(ConnectorRun)
            .where(*filters)
            .order_by(ConnectorRun.created_at.desc(), ConnectorRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    def add(self, run: ConnectorRun) -> None:
        self.session.add(run)
