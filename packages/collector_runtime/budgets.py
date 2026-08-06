from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from packages.collector_runtime.budget_repository import CollectionBudgetRepository
from packages.collector_runtime.budget_types import (
    BUDGET_SCOPE_TYPES,
    BudgetReservation,
    budget_snapshot,
)
from packages.collector_runtime.exceptions import BudgetExceededError
from packages.connector_management.exceptions import ConflictError, ResourceNotFoundError
from packages.connector_management.repositories import AuditLogRepository, Page
from packages.database.models import CollectionBudget


class CollectionBudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CollectionBudgetRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(
        self,
        *,
        scope_type: str,
        scope_key: str,
        values: dict[str, Any],
        actor: str,
    ) -> CollectionBudget:
        self._validate(scope_type=scope_type, values=values)
        async with self.session.begin():
            if await self.repository.get_by_scope(scope_type, scope_key.strip()):
                raise ConflictError("该预算作用域已存在")
            budget = CollectionBudget(
                scope_type=scope_type,
                scope_key=scope_key.strip(),
                updated_by=actor,
                **values,
            )
            self.session.add(budget)
            await self.session.flush()
            self.audit.add(
                entity_type="collection_budget",
                entity_id=budget.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=budget_snapshot(budget),
            )
        return budget

    async def get(self, budget_id: UUID) -> CollectionBudget:
        budget = await self.repository.get(budget_id)
        if budget is None:
            raise ResourceNotFoundError("采集预算不存在")
        return budget

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        scope_type: str | None,
        enabled: bool | None,
    ) -> Page[CollectionBudget]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            scope_type=scope_type,
            enabled=enabled,
        )

    async def update(
        self,
        *,
        budget_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> CollectionBudget:
        self._validate(scope_type=None, values=changes)
        async with self.session.begin():
            budget = await self.repository.get(budget_id)
            if budget is None:
                raise ResourceNotFoundError("采集预算不存在")
            before = budget_snapshot(budget)
            for name, value in changes.items():
                if getattr(budget, name) != value:
                    setattr(budget, name, value)
            if before == budget_snapshot(budget):
                return budget
            budget.updated_by = actor
            self.audit.add(
                entity_type="collection_budget",
                entity_id=budget.id,
                action="update",
                actor=actor,
                before_data=before,
                after_data=budget_snapshot(budget),
            )
        return budget

    async def ensure_default(
        self,
        *,
        connector_instance_id: UUID,
        connector_type: str,
        actor: str,
    ) -> CollectionBudget:
        async with self.session.begin():
            budget, created = await self.repository.ensure_default(
                connector_instance_id=connector_instance_id,
                connector_type=connector_type,
                actor=actor,
            )
            if created:
                self._audit_default(budget, actor)
        return budget

    async def reserve(
        self,
        *,
        platform: str,
        connector_instance_id: UUID,
        connector_type: str,
        platform_account_id: UUID | None,
        source_id: UUID,
        requested_items: int,
        actor: str,
    ) -> tuple[BudgetReservation, ...]:
        if requested_items < 1:
            raise BudgetExceededError("requested_limit 必须大于等于 1")
        async with self.session.begin():
            budgets = await self.repository.applicable(
                platform=platform,
                connector_instance_id=connector_instance_id,
                platform_account_id=platform_account_id,
                source_id=source_id,
            )
            if not budgets:
                budget, created = await self.repository.ensure_default(
                    connector_instance_id=connector_instance_id,
                    connector_type=connector_type,
                    actor=actor,
                )
                budgets = [budget]
                if created:
                    self._audit_default(budget, actor)

            reservations: list[BudgetReservation] = []
            now = datetime.now(UTC)
            for budget in sorted(budgets, key=lambda item: str(item.id)):
                usage_date = now.astimezone(ZoneInfo(budget.timezone)).date()
                usage = await self.repository.get_or_create_usage(
                    budget_id=budget.id,
                    usage_date=usage_date,
                )
                if requested_items > budget.max_items_per_run:
                    raise BudgetExceededError("requested_limit 超过单次预算")
                if usage.runs_reserved + 1 > budget.max_runs_per_day:
                    raise BudgetExceededError("已达到当日运行次数预算")
                if (
                    usage.items_used
                    + usage.items_reserved
                    + requested_items
                    > budget.max_items_per_day
                ):
                    raise BudgetExceededError("已达到当日条目预算")
                if usage.active_runs + 1 > budget.max_concurrency:
                    raise BudgetExceededError("已达到并发运行预算")
                usage.runs_reserved += 1
                usage.items_reserved += requested_items
                usage.active_runs += 1
                usage.version += 1
                reservations.append(
                    BudgetReservation(
                        budget_id=budget.id,
                        usage_date=usage_date.isoformat(),
                        reserved_items=requested_items,
                    )
                )
            return tuple(reservations)

    async def settle(
        self,
        *,
        reservations: tuple[BudgetReservation, ...],
        actual_items: int,
        completed: bool,
    ) -> None:
        async with self.session.begin():
            for reservation in sorted(
                reservations,
                key=lambda item: str(item.budget_id),
            ):
                usage = await self.repository.get_or_create_usage(
                    budget_id=reservation.budget_id,
                    usage_date=datetime.fromisoformat(reservation.usage_date).date(),
                )
                usage.active_runs = max(0, usage.active_runs - 1)
                usage.items_reserved = max(
                    0,
                    usage.items_reserved - reservation.reserved_items,
                )
                if completed:
                    usage.runs_completed += 1
                    usage.items_used += max(0, actual_items)
                else:
                    usage.runs_reserved = max(0, usage.runs_reserved - 1)
                usage.version += 1

    def _audit_default(self, budget: CollectionBudget, actor: str) -> None:
        self.audit.add(
            entity_type="collection_budget",
            entity_id=budget.id,
            action="create_default",
            actor=actor,
            before_data={},
            after_data=budget_snapshot(budget),
        )

    @staticmethod
    def _validate(
        *,
        scope_type: str | None,
        values: dict[str, Any],
    ) -> None:
        if scope_type is not None and scope_type not in BUDGET_SCOPE_TYPES:
            raise ValueError("不支持的预算作用域")
        for name in (
            "max_runs_per_day",
            "max_items_per_run",
            "max_items_per_day",
            "max_concurrency",
        ):
            if name in values and int(values[name]) < 1:
                raise ValueError(f"{name} 必须大于等于 1")
        for name in ("max_comments_per_run", "max_comments_per_day"):
            if name in values and int(values[name]) < 0:
                raise ValueError(f"{name} 不能为负数")
        if "timezone" in values:
            try:
                ZoneInfo(str(values["timezone"]))
            except ZoneInfoNotFoundError as exc:
                raise ValueError("预算时区无效") from exc


__all__ = ["BudgetReservation", "CollectionBudgetService"]
