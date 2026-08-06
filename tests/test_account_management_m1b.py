from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.connector_management.exceptions import InvalidStateTransitionError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.database.models import ConfigurationChangeLog, ConnectorDefinition
from packages.risk_guard.models import AccountStatus


async def _account(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "weibo")
    )
    assert definition is not None
    await db_session.commit()
    instance = await ConnectorInstanceService(db_session).create(
        definition_id=definition.id,
        name="微博实例",
        config={"modes": ["search"]},
        schedule_config={},
        actor="admin",
    )
    return await PlatformAccountService(db_session).create(
        connector_instance_id=instance.id,
        platform="weibo",
        display_name="测试账号",
        account_identifier="account-1",
        credential_ref="secret://weibo/account-1",
        browser_profile_ref="profile://weibo/account-1",
        actor="admin",
    )


@pytest.mark.usefixtures("clean_database")
async def test_account_credential_references_and_audit_are_safe(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    assert account.credential_ref == "secret://weibo/account-1"
    log = await db_session.scalar(
        select(ConfigurationChangeLog).where(
            ConfigurationChangeLog.entity_type == "platform_account"
        )
    )
    assert log is not None
    assert log.after_data["credential_configured"] is True
    assert "secret://" not in str(log.after_data)


@pytest.mark.usefixtures("clean_database")
async def test_account_manual_transition_rules(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    service = PlatformAccountService(db_session)
    restricted = await service.transition_status(
        account_id=account.id,
        target_status=AccountStatus.RESTRICTED,
        reason="平台明确限制该测试账号",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    assert restricted.manual_review_required is True
    with pytest.raises(InvalidStateTransitionError):
        await service.transition_status(
            account_id=account.id,
            target_status=AccountStatus.HEALTHY,
            reason="尝试直接恢复",
            cooldown_until=None,
            override_cooldown=False,
            actor="reviewer",
        )
    reviewed = await service.transition_status(
        account_id=account.id,
        target_status=AccountStatus.REVIEW_REQUIRED,
        reason="已进入人工复核流程",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    assert reviewed.status is AccountStatus.REVIEW_REQUIRED
    healthy = await service.transition_status(
        account_id=account.id,
        target_status=AccountStatus.HEALTHY,
        reason="已人工登录平台确认账号正常",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    assert healthy.status is AccountStatus.HEALTHY


@pytest.mark.usefixtures("clean_database")
async def test_active_cooldown_requires_explicit_override(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    service = PlatformAccountService(db_session)
    until = datetime.now(UTC) + timedelta(hours=1)
    await service.transition_status(
        account_id=account.id,
        target_status=AccountStatus.COOLDOWN,
        reason="连续失败后人工设置冷却",
        cooldown_until=until,
        override_cooldown=False,
        actor="reviewer",
    )
    with pytest.raises(InvalidStateTransitionError):
        await service.transition_status(
            account_id=account.id,
            target_status=AccountStatus.HEALTHY,
            reason="冷却未结束",
            cooldown_until=None,
            override_cooldown=False,
            actor="reviewer",
        )
    healthy = await service.transition_status(
        account_id=account.id,
        target_status=AccountStatus.HEALTHY,
        reason="人工核验后提前解除冷却",
        cooldown_until=None,
        override_cooldown=True,
        actor="reviewer",
    )
    assert healthy.status is AccountStatus.HEALTHY
