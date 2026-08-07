import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from packages.collector_runtime.budget_types import BudgetReservation
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.exceptions import BudgetExceededError
from packages.connector_management.exceptions import InvalidStateTransitionError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    ConnectorRunService,
)
from packages.database.models import ConnectorDefinition, ConnectorRunStatus
from packages.database.session import get_async_sessionmaker
from packages.signals.services import SourceService


async def _instance_source(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.connector_type == "rss")
    )
    assert definition is not None
    definition_id = definition.id
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition_id,
        name=f"runtime-{uuid4()}",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={},
        actor="admin",
    )
    instance = await ConnectorInstanceService(db_session).enable(
        instance_id=instance.id,
        actor="admin",
    )
    source = await SourceService(db_session).create(
        connector_instance_id=instance.id,
        name="feed",
        source_type="rss",
        mode="feed",
        scope_key=f"scope:{uuid4()}",
        external_ref="https://example.com/feed.xml",
        config={},
        enabled=True,
        actor="admin",
    )
    return instance, source


@pytest.mark.usefixtures("clean_database")
async def test_atomic_run_claim_has_one_winner(db_session) -> None:  # type: ignore[no-untyped-def]
    instance, source = await _instance_source(db_session)
    run = await ConnectorRunService(db_session).create_pending(
        connector_instance_id=instance.id,
        source_id=source.id,
        platform_account_id=None,
        mode="feed",
        requested_limit=10,
    )
    run_id = run.id

    async def claim_once() -> str:
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            try:
                await ConnectorRunService(session).claim(run_id=run_id)
            except InvalidStateTransitionError:
                return "conflict"
            return "claimed"

    outcomes = await asyncio.gather(claim_once(), claim_once())
    assert sorted(outcomes) == ["claimed", "conflict"]

    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        await ConnectorRunService(session).finalize(
            run_id=run_id,
            target_status=ConnectorRunStatus.SUCCEEDED,
        )
    async with session_factory() as session:
        with pytest.raises(InvalidStateTransitionError):
            await ConnectorRunService(session).claim(run_id=run_id)


@pytest.mark.usefixtures("clean_database")
async def test_concurrent_budget_reservation_cannot_exceed_limit(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    instance, source = await _instance_source(db_session)
    await CollectionBudgetService(db_session).create(
        scope_type="connector",
        scope_key=str(instance.id),
        values={
            "max_runs_per_day": 10,
            "max_items_per_run": 10,
            "max_items_per_day": 10,
            "max_comments_per_run": 0,
            "max_comments_per_day": 0,
            "max_concurrency": 1,
            "timezone": "UTC",
            "enabled": True,
        },
        actor="admin",
    )

    async def reserve_once() -> tuple[str, tuple[BudgetReservation, ...] | None]:
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            try:
                reservation = await CollectionBudgetService(session).reserve(
                    platform="rss",
                    connector_instance_id=instance.id,
                    connector_type="rss",
                    platform_account_id=None,
                    source_id=source.id,
                    requested_items=10,
                    actor="tester",
                )
            except BudgetExceededError:
                return "rejected", None
            return "reserved", reservation

    first, second = await asyncio.gather(reserve_once(), reserve_once())
    assert sorted([first[0], second[0]]) == ["rejected", "reserved"]
    winner = first[1] if first[0] == "reserved" else second[1]
    assert winner is not None

    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        await CollectionBudgetService(session).settle(
            reservations=winner,
            actual_items=10,
            completed=True,
        )

    async with session_factory() as session:
        with pytest.raises(BudgetExceededError, match="当日条目预算"):
            await CollectionBudgetService(session).reserve(
                platform="rss",
                connector_instance_id=instance.id,
                connector_type="rss",
                platform_account_id=None,
                source_id=source.id,
                requested_items=1,
                actor="tester",
            )
