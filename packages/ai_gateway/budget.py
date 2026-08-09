from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.errors import AIBudgetExceededError
from packages.database.models import AIBudgetRecord, AIBudgetUsageRecord

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class AIBudgetReservationItem:
    budget_id: UUID
    usage_date: date
    reserved_cost: Decimal
    reserved_tokens: int
    unknown_reserved: bool


@dataclass(frozen=True, slots=True)
class AIBudgetReservation:
    items: tuple[AIBudgetReservationItem, ...]


class AIBudgetGate:
    """Serialize budget reservations with PostgreSQL row locks before provider calls."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def reserve(
        self,
        *,
        task_key: str,
        provider_key: str,
        estimated_cost: Decimal | None,
        estimated_tokens: int,
    ) -> AIBudgetReservation:
        if estimated_cost is not None and estimated_cost < 0:
            raise ValueError("estimated_cost 不能为负数")
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens 不能为负数")
        today = datetime.now(UTC).date()
        items: list[AIBudgetReservationItem] = []
        async with self.session_factory() as session:
            async with session.begin():
                budgets = list(
                    (
                        await session.scalars(
                            select(AIBudgetRecord)
                            .where(
                                AIBudgetRecord.enabled.is_(True),
                                or_(
                                    and_(
                                        AIBudgetRecord.scope_type == "global",
                                        AIBudgetRecord.scope_key == "global",
                                    ),
                                    and_(
                                        AIBudgetRecord.scope_type == "task",
                                        AIBudgetRecord.scope_key == task_key,
                                    ),
                                    and_(
                                        AIBudgetRecord.scope_type == "provider",
                                        AIBudgetRecord.scope_key == provider_key,
                                    ),
                                ),
                            )
                            .order_by(AIBudgetRecord.id)
                            .with_for_update()
                        )
                    ).all()
                )
                for budget in budgets:
                    usage = await self._usage(session, budget.id, today)
                    unknown_reserved = estimated_cost is None and (
                        budget.daily_cost_limit is not None or budget.monthly_cost_limit is not None
                    )
                    if unknown_reserved:
                        if budget.unknown_usage_policy == "block":
                            raise AIBudgetExceededError("AI 成本未知，预算策略禁止调用")
                        if usage.unknown_usage_count > 0:
                            raise AIBudgetExceededError("AI 未知用量额度已使用")
                    reserved_cost = estimated_cost or ZERO
                    projected_daily_cost = usage.settled_cost + usage.reserved_cost + reserved_cost
                    if (
                        budget.daily_cost_limit is not None
                        and projected_daily_cost > budget.daily_cost_limit
                    ):
                        raise AIBudgetExceededError("AI daily cost budget exceeded")
                    projected_tokens = usage.settled_tokens + usage.reserved_tokens + estimated_tokens
                    if (
                        budget.daily_token_limit is not None
                        and projected_tokens > budget.daily_token_limit
                    ):
                        raise AIBudgetExceededError("AI daily token budget exceeded")
                    if budget.monthly_cost_limit is not None:
                        month_start = today.replace(day=1)
                        monthly = await session.scalar(
                            select(
                                func.coalesce(
                                    func.sum(
                                        AIBudgetUsageRecord.settled_cost
                                        + AIBudgetUsageRecord.reserved_cost
                                    ),
                                    ZERO,
                                )
                            ).where(
                                AIBudgetUsageRecord.budget_id == budget.id,
                                AIBudgetUsageRecord.usage_date >= month_start,
                                AIBudgetUsageRecord.usage_date <= today,
                            )
                        )
                        projected_monthly = Decimal(monthly or ZERO) + reserved_cost
                        if projected_monthly > budget.monthly_cost_limit:
                            raise AIBudgetExceededError("AI monthly cost budget exceeded")
                    usage.reserved_cost += reserved_cost
                    usage.reserved_tokens += estimated_tokens
                    usage.active_reservations += 1
                    if unknown_reserved:
                        usage.unknown_usage_count += 1
                    usage.version += 1
                    items.append(
                        AIBudgetReservationItem(
                            budget_id=budget.id,
                            usage_date=today,
                            reserved_cost=reserved_cost,
                            reserved_tokens=estimated_tokens,
                            unknown_reserved=unknown_reserved,
                        )
                    )
        return AIBudgetReservation(items=tuple(items))

    async def settle(
        self,
        reservation: AIBudgetReservation,
        *,
        completed: bool,
        actual_cost: Decimal | None,
        actual_tokens: int | None,
    ) -> None:
        if actual_cost is not None and actual_cost < 0:
            raise ValueError("actual_cost 不能为负数")
        if actual_tokens is not None and actual_tokens < 0:
            raise ValueError("actual_tokens 不能为负数")
        async with self.session_factory() as session:
            async with session.begin():
                for item in sorted(reservation.items, key=lambda value: str(value.budget_id)):
                    budget = await session.scalar(
                        select(AIBudgetRecord)
                        .where(AIBudgetRecord.id == item.budget_id)
                        .with_for_update()
                    )
                    if budget is None:
                        continue
                    usage = await self._usage(session, item.budget_id, item.usage_date)
                    usage.reserved_cost = max(ZERO, usage.reserved_cost - item.reserved_cost)
                    usage.reserved_tokens = max(0, usage.reserved_tokens - item.reserved_tokens)
                    usage.active_reservations = max(0, usage.active_reservations - 1)
                    if completed:
                        if actual_cost is not None:
                            usage.settled_cost += actual_cost
                        if actual_tokens is not None:
                            usage.settled_tokens += actual_tokens
                        needs_cost = (
                            budget.daily_cost_limit is not None
                            or budget.monthly_cost_limit is not None
                        )
                        needs_tokens = budget.daily_token_limit is not None
                        newly_unknown = (needs_cost and actual_cost is None) or (
                            needs_tokens and actual_tokens is None
                        )
                        if newly_unknown and not item.unknown_reserved:
                            usage.unknown_usage_count += 1
                    elif item.unknown_reserved:
                        usage.unknown_usage_count = max(0, usage.unknown_usage_count - 1)
                    usage.version += 1

    @staticmethod
    async def _usage(
        session: AsyncSession,
        budget_id: UUID,
        usage_date: date,
    ) -> AIBudgetUsageRecord:
        usage = await session.scalar(
            select(AIBudgetUsageRecord)
            .where(
                AIBudgetUsageRecord.budget_id == budget_id,
                AIBudgetUsageRecord.usage_date == usage_date,
            )
            .with_for_update()
        )
        if usage is None:
            usage = AIBudgetUsageRecord(budget_id=budget_id, usage_date=usage_date)
            session.add(usage)
            await session.flush()
        return usage
