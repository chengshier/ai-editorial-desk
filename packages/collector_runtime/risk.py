from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.collector_runtime.exceptions import PreflightRejectedError
from packages.connector_management.repositories import AuditLogRepository
from packages.connectors.http import ConnectorFetchError
from packages.database.models import (
    ConnectorRun,
    ConnectorRunStatus,
    PlatformAccount,
    PlatformRiskEvent,
)
from packages.database.types import sanitize_context
from packages.risk_guard.models import AccountStatus, PlatformRiskError, RiskAction


class RuntimeRiskGuard:
    """Apply account gates and persist real platform-risk failures."""

    @staticmethod
    def before_run(account: PlatformAccount | None) -> None:
        if account is None:
            return
        if account.manual_review_required:
            raise PreflightRejectedError("账号需要人工复核，不能启动采集")
        if account.status in {
            AccountStatus.REVIEW_REQUIRED,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }:
            raise PreflightRejectedError("账号状态不允许启动采集")
        if (
            account.status is AccountStatus.COOLDOWN
            and account.cooldown_until is not None
            and account.cooldown_until > datetime.now(UTC)
        ):
            raise PreflightRejectedError("账号仍处于冷却期")

    @staticmethod
    def is_ordinary_network_error(error: BaseException) -> bool:
        return isinstance(error, ConnectorFetchError)

    async def handle_platform_risk(
        self,
        *,
        session: AsyncSession,
        run_id: UUID,
        connector_instance_id: UUID,
        platform_account_id: UUID | None,
        platform: str,
        error: PlatformRiskError,
        actor: str,
        metadata: dict[str, Any] | None = None,
        raw_error_code: str | None = None,
        standard_error_code: str = "platform_risk",
        risk_level: str = "high",
        retryable: bool = False,
        response_context: dict[str, Any] | None = None,
        collected_count: int = 0,
        inserted_count: int = 0,
        duplicate_count: int = 0,
        failed_count: int = 1,
        checkpoint_after: dict[str, Any] | None = None,
    ) -> None:
        event = error.event
        now = datetime.now(UTC)
        async with session.begin():
            session.add(
                PlatformRiskEvent(
                    connector_instance_id=connector_instance_id,
                    platform_account_id=platform_account_id,
                    connector_run_id=run_id,
                    platform=platform,
                    risk_type="platform_restriction",
                    risk_level=risk_level,
                    raw_error_code=raw_error_code or event.code,
                    standard_error_code=standard_error_code,
                    message=event.message,
                    action_taken=event.action,
                    retryable=retryable,
                    request_context={},
                    response_context=sanitize_context(response_context or {}),
                    manual_review_required=True,
                )
            )
            if platform_account_id is not None:
                account = await session.get(PlatformAccount, platform_account_id)
                if account is not None:
                    target_status = (
                        AccountStatus.RESTRICTED
                        if event.action is RiskAction.PAUSE_PLATFORM
                        else AccountStatus.REVIEW_REQUIRED
                    )
                    before = {
                        "status": account.status.value,
                        "manual_review_required": account.manual_review_required,
                    }
                    account.status = target_status
                    account.manual_review_required = True
                    account.last_warning_at = now
                    account.last_warning_code = standard_error_code
                    account.updated_by = actor
                    AuditLogRepository(session).add(
                        entity_type="platform_account",
                        entity_id=account.id,
                        action="runtime_risk_transition",
                        actor=actor,
                        before_data=before,
                        after_data={
                            "status": target_status.value,
                            "manual_review_required": True,
                            "risk_code": standard_error_code,
                        },
                    )
            run = await session.get(ConnectorRun, run_id)
            if run is not None and run.status is ConnectorRunStatus.RUNNING:
                run.status = ConnectorRunStatus.PAUSED_RISK
                run.finished_at = now
                run.progress_updated_at = now
                run.error_code = standard_error_code
                run.error_message = event.message
                run.collected_count = collected_count
                run.inserted_count = inserted_count
                run.duplicate_count = duplicate_count
                run.failed_count = failed_count
                run.checkpoint_after = checkpoint_after
                run.run_metadata = sanitize_context(
                    {
                        **(metadata or run.run_metadata),
                        "risk_action": event.action.value,
                        "risk_disposition": event.disposition.value,
                    }
                )
