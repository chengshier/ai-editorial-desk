from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.connector_management.repositories.base import Page
from packages.database.models import PlatformAccount
from packages.risk_guard.models import AccountStatus


class PlatformAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, account_id: UUID) -> PlatformAccount | None:
        statement = (
            select(PlatformAccount)
            .options(selectinload(PlatformAccount.connector_instance))
            .where(PlatformAccount.id == account_id)
        )
        return await self.session.scalar(statement)

    async def get_by_identifier(
        self,
        connector_instance_id: UUID,
        platform: str,
        account_identifier: str,
    ) -> PlatformAccount | None:
        statement = select(PlatformAccount).where(
            PlatformAccount.connector_instance_id == connector_instance_id,
            PlatformAccount.platform == platform,
            PlatformAccount.account_identifier == account_identifier,
        )
        return await self.session.scalar(statement)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None = None,
        platform: str | None = None,
        status: AccountStatus | None = None,
        manual_review_required: bool | None = None,
    ) -> Page[PlatformAccount]:
        filters = []
        if connector_instance_id is not None:
            filters.append(PlatformAccount.connector_instance_id == connector_instance_id)
        if platform is not None:
            filters.append(PlatformAccount.platform == platform)
        if status is not None:
            filters.append(PlatformAccount.status == status)
        if manual_review_required is not None:
            filters.append(
                PlatformAccount.manual_review_required.is_(manual_review_required)
            )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(PlatformAccount).where(*filters)
            )
            or 0
        )
        statement = (
            select(PlatformAccount)
            .where(*filters)
            .order_by(PlatformAccount.created_at.desc(), PlatformAccount.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    def add(self, account: PlatformAccount) -> None:
        self.session.add(account)
