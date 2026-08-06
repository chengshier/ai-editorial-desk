from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    InvalidStateTransitionError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import (
    AuditLogRepository,
    ConnectorInstanceRepository,
    Page,
    PlatformAccountRepository,
)
from packages.database.models import PlatformAccount
from packages.risk_guard.models import AccountStatus

ALLOWED_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.HEALTHY: frozenset(
        {
            AccountStatus.WARNING,
            AccountStatus.COOLDOWN,
            AccountStatus.REVIEW_REQUIRED,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }
    ),
    AccountStatus.WARNING: frozenset(
        {
            AccountStatus.HEALTHY,
            AccountStatus.COOLDOWN,
            AccountStatus.REVIEW_REQUIRED,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }
    ),
    AccountStatus.COOLDOWN: frozenset(
        {
            AccountStatus.HEALTHY,
            AccountStatus.WARNING,
            AccountStatus.REVIEW_REQUIRED,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }
    ),
    AccountStatus.REVIEW_REQUIRED: frozenset(
        {
            AccountStatus.HEALTHY,
            AccountStatus.COOLDOWN,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }
    ),
    AccountStatus.RESTRICTED: frozenset(
        {AccountStatus.REVIEW_REQUIRED, AccountStatus.DISABLED}
    ),
    AccountStatus.DISABLED: frozenset({AccountStatus.REVIEW_REQUIRED}),
}


def _account_snapshot(account: PlatformAccount) -> dict[str, Any]:
    return {
        "connector_instance_id": str(account.connector_instance_id),
        "platform": account.platform,
        "display_name": account.display_name,
        "account_identifier": account.account_identifier,
        "has_credential_reference": bool(account.credential_ref),
        "browser_profile_configured": bool(account.browser_profile_ref),
        "status": account.status.value,
        "risk_level": account.risk_level,
        "cooldown_until": account.cooldown_until.isoformat()
        if account.cooldown_until
        else None,
        "manual_review_required": account.manual_review_required,
        "updated_by": account.updated_by,
    }


class PlatformAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PlatformAccountRepository(session)
        self.instances = ConnectorInstanceRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(
        self,
        *,
        connector_instance_id: UUID,
        platform: str,
        display_name: str,
        account_identifier: str,
        credential_ref: str | None,
        browser_profile_ref: str | None,
        actor: str,
    ) -> PlatformAccount:
        async with self.session.begin():
            instance = await self.instances.get(connector_instance_id)
            if instance is None:
                raise ResourceNotFoundError("连接器实例不存在")
            if instance.status == "archived":
                raise ConflictError("不能为已归档实例创建账号")
            if instance.definition.platform != platform:
                raise BusinessValidationError("账号平台必须与连接器定义平台一致")
            duplicate = await self.repository.get_by_identifier(
                connector_instance_id, platform, account_identifier.strip()
            )
            if duplicate is not None:
                raise ConflictError("该平台账号标识已存在")
            account = PlatformAccount(
                connector_instance_id=connector_instance_id,
                platform=platform,
                display_name=display_name.strip(),
                account_identifier=account_identifier.strip(),
                credential_ref=credential_ref,
                browser_profile_ref=browser_profile_ref,
                status=AccountStatus.HEALTHY,
                updated_by=actor,
            )
            self.repository.add(account)
            await self.session.flush()
            self.audit.add(
                entity_type="platform_account",
                entity_id=account.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_account_snapshot(account),
            )
        return account

    async def get(self, account_id: UUID) -> PlatformAccount:
        account = await self.repository.get(account_id)
        if account is None:
            raise ResourceNotFoundError("平台账号不存在")
        return account

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        connector_instance_id: UUID | None,
        platform: str | None,
        status: AccountStatus | None,
        manual_review_required: bool | None,
    ) -> Page[PlatformAccount]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            connector_instance_id=connector_instance_id,
            platform=platform,
            status=status,
            manual_review_required=manual_review_required,
        )

    async def update(
        self,
        *,
        account_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> PlatformAccount:
        async with self.session.begin():
            account = await self.repository.get(account_id)
            if account is None:
                raise ResourceNotFoundError("平台账号不存在")

            before = _account_snapshot(account)
            actual_changed = False
            credential_reference_changed = False
            browser_profile_reference_changed = False

            if "display_name" in changes:
                display_name = str(changes["display_name"]).strip()
                if display_name != account.display_name:
                    account.display_name = display_name
                    actual_changed = True

            if "credential_ref" in changes:
                credential_ref = cast(str | None, changes["credential_ref"])
                if credential_ref != account.credential_ref:
                    account.credential_ref = credential_ref
                    credential_reference_changed = True
                    actual_changed = True

            if "browser_profile_ref" in changes:
                browser_profile_ref = cast(str | None, changes["browser_profile_ref"])
                if browser_profile_ref != account.browser_profile_ref:
                    account.browser_profile_ref = browser_profile_ref
                    browser_profile_reference_changed = True
                    actual_changed = True

            if not actual_changed:
                return account

            account.updated_by = actor
            after = _account_snapshot(account)
            if credential_reference_changed:
                after["credential_reference_changed"] = True
            if browser_profile_reference_changed:
                after["browser_profile_reference_changed"] = True

            self.audit.add(
                entity_type="platform_account",
                entity_id=account.id,
                action="update",
                actor=actor,
                before_data=before,
                after_data=after,
            )
        return account

    async def transition_status(
        self,
        *,
        account_id: UUID,
        target_status: AccountStatus,
        reason: str,
        cooldown_until: datetime | None,
        override_cooldown: bool,
        actor: str,
    ) -> PlatformAccount:
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise BusinessValidationError("人工状态变更必须填写明确原因")
        async with self.session.begin():
            account = await self.repository.get(account_id)
            if account is None:
                raise ResourceNotFoundError("平台账号不存在")
            if target_status == account.status:
                return account
            if target_status not in ALLOWED_TRANSITIONS[account.status]:
                raise InvalidStateTransitionError(
                    f"账号状态不能从 {account.status.value} 直接变为 {target_status.value}"
                )
            now = datetime.now(UTC)
            if target_status is AccountStatus.COOLDOWN:
                if cooldown_until is None:
                    raise BusinessValidationError("设置冷却状态时必须提供 cooldown_until")
                if cooldown_until.tzinfo is None or cooldown_until.utcoffset() is None:
                    raise BusinessValidationError("cooldown_until 必须包含时区")
                if cooldown_until <= now:
                    raise BusinessValidationError("cooldown_until 必须晚于当前时间")
            if (
                account.status is AccountStatus.COOLDOWN
                and target_status is AccountStatus.HEALTHY
                and account.cooldown_until is not None
                and account.cooldown_until > now
                and not override_cooldown
            ):
                raise InvalidStateTransitionError(
                    "冷却尚未结束，恢复健康必须明确设置人工覆盖"
                )

            before = _account_snapshot(account)
            account.status = target_status
            account.cooldown_until = (
                cooldown_until if target_status is AccountStatus.COOLDOWN else None
            )
            account.manual_review_required = target_status in {
                AccountStatus.REVIEW_REQUIRED,
                AccountStatus.RESTRICTED,
            }
            account.updated_by = actor
            self.audit.add(
                entity_type="platform_account",
                entity_id=account.id,
                action="status_transition",
                actor=actor,
                before_data=before,
                after_data={
                    **_account_snapshot(account),
                    "transition_reason": normalized_reason,
                    "override_cooldown": override_cooldown,
                },
            )
        return account
