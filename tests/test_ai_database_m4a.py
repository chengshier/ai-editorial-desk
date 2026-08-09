from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.ai_gateway.budget import AIBudgetGate, AIBudgetReservation
from packages.ai_gateway.errors import AIBudgetExceededError
from packages.ai_gateway.management import AIManagementService
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    AIBudgetRecord,
    AIBudgetUsageRecord,
    AIInvocationRecord,
    AIProviderRecord,
    AITaskRouteRecord,
)
from packages.database.session import get_async_sessionmaker
from tests.m4a_helpers import create_ai_stack


@pytest.mark.usefixtures("clean_database")
async def test_postgresql_provider_key_is_unique(db_session) -> None:  # type: ignore[no-untyped-def]
    first = AIProviderRecord(
        provider_key="unique-provider",
        display_name="One",
        provider_type="openai_compatible",
        base_url="https://one.test/v1",
        enabled=False,
        config={},
    )
    db_session.add(first)
    await db_session.commit()

    duplicate = AIProviderRecord(
        provider_key="unique-provider",
        display_name="Two",
        provider_type="openai_compatible",
        base_url="https://two.test/v1",
        enabled=False,
        config={},
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.usefixtures("clean_database")
async def test_postgresql_budget_concurrent_reserve_and_settle(db_session) -> None:  # type: ignore[no-untyped-def]
    budget = AIBudgetRecord(
        scope_type="global",
        scope_key="global",
        enabled=True,
        daily_cost_limit=Decimal("1.00"),
        monthly_cost_limit=Decimal("2.00"),
        daily_token_limit=100,
        unknown_usage_policy="block",
        config={},
    )
    db_session.add(budget)
    await db_session.commit()

    gate = AIBudgetGate(get_async_sessionmaker())

    async def reserve_once() -> AIBudgetReservation:
        return await gate.reserve(
            task_key="draft_generation",
            provider_key="test-provider",
            estimated_cost=Decimal("0.75"),
            estimated_tokens=60,
        )

    results = await asyncio.gather(reserve_once(), reserve_once(), return_exceptions=True)
    reservations = [item for item in results if isinstance(item, AIBudgetReservation)]
    failures = [item for item in results if isinstance(item, AIBudgetExceededError)]
    assert len(reservations) == 1
    assert len(failures) == 1

    await gate.settle(
        reservations[0],
        completed=True,
        actual_cost=Decimal("0.50"),
        actual_tokens=50,
    )
    usage = await db_session.scalar(
        select(AIBudgetUsageRecord).where(AIBudgetUsageRecord.budget_id == budget.id)
    )
    assert usage is not None
    await db_session.refresh(usage)
    assert usage.reserved_cost == Decimal("0")
    assert usage.reserved_tokens == 0
    assert usage.settled_cost == Decimal("0.50000000")
    assert usage.settled_tokens == 50
    assert usage.active_reservations == 0


@pytest.mark.usefixtures("clean_database")
async def test_unknown_cost_budget_is_conservative(db_session) -> None:  # type: ignore[no-untyped-def]
    budget = AIBudgetRecord(
        scope_type="global",
        scope_key="global",
        enabled=True,
        daily_cost_limit=Decimal("1.00"),
        unknown_usage_policy="block",
        config={},
    )
    db_session.add(budget)
    await db_session.commit()
    gate = AIBudgetGate(get_async_sessionmaker())
    with pytest.raises(AIBudgetExceededError):
        await gate.reserve(
            task_key="draft_generation",
            provider_key="test-provider",
            estimated_cost=None,
            estimated_tokens=1,
        )

    budget.unknown_usage_policy = "allow_once"
    await db_session.commit()
    first = await gate.reserve(
        task_key="draft_generation",
        provider_key="test-provider",
        estimated_cost=None,
        estimated_tokens=1,
    )
    with pytest.raises(AIBudgetExceededError):
        await gate.reserve(
            task_key="draft_generation",
            provider_key="test-provider",
            estimated_cost=None,
            estimated_tokens=1,
        )
    await gate.settle(first, completed=False, actual_cost=None, actual_tokens=None)


@pytest.mark.usefixtures("clean_database")
async def test_route_update_keeps_history_and_single_active_version(db_session) -> None:  # type: ignore[no-untyped-def]
    _, primary, _, route_v1 = await create_ai_stack(db_session)
    invocation = AIInvocationRecord(
        task_key="draft_generation",
        route_id=route_v1.id,
        route_version=1,
        provider_key="test-provider",
        model_name=primary.model_name,
        capability="text_generation",
        status="succeeded",
        input_hash="a" * 64,
        pricing_snapshot={"pricing_version": "v1"},
        metadata_json={},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    db_session.add(invocation)
    await db_session.commit()

    route_v2 = await AIManagementService(db_session).update_route(
        task_key="draft_generation",
        values={
            "primary_model_id": primary.id,
            "fallback_model_ids": [],
            "timeout_seconds": 9,
            "retry_limit": 1,
            "budget_policy": {},
            "config": {},
            "enabled": True,
        },
        actor="route-test",
    )
    assert route_v2.version == 2
    versions = list(
        (
            await db_session.scalars(
                select(AITaskRouteRecord)
                .where(AITaskRouteRecord.task_key == "draft_generation")
                .order_by(AITaskRouteRecord.version)
            )
        ).all()
    )
    assert [item.version for item in versions] == [1, 2]
    assert [item.is_active for item in versions] == [False, True]
    await db_session.refresh(invocation)
    assert invocation.route_id == route_v1.id
    assert invocation.route_version == 1


@pytest.mark.usefixtures("clean_database")
async def test_route_concurrent_update_cannot_create_two_active_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    _, primary, _, _ = await create_ai_stack(db_session)
    primary_id = primary.id
    session_factory = get_async_sessionmaker()

    async def update(timeout: int):  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            return await AIManagementService(session).update_route(
                task_key="draft_generation",
                values={
                    "primary_model_id": primary_id,
                    "fallback_model_ids": [],
                    "timeout_seconds": timeout,
                    "retry_limit": 0,
                    "budget_policy": {},
                    "config": {},
                    "enabled": True,
                },
                actor=f"route-{timeout}",
            )

    results = await asyncio.gather(update(7), update(8), return_exceptions=True)
    successes = [item for item in results if isinstance(item, AITaskRouteRecord)]
    expected_failures = [item for item in results if isinstance(item, ResourceNotFoundError)]
    assert len(successes) >= 1
    assert len(successes) + len(expected_failures) == 2

    active = list(
        (
            await db_session.scalars(
                select(AITaskRouteRecord).where(
                    AITaskRouteRecord.task_key == "draft_generation",
                    AITaskRouteRecord.is_active.is_(True),
                )
            )
        ).all()
    )
    assert len(active) == 1
    assert active[0].version >= 2


@pytest.mark.usefixtures("clean_database")
async def test_invocation_uuid_is_database_unique(db_session) -> None:  # type: ignore[no-untyped-def]
    invocation_id = uuid4()
    common = {
        "id": invocation_id,
        "task_key": "test",
        "route_version": 1,
        "capability": "text_generation",
        "status": "failed",
        "input_hash": "b" * 64,
        "pricing_snapshot": {},
        "metadata_json": {},
        "started_at": datetime.now(UTC),
    }
    db_session.add(AIInvocationRecord(**common))
    await db_session.commit()
    db_session.add(AIInvocationRecord(**common))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
