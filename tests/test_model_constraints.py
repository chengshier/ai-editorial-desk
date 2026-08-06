from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorInstance,
    PlatformAccount,
    PlatformRiskEvent,
)
from packages.risk_guard.models import AccountStatus, RiskAction


async def create_instance(session: AsyncSession) -> ConnectorInstance:
    definition = ConnectorDefinition(
        connector_type="mediacrawler",
        platform="weibo",
        display_name="微博",
        capabilities={"search": True},
        config_schema={"type": "object"},
        ui_schema={},
        implementation_version="1.0.0",
    )
    instance = ConnectorInstance(definition=definition, name="weibo-primary")
    session.add(instance)
    await session.flush()
    return instance


@pytest.mark.asyncio
async def test_definition_type_and_platform_are_unique(db_session: AsyncSession) -> None:
    first = ConnectorDefinition(
        connector_type="rss",
        platform="rss",
        display_name="RSS",
        capabilities={},
        config_schema={},
        ui_schema={},
        implementation_version="1.0.0",
    )
    duplicate = ConnectorDefinition(
        connector_type="rss",
        platform="rss",
        display_name="RSS duplicate",
        capabilities={},
        config_schema={},
        ui_schema={},
        implementation_version="1.0.1",
    )
    db_session.add(first)
    await db_session.commit()
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_checkpoint_scope_is_unique_even_without_account(
    db_session: AsyncSession,
) -> None:
    instance = await create_instance(db_session)
    db_session.add_all(
        [
            ConnectorCheckpoint(
                connector_instance_id=instance.id,
                platform_account_id=None,
                mode="search",
                scope_key="keyword:ai",
            ),
            ConnectorCheckpoint(
                connector_instance_id=instance.id,
                platform_account_id=None,
                mode="search",
                scope_key="keyword:ai",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_platform_account_rejects_negative_counters(db_session: AsyncSession) -> None:
    instance = await create_instance(db_session)
    db_session.add(
        PlatformAccount(
            connector_instance_id=instance.id,
            platform="weibo",
            display_name="test account",
            account_identifier="test-account",
            status=AccountStatus.HEALTHY,
            consecutive_failures=-1,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_timestamps_are_normalized_to_utc(db_session: AsyncSession) -> None:
    instance = await create_instance(db_session)
    source_time = datetime(2026, 8, 6, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    account = PlatformAccount(
        connector_instance_id=instance.id,
        platform="weibo",
        display_name="UTC account",
        account_identifier="utc-account",
        status=AccountStatus.HEALTHY,
        last_success_at=source_time,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    assert account.last_success_at == datetime(2026, 8, 6, 4, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_risk_context_redacts_credentials_before_storage(
    db_session: AsyncSession,
) -> None:
    instance = await create_instance(db_session)
    event = PlatformRiskEvent(
        connector_instance_id=instance.id,
        platform="weibo",
        risk_type="permission_denied",
        risk_level="high",
        message="platform rejected request",
        action_taken=RiskAction.PAUSE_ACCOUNT,
        retryable=False,
        request_context={
            "url": "https://example.invalid/resource",
            "headers": {"Authorization": "Bearer secret", "Cookie": "sid=secret"},
        },
        response_context={"status": 403, "token": "secret-token"},
    )
    db_session.add(event)
    await db_session.commit()
    event_id = event.id
    db_session.expunge_all()

    stored = (
        await db_session.execute(
            select(PlatformRiskEvent).where(PlatformRiskEvent.id == event_id)
        )
    ).scalar_one()

    assert stored.request_context["headers"]["Authorization"] == "[REDACTED]"
    assert stored.request_context["headers"]["Cookie"] == "[REDACTED]"
    assert stored.response_context["token"] == "[REDACTED]"

    raw_text = (
        await db_session.execute(
            text(
                "SELECT request_context::text || response_context::text "
                "FROM platform_risk_events WHERE id = :id"
            ),
            {"id": event_id},
        )
    ).scalar_one()
    assert "secret" not in raw_text
