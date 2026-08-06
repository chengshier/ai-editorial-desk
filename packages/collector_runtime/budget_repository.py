from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from packages.collector_runtime.budget_types import default_budget_values
from packages.connector_management.repositories import Page
from packages.database.models import CollectionBudget, CollectionBudgetUsage


class CollectionBudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, budget_id: UUID) -> CollectionBudget | None:
        return await self.session.get(CollectionBudget, budget_id)

    async def get_by_scope(
        self,
        scope_type: str,
        scope_key: str,
    ) -> CollectionBudget | None:
        result = await self.session.execute(
            select(CollectionBudget).where(
                CollectionBudget.scope_type == scope_type,
                CollectionBudget.scope_key == scope_key,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        scope_type: str | None,
        enabled: bool | None,
    ) -> Page[CollectionBudget]:
        filters: list[ColumnElement[bool]] = []
        if scope_type is not None:
            filters.append(CollectionBudget.scope_type == scope_type)
        if enabled is not None:
            filters.append(CollectionBudget.enabled.is_(enabled))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(CollectionBudget).where(*filters)
            )
            or 0
        )
        statement = (
            select(CollectionBudget)
            .where(*filters)
            .order_by(
                CollectionBudget.created_at.desc(),
                CollectionBudget.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def applicable(
        self,
        *,
        platform: str,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        source_id: UUID,
    ) -> list[CollectionBudget]:
        clauses: list[ColumnElement[bool]] = [
            (CollectionBudget.scope_type == "platform")
            & (CollectionBudget.scope_key == platform),
            (CollectionBudget.scope_type == "connector")
            & (CollectionBudget.scope_key == str(connector_instance_id)),
            (CollectionBudget.scope_type == "task")
            & (CollectionBudget.scope_key == str(source_id)),
        ]
        if platform_account_id is not None:
            clauses.append(
                (CollectionBudget.scope_type == "account")
                & (CollectionBudget.scope_key == str(platform_account_id))
            )
        statement = (
            select(CollectionBudget)
            .where(CollectionBudget.enabled.is_(True), or_(*clauses))
            .order_by(CollectionBudget.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def ensure_default(
        self,
        *,
        connector_instance_id: UUID,
        connector_type: str,
        actor: str,
    ) -> tuple[CollectionBudget, bool]:
        statement = (
            insert(CollectionBudget)
            .values(
                scope_type="connector",
                scope_key=str(connector_instance_id),
                updated_by=actor,
                **default_budget_values(connector_type),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CollectionBudget.scope_type,
                    CollectionBudget.scope_key,
                ]
            )
            .returning(CollectionBudget.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        budget = await self.get_by_scope("connector", str(connector_instance_id))
        if budget is None:
            raise RuntimeError("默认预算写入后未找到记录")
        return budget, created_id is not None

    async def get_or_create_usage(
        self,
        *,
        budget_id: UUID,
        usage_date: date,
    ) -> CollectionBudgetUsage:
        await self.session.execute(
            insert(CollectionBudgetUsage)
            .values(budget_id=budget_id, usage_date=usage_date)
            .on_conflict_do_nothing(
                index_elements=[
                    CollectionBudgetUsage.budget_id,
                    CollectionBudgetUsage.usage_date,
                ]
            )
        )
        result = await self.session.execute(
            select(CollectionBudgetUsage)
            .where(
                CollectionBudgetUsage.budget_id == budget_id,
                CollectionBudgetUsage.usage_date == usage_date,
            )
            .with_for_update()
        )
        usage = result.scalar_one_or_none()
        if usage is None:
            raise RuntimeError("预算使用记录创建失败")
        return usage
