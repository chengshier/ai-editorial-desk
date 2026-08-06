from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
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
        source_id: UUID | None = None,
        status: ConnectorRunStatus | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
    ) -> Page[ConnectorRun]:
        filters = []
        if connector_instance_id is not None:
            filters.append(ConnectorRun.connector_instance_id == connector_instance_id)
        if platform_account_id is not None:
            filters.append(ConnectorRun.platform_account_id == platform_account_id)
        if source_id is not None:
            filters.append(ConnectorRun.source_id == source_id)
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

    async def atomic_transition(
        self,
        *,
        run_id: UUID,
        expected_statuses: frozenset[ConnectorRunStatus],
        target_status: ConnectorRunStatus,
        values: dict[str, Any],
    ) -> ConnectorRun | None:
        statement = (
            update(ConnectorRun)
            .where(
                ConnectorRun.id == run_id,
                ConnectorRun.status.in_(expected_statuses),
            )
            .values(status=target_status, **values)
            .returning(ConnectorRun)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def atomic_progress(
        self,
        *,
        run_id: UUID,
        values: dict[str, Any],
    ) -> ConnectorRun | None:
        statement = (
            update(ConnectorRun)
            .where(
                ConnectorRun.id == run_id,
                ConnectorRun.status == ConnectorRunStatus.RUNNING,
            )
            .values(**values)
            .returning(ConnectorRun)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def has_active_for_source(self, source_id: UUID) -> bool:
        count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ConnectorRun)
                .where(
                    ConnectorRun.source_id == source_id,
                    ConnectorRun.status.in_(
                        {
                            ConnectorRunStatus.PENDING,
                            ConnectorRunStatus.RUNNING,
                        }
                    ),
                )
            )
            or 0
        )
        return count > 0

    def add(self, run: ConnectorRun) -> None:
        self.session.add(run)
