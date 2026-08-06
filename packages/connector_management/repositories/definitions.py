from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.repositories.base import Page
from packages.database.models import ConnectorDefinition


class ConnectorDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, definition_id: UUID) -> ConnectorDefinition | None:
        return await self.session.get(ConnectorDefinition, definition_id)

    async def get_by_key(self, connector_type: str, platform: str) -> ConnectorDefinition | None:
        statement = select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == connector_type,
            ConnectorDefinition.platform == platform,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_type: str | None = None,
        platform: str | None = None,
        is_enabled: bool | None = None,
    ) -> Page[ConnectorDefinition]:
        filters = []
        if connector_type is not None:
            filters.append(ConnectorDefinition.connector_type == connector_type)
        if platform is not None:
            filters.append(ConnectorDefinition.platform == platform)
        if is_enabled is not None:
            filters.append(ConnectorDefinition.is_enabled.is_(is_enabled))

        total_statement = select(func.count()).select_from(ConnectorDefinition).where(*filters)
        total = int(await self.session.scalar(total_statement) or 0)
        statement = (
            select(ConnectorDefinition)
            .where(*filters)
            .order_by(
                ConnectorDefinition.display_name.asc(),
                ConnectorDefinition.platform.asc(),
                ConnectorDefinition.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    def add(self, definition: ConnectorDefinition) -> None:
        self.session.add(definition)
