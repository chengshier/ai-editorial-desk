from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.connector_management.repositories.base import Page
from packages.database.models import ConnectorInstance


class ConnectorInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, instance_id: UUID) -> ConnectorInstance | None:
        statement = (
            select(ConnectorInstance)
            .options(selectinload(ConnectorInstance.definition))
            .where(ConnectorInstance.id == instance_id)
        )
        return await self.session.scalar(statement)

    async def get_by_name(self, definition_id: UUID, name: str) -> ConnectorInstance | None:
        statement = select(ConnectorInstance).where(
            ConnectorInstance.definition_id == definition_id,
            ConnectorInstance.name == name,
        )
        return await self.session.scalar(statement)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        definition_id: UUID | None = None,
        enabled: bool | None = None,
        status: str | None = None,
    ) -> Page[ConnectorInstance]:
        filters = []
        if definition_id is not None:
            filters.append(ConnectorInstance.definition_id == definition_id)
        if enabled is not None:
            filters.append(ConnectorInstance.enabled.is_(enabled))
        if status is not None:
            filters.append(ConnectorInstance.status == status)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ConnectorInstance).where(*filters)
            )
            or 0
        )
        statement = (
            select(ConnectorInstance)
            .options(selectinload(ConnectorInstance.definition))
            .where(*filters)
            .order_by(ConnectorInstance.created_at.desc(), ConnectorInstance.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    def add(self, instance: ConnectorInstance) -> None:
        self.session.add(instance)
