from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from packages.connector_management.exceptions import InvalidStateTransitionError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
    PlatformAccountService,
)
from packages.database.models import ConfigurationChangeLog, ConnectorDefinition
from packages.risk_guard.models import AccountStatus

CREDENTIAL_REFERENCE_A = "secret://weibo/account-1"
CREDENTIAL_REFERENCE_B = "secret://weibo/account-2"
BROWSER_PROFILE_REFERENCE_A = "profile://weibo/account-1"
BROWSER_PROFILE_REFERENCE_B = "profile://weibo/account-2"


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
        credential_ref=CREDENTIAL_REFERENCE_A,
        browser_profile_ref=BROWSER_PROFILE_REFERENCE_A,
        actor="admin",
    )


async def _update_audits(db_session, account_id):  # type: ignore[no-untyped-def]
    statement = (
        select(ConfigurationChangeLog)
        .where(
            ConfigurationChangeLog.entity_type == "platform_account",
            ConfigurationChangeLog.entity_id == account_id,
            ConfigurationChangeLog.action == "update",
        )
        .order_by(ConfigurationChangeLog.created_at.asc())
    )
    return list((await db_session.scalars(statement)).all())


@pytest.mark.usefixtures("clean_database")
async def test_account_credential_references_and_audit_are_safe(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    assert account.credential_ref == CREDENTIAL_REFERENCE_A
    log = await db_session.scalar(
        select(ConfigurationChangeLog).where(
            ConfigurationChangeLog.entity_type == "platform_account"
        )
    )
    assert log is not None
    assert log.after_data["has_credential_reference"] is True
    assert CREDENTIAL_REFERENCE_A not in str(log.after_data)


@pytest.mark.usefixtures("clean_database")
async def test_credential_reference_a_to_b_updates_actor_and_audit(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    account_id = account.id

    updated = await PlatformAccountService(db_session).update(
        account_id=account_id,
        changes={"credential_ref": CREDENTIAL_REFERENCE_B},
        actor="credential-editor",
    )
    await db_session.refresh(updated)

    assert updated.credential_ref == CREDENTIAL_REFERENCE_B
    assert updated.updated_by == "credential-editor"
    audits = await _update_audits(db_session, account_id)
    assert len(audits) == 1
    assert audits[0].after_data["credential_reference_changed"] is True
    assert audits[0].after_data["has_credential_reference"] is True
    audit_text = f"{audits[0].before_data}{audits[0].after_data}"
    assert CREDENTIAL_REFERENCE_A not in audit_text
    assert CREDENTIAL_REFERENCE_B not in audit_text


@pytest.mark.usefixtures("clean_database")
async def test_browser_profile_reference_a_to_b_is_audited_without_leak(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    account_id = account.id

    updated = await PlatformAccountService(db_session).update(
        account_id=account_id,
        changes={"browser_profile_ref": BROWSER_PROFILE_REFERENCE_B},
        actor="profile-editor",
    )
    await db_session.refresh(updated)

    assert updated.browser_profile_ref == BROWSER_PROFILE_REFERENCE_B
    assert updated.updated_by == "profile-editor"
    audits = await _update_audits(db_session, account_id)
    assert len(audits) == 1
    assert audits[0].after_data["browser_profile_reference_changed"] is True
    assert audits[0].after_data["browser_profile_configured"] is True
    audit_text = f"{audits[0].before_data}{audits[0].after_data}"
    assert BROWSER_PROFILE_REFERENCE_A not in audit_text
    assert BROWSER_PROFILE_REFERENCE_B not in audit_text


@pytest.mark.usefixtures("clean_database")
async def test_same_references_are_idempotent_and_keep_updated_by(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    account_id = account.id
    original_updated_by = account.updated_by

    updated = await PlatformAccountService(db_session).update(
        account_id=account_id,
        changes={
            "credential_ref": CREDENTIAL_REFERENCE_A,
            "browser_profile_ref": BROWSER_PROFILE_REFERENCE_A,
        },
        actor="noop-editor",
    )

    update_count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(ConfigurationChangeLog)
            .where(
                ConfigurationChangeLog.entity_id == account_id,
                ConfigurationChangeLog.action == "update",
            )
        )
        or 0
    )
    assert updated.updated_by == original_updated_by
    assert update_count == 0


@pytest.mark.usefixtures("clean_database")
async def test_account_manual_transition_rules(db_session) -> None:  # type: ignore[no-untyped-def]
    account = await _account(db_session)
    account_id = account.id
    service = PlatformAccountService(db_session)
    restricted = await service.transition_status(
        account_id=account_id,
        target_status=AccountStatus.RESTRICTED,
        reason="平台明确限制该测试账号",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    assert restricted.manual_review_required is True
    with pytest.raises(InvalidStateTransitionError):
        await service.transition_status(
            account_id=account_id,
            target_status=AccountStatus.HEALTHY,
            reason="尝试直接恢复",
            cooldown_until=None,
            override_cooldown=False,
            actor="reviewer",
        )
    reviewed = await service.transition_status(
        account_id=account_id,
        target_status=AccountStatus.REVIEW_REQUIRED,
        reason="已进入人工复核流程",
        cooldown_until=None,
        override_cooldown=False,
        actor="reviewer",
    )
    assert reviewed.status is AccountStatus.REVIEW_REQUIRED
    healthy = await service.transition_status(
        account_id=account_id,
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
    account_id = account.id
    service = PlatformAccountService(db_session)
    until = datetime.now(UTC) + timedelta(hours=1)
    await service.transition_status(
        account_id=account_id,
        target_status=AccountStatus.COOLDOWN,
        reason="连续失败后人工设置冷却",
        cooldown_until=until,
        override_cooldown=False,
        actor="reviewer",
    )
    with pytest.raises(InvalidStateTransitionError):
        await service.transition_status(
            account_id=account_id,
            target_status=AccountStatus.HEALTHY,
            reason="冷却未结束",
            cooldown_until=None,
            override_cooldown=False,
            actor="reviewer",
        )
    healthy = await service.transition_status(
        account_id=account_id,
        target_status=AccountStatus.HEALTHY,
        reason="人工核验后提前解除冷却",
        cooldown_until=None,
        override_cooldown=True,
        actor="reviewer",
    )
    assert healthy.status is AccountStatus.HEALTHY
