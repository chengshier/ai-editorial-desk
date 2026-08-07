from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from packages.collector_runtime.budget_types import BudgetReservation
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.context import MAX_TEST_RUN_LIMIT, PreflightContext
from packages.collector_runtime.exceptions import (
    ConnectorImplementationUnavailableError,
    PreflightRejectedError,
)
from packages.collector_runtime.protocols import CollectionTask
from packages.collector_runtime.risk import RuntimeRiskGuard
from packages.connector_management.services import (
    ConnectorCheckpointService,
    ConnectorRunService,
)
from packages.connectors import ConnectorRegistry, RawSignal
from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.account_profile import (
    AccountExecutionBlocked,
    MediaCrawlerAccountContext,
)
from packages.connectors.mediacrawler_adapter.protocol import LoginState
from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunTriggerType,
    PlatformAccount,
    Source,
)

logger = logging.getLogger(__name__)


class CollectorRuntimeSupport:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ConnectorRegistry,
        risk_guard: RuntimeRiskGuard | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.risk_guard = risk_guard or RuntimeRiskGuard()

    async def preflight(self, task: CollectionTask) -> PreflightContext:
        if task.requested_limit < 1 or task.requested_limit > MAX_TEST_RUN_LIMIT:
            raise PreflightRejectedError("requested_limit 超出受控测试运行范围")
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConnectorInstance)
                .options(selectinload(ConnectorInstance.definition))
                .where(ConnectorInstance.id == task.connector_instance_id)
            )
            instance = result.scalar_one_or_none()
            if instance is None:
                raise PreflightRejectedError("连接器实例不存在")
            definition = instance.definition
            source = await session.get(Source, task.source_id)
            if source is None or source.connector_instance_id != instance.id:
                raise PreflightRejectedError("来源不存在或不属于该实例")
            account = (
                await session.get(PlatformAccount, task.platform_account_id)
                if task.platform_account_id is not None
                else None
            )
            if task.platform_account_id is not None and account is None:
                raise PreflightRejectedError("平台账号不存在")
            if account is not None and account.connector_instance_id != instance.id:
                raise PreflightRejectedError("平台账号不属于该连接器实例")
            if instance.status == "archived" or not instance.enabled:
                raise PreflightRejectedError("连接器实例未启用或已归档")
            if not definition.is_enabled:
                raise PreflightRejectedError("连接器定义已停用")
            if source.status == "archived" or not source.enabled:
                raise PreflightRejectedError("来源未启用或已归档")
            if source.source_type != definition.connector_type:
                raise PreflightRejectedError("来源类型与连接器定义不一致")
            if not self.registry.has(definition.connector_type):
                raise ConnectorImplementationUnavailableError(
                    "该连接器只有 Definition，尚无可运行实现"
                )
            if not bool(definition.capabilities.get(task.mode)):
                raise PreflightRejectedError("连接器不支持请求的运行模式")
            allowed_modes = definition.capabilities.get("allowed_modes")
            if isinstance(allowed_modes, list) and task.mode not in allowed_modes:
                raise PreflightRejectedError("平台当前不允许请求的运行模式")
            if bool(definition.capabilities.get("requires_account")) and account is None:
                raise PreflightRejectedError("该连接器运行需要平台账号")
            self.risk_guard.before_run(account)
            runtime_context = self._runtime_account_context(
                definition.connector_type,
                account,
            )
            return PreflightContext(
                instance=instance,
                definition=definition,
                source=source,
                account=account,
                runtime_context=runtime_context,
            )

    @staticmethod
    def _runtime_account_context(
        connector_type: str,
        account: PlatformAccount | None,
    ) -> object | None:
        if connector_type != "mediacrawler" or account is None:
            return None
        context = MediaCrawlerAccountContext(
            platform_account_id=account.id,
            account_identifier=account.account_identifier,
            credential_ref=account.credential_ref,
            browser_profile_ref=account.browser_profile_ref,
            account_status=account.status,
            cooldown_until=account.cooldown_until,
            manual_review_required=account.manual_review_required,
            login_state=LoginState.UNKNOWN,
        )
        try:
            context.ensure_runnable()
        except AccountExecutionBlocked as exc:
            raise PreflightRejectedError(str(exc)) from exc
        return context

    async def load_checkpoint(
        self,
        task: CollectionTask,
        context: PreflightContext,
    ) -> ConnectorCheckpoint | None:
        if not bool(context.definition.capabilities.get("supports_checkpoint")):
            return None
        async with self.session_factory() as session:
            checkpoint = await ConnectorCheckpointService(session).get_or_create(
                connector_instance_id=context.instance.id,
                source_id=context.source.id,
                platform_account_id=task.platform_account_id,
                mode=task.mode,
                scope_key=context.source.scope_key,
            )
        if (
            task.checkpoint_version is not None
            and checkpoint.version != task.checkpoint_version
        ):
            raise PreflightRejectedError("expected_checkpoint_version 不匹配")
        return checkpoint

    async def create_run(
        self,
        task: CollectionTask,
        context: PreflightContext,
        checkpoint: ConnectorCheckpoint | None,
    ) -> ConnectorRun:
        async with self.session_factory() as session:
            return await ConnectorRunService(session).create_pending(
                connector_instance_id=context.instance.id,
                source_id=context.source.id,
                platform_account_id=task.platform_account_id,
                mode=task.mode,
                requested_limit=task.requested_limit,
                checkpoint_before=(
                    dict(checkpoint.checkpoint_data)
                    if checkpoint is not None
                    else None
                ),
                metadata={"task": task.to_dict()},
                trigger_type=ConnectorRunTriggerType(task.trigger_type.value),
                parent_run_id=task.parent_run_id,
                retry_count=task.retry_count,
            )

    async def advance_checkpoint(
        self,
        *,
        checkpoint_id: UUID,
        expected_version: int,
        checkpoint_data: dict[str, Any],
        signals: tuple[RawSignal, ...],
    ) -> None:
        published = [
            item.published_at for item in signals if item.published_at is not None
        ]
        signal_last_published_at = max(published, default=None)
        signal_last_external_id = next(
            (
                item.external_id
                for item in reversed(signals)
                if item.external_id is not None
            ),
            None,
        )
        candidate_published_at = self._checkpoint_datetime(
            checkpoint_data.get("latest_published_at")
        )
        candidate_external_id = checkpoint_data.get("last_external_id")
        last_published_at = candidate_published_at or signal_last_published_at
        last_external_id = (
            candidate_external_id
            if isinstance(candidate_external_id, str) and candidate_external_id
            else signal_last_external_id
        )
        cursor_value = checkpoint_data.get("cursor")
        cursor = dict(cursor_value) if isinstance(cursor_value, dict) else None
        page = checkpoint_data.get("page")
        if cursor is None and isinstance(page, int) and page >= 1:
            cursor = {"page": page}
        async with self.session_factory() as session:
            await ConnectorCheckpointService(session).update(
                checkpoint_id=checkpoint_id,
                expected_version=expected_version,
                cursor=cursor,
                watermark=(
                    last_published_at.isoformat()
                    if last_published_at is not None
                    else None
                ),
                last_external_id=last_external_id,
                last_published_at=last_published_at,
                checkpoint_data=checkpoint_data,
            )

    @staticmethod
    def _checkpoint_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed

    async def settle(
        self,
        reservations: tuple[BudgetReservation, ...],
        *,
        actual_items: int,
        actual_comments: int = 0,
        completed: bool,
    ) -> None:
        if not reservations:
            return
        async with self.session_factory() as session:
            await CollectionBudgetService(session).settle(
                reservations=reservations,
                actual_items=actual_items,
                actual_comments=actual_comments,
                completed=completed,
            )

    @staticmethod
    def safe_error_message(error: BaseException) -> str:
        if isinstance(error, ConnectorFetchError):
            return error.safe_message
        if isinstance(error, (ValueError, PreflightRejectedError)):
            return str(error)
        return "采集执行失败"

    @staticmethod
    def log_result(
        *,
        context: PreflightContext,
        run: ConnectorRun,
        failed_count: int,
        latency: float,
        risk_action: str | None,
    ) -> None:
        logger.info(
            "collector_run_completed",
            extra={
                "run_id": str(run.id),
                "connector_instance_id": str(context.instance.id),
                "source_id": str(context.source.id),
                "connector_type": context.definition.connector_type,
                "platform": context.definition.platform,
                "mode": run.mode,
                "status": run.status.value,
                "collected_count": run.collected_count,
                "inserted_count": run.inserted_count,
                "duplicate_count": run.duplicate_count,
                "failed_count": failed_count,
                "latency": latency,
                "error_code": run.error_code,
                "risk_action": risk_action,
            },
        )
