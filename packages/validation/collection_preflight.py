from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from packages.collector_runtime.budget_repository import CollectionBudgetRepository
from packages.collector_runtime.risk import RuntimeRiskGuard
from packages.common.config import get_settings
from packages.connectors.implementations import implementation_registry
from packages.connectors.mediacrawler_adapter.runner import SAFE_ENV_NAMES
from packages.connectors.mediacrawler_adapter.smoke import LOGIN_STATE_MARKERS
from packages.database.models import (
    CollectionBudgetUsage,
    ConnectorCheckpoint,
    ConnectorInstance,
    PlatformAccount,
    Source,
)

SAFE_REAL_COLLECTION_LIMIT = 5
EXPECTED_CDP_HOST = "127.0.0.1"
EXPECTED_CDP_PORT = 9222
REPO_ROOT = Path(__file__).resolve().parents[2]
LOGIN_HELPER_ENTRYPOINT = (
    REPO_ROOT
    / "packages"
    / "connectors"
    / "mediacrawler_adapter"
    / "login_preflight_entry"
    / "main.py"
)
_PLATFORM_ORIGINS = {
    "bilibili": "https://www.bilibili.com",
    "zhihu": "https://www.zhihu.com",
    "weibo": "https://m.weibo.cn",
}


@dataclass(frozen=True, slots=True)
class CollectionPreflightCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class CollectionPreflightReport:
    status: str
    platform: str
    mode: str
    requested_limit: int
    comment_limit: int
    initiates_platform_request: bool = False
    uses_local_cdp: bool = False
    account_label: str | None = None
    checkpoint_summary: dict[str, str | int | None] = field(default_factory=dict)
    budget_summary: dict[str, int | str | None] = field(default_factory=dict)
    checks: tuple[CollectionPreflightCheck, ...] = ()


class CollectionPreflightService:
    """Read-only preparation check for one low-volume real collection request.

    This service never creates ConnectorRun / Checkpoint / budget usage rows and never
    navigates to a platform. For MediaCrawler it may connect to the already-running
    localhost CDP browser and read login-state marker presence through the dedicated
    helper process.
    """

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    async def run(
        self,
        *,
        source_id: UUID,
        platform_account_id: UUID | None,
        requested_limit: int,
        comment_limit: int,
    ) -> CollectionPreflightReport:
        checks: list[CollectionPreflightCheck] = []
        checkpoint_summary: dict[str, str | int | None] = {}
        budget_summary: dict[str, int | str | None] = {}
        platform = "unknown"
        mode = "unknown"
        account_label: str | None = None
        uses_local_cdp = False

        if requested_limit < 1 or requested_limit > SAFE_REAL_COLLECTION_LIMIT:
            checks.append(
                CollectionPreflightCheck(
                    "low_volume_limit",
                    "BLOCKED",
                    f"低量真实采集单次仅允许 1-{SAFE_REAL_COLLECTION_LIMIT} 条；正式采集量请通过采集预算配置。",
                )
            )
        else:
            checks.append(
                CollectionPreflightCheck(
                    "low_volume_limit",
                    "READY",
                    f"本次低量真实采集上限为 {requested_limit} 条。",
                )
            )

        async with self.session_factory() as session:
            result = await session.execute(
                select(ConnectorInstance)
                .options(selectinload(ConnectorInstance.definition))
                .join(Source, Source.connector_instance_id == ConnectorInstance.id)
                .where(Source.id == source_id)
            )
            instance = result.scalar_one_or_none()
            source = await session.get(Source, source_id)
            if instance is None or source is None:
                checks.append(CollectionPreflightCheck("source", "BLOCKED", "信源不存在或未绑定连接器实例。"))
                return self._report(checks, platform, mode, requested_limit, comment_limit)

            definition = instance.definition
            platform = definition.platform
            mode = source.mode
            checks.extend(self._configuration_checks(instance, definition, source))

            account = await self._load_account(session, instance.id, platform_account_id)
            if account is not None:
                account_label = account.display_name
            checks.extend(self._account_checks(definition, instance.id, account, platform_account_id))

            if definition.connector_type == "mediacrawler":
                uses_local_cdp = True
                checks.extend(self._runtime_environment_checks(account))

            checkpoint_summary = await self._checkpoint_summary(
                session=session,
                source=source,
                account_id=platform_account_id,
            )
            checks.append(
                CollectionPreflightCheck(
                    "checkpoint",
                    "READY",
                    self._checkpoint_message(checkpoint_summary),
                )
            )

            budget_status, budget_message, budget_summary = await self._budget_projection(
                session=session,
                instance=instance,
                source=source,
                account_id=platform_account_id,
                requested_limit=requested_limit,
                comment_limit=comment_limit,
            )
            checks.append(CollectionPreflightCheck("budget", budget_status, budget_message))

        if definition.connector_type == "mediacrawler":
            cdp_ok = await self._cdp_reachable()
            checks.append(
                CollectionPreflightCheck(
                    "cdp",
                    "READY" if cdp_ok else "BLOCKED",
                    "本地 Chrome CDP 127.0.0.1:9222 可连接。" if cdp_ok else "本地 Chrome CDP 127.0.0.1:9222 不可连接，请先启动专用浏览器。",
                )
            )
            if cdp_ok and account is not None and platform in _PLATFORM_ORIGINS:
                login_status, login_message = await self._login_marker_check(platform)
                checks.append(CollectionPreflightCheck("login_state", login_status, login_message))
            elif platform in _PLATFORM_ORIGINS:
                checks.append(CollectionPreflightCheck("login_state", "BLOCKED", "尚不能检查登录态：请先补齐健康平台账号并启动本地 CDP。"))

        return CollectionPreflightReport(
            status="READY" if all(check.status == "READY" for check in checks) else "BLOCKED",
            platform=platform,
            mode=mode,
            requested_limit=requested_limit,
            comment_limit=comment_limit,
            initiates_platform_request=False,
            uses_local_cdp=uses_local_cdp,
            account_label=account_label,
            checkpoint_summary=checkpoint_summary,
            budget_summary=budget_summary,
            checks=tuple(checks),
        )

    @staticmethod
    def _report(
        checks: list[CollectionPreflightCheck],
        platform: str,
        mode: str,
        requested_limit: int,
        comment_limit: int,
    ) -> CollectionPreflightReport:
        return CollectionPreflightReport(
            status="BLOCKED",
            platform=platform,
            mode=mode,
            requested_limit=requested_limit,
            comment_limit=comment_limit,
            checks=tuple(checks),
        )

    @staticmethod
    def _configuration_checks(instance: Any, definition: Any, source: Source) -> list[CollectionPreflightCheck]:
        checks: list[CollectionPreflightCheck] = []
        ready = bool(definition.is_enabled and instance.enabled and source.enabled and instance.status != "archived" and source.status != "archived")
        checks.append(CollectionPreflightCheck("configuration", "READY" if ready else "BLOCKED", "连接器定义、实例与信源均已启用。" if ready else "连接器定义、实例或信源未启用。"))
        implemented = implementation_registry.has(definition.connector_type)
        checks.append(CollectionPreflightCheck("implementation", "READY" if implemented else "BLOCKED", "连接器运行实现已注册。" if implemented else "当前连接器只有能力定义，没有可运行实现。"))
        allowed = bool(definition.capabilities.get(source.mode))
        declared = definition.capabilities.get("allowed_modes")
        if isinstance(declared, list):
            allowed = allowed and source.mode in declared
        instance_modes = instance.config.get("modes")
        if isinstance(instance_modes, list) and instance_modes:
            allowed = allowed and source.mode in instance_modes
        checks.append(CollectionPreflightCheck("mode", "READY" if allowed else "BLOCKED", f"采集模式 {source.mode} 已启用。" if allowed else f"采集模式 {source.mode} 当前不可运行。"))
        return checks

    @staticmethod
    async def _load_account(session: AsyncSession, instance_id: UUID, account_id: UUID | None) -> PlatformAccount | None:
        if account_id is None:
            return None
        account = await session.get(PlatformAccount, account_id)
        return account if account is not None and account.connector_instance_id == instance_id else None

    @staticmethod
    def _account_checks(definition: Any, instance_id: UUID, account: PlatformAccount | None, requested_account_id: UUID | None) -> list[CollectionPreflightCheck]:
        requires_account = bool(definition.capabilities.get("requires_account"))
        if requested_account_id is not None and account is None:
            return [CollectionPreflightCheck("account", "BLOCKED", "所选平台账号不存在或不属于该连接器实例。")]
        if requires_account and account is None:
            return [CollectionPreflightCheck("account", "BLOCKED", "该平台需要绑定健康账号，请先到“平台账号 / 风险”配置。")]
        if account is None:
            return [CollectionPreflightCheck("account", "READY", "该连接器无需平台账号。")]
        try:
            RuntimeRiskGuard().before_run(account)
        except Exception:
            return [CollectionPreflightCheck("account", "BLOCKED", "平台账号处于 cooldown、需要人工复核或其他风险阻断状态。")]
        return [CollectionPreflightCheck("account", "READY", "平台账号健康，当前没有账号级风险阻断。")]

    def _runtime_environment_checks(self, account: PlatformAccount | None) -> list[CollectionPreflightCheck]:
        python_value = self.settings.mediacrawler_python
        python_ready = bool(shutil.which(python_value) or Path(python_value).exists())
        vendor_ready = (REPO_ROOT / self.settings.mediacrawler_home).exists()
        checks = [
            CollectionPreflightCheck("dedicated_python", "READY" if python_ready else "BLOCKED", "MediaCrawler Python 可用。" if python_ready else "MediaCrawler Python 不可用，请检查 MEDIACRAWLER_PYTHON。"),
            CollectionPreflightCheck("vendor_runtime", "READY" if vendor_ready else "BLOCKED", "MediaCrawler vendor 目录存在。" if vendor_ready else "MediaCrawler vendor 目录不存在，请检查 MEDIACRAWLER_HOME。"),
        ]
        if account is None:
            return checks
        profile_ref = account.browser_profile_ref
        if not profile_ref:
            checks.append(CollectionPreflightCheck("profile", "BLOCKED", "平台账号尚未绑定专用 Browser Profile。"))
            return checks
        root = (REPO_ROOT / self.settings.mediacrawler_profile_root).resolve()
        candidate = (root / profile_ref).resolve()
        contained = candidate == root or root in candidate.parents
        ready = contained and candidate.is_dir()
        checks.append(CollectionPreflightCheck("profile", "READY" if ready else "BLOCKED", "专用 Browser Profile 已绑定且可解析。" if ready else "Browser Profile 缺失或不在允许的 Profile 根目录内。"))
        return checks

    @staticmethod
    async def _checkpoint_summary(*, session: AsyncSession, source: Source, account_id: UUID | None) -> dict[str, str | int | None]:
        result = await session.execute(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.connector_instance_id == source.connector_instance_id,
                ConnectorCheckpoint.source_id == source.id,
                ConnectorCheckpoint.platform_account_id == account_id,
                ConnectorCheckpoint.mode == source.mode,
                ConnectorCheckpoint.scope_key == source.scope_key,
            )
        )
        checkpoint = result.scalar_one_or_none()
        if checkpoint is None:
            return {"mode": source.mode, "resume_scope": "从头开始", "version": None}
        data = checkpoint.checkpoint_data or {}
        page = data.get("page")
        if isinstance(page, int) and page >= 1:
            resume = f"{source.mode}:page:{page}"
        else:
            completed = data.get("last_completed_scope")
            resume = str(completed) if isinstance(completed, str) and completed else "已有检查点"
        return {"mode": source.mode, "resume_scope": resume, "version": checkpoint.version}

    @staticmethod
    def _checkpoint_message(summary: dict[str, str | int | None]) -> str:
        resume = summary.get("resume_scope") or "从头开始"
        return f"本次续采位置：{resume}。"

    @staticmethod
    async def _budget_projection(
        *,
        session: AsyncSession,
        instance: ConnectorInstance,
        source: Source,
        account_id: UUID | None,
        requested_limit: int,
        comment_limit: int,
    ) -> tuple[str, str, dict[str, int | str | None]]:
        budgets = await CollectionBudgetRepository(session).applicable(
            platform=instance.definition.platform,
            connector_instance_id=instance.id,
            platform_account_id=account_id,
            source_id=source.id,
        )
        if not budgets:
            return "BLOCKED", "尚未配置适用的采集预算；预检不会自动创建默认预算。", {"budget_count": 0}
        now = datetime.now(UTC)
        for budget in budgets:
            usage_date = now.astimezone(ZoneInfo(budget.timezone)).date()
            usage = await session.scalar(
                select(CollectionBudgetUsage).where(
                    CollectionBudgetUsage.budget_id == budget.id,
                    CollectionBudgetUsage.usage_date == usage_date,
                )
            )
            runs_reserved = usage.runs_reserved if usage else 0
            items_used = usage.items_used if usage else 0
            items_reserved = usage.items_reserved if usage else 0
            comments_used = usage.comments_used if usage else 0
            comments_reserved = usage.comments_reserved if usage else 0
            active_runs = usage.active_runs if usage else 0
            if requested_limit > budget.max_items_per_run:
                return "BLOCKED", "本次条目数超过适用预算的单次上限。", {"budget_count": len(budgets)}
            if comment_limit > budget.max_comments_per_run:
                return "BLOCKED", "本次评论数超过适用预算的单次上限。", {"budget_count": len(budgets)}
            if runs_reserved + 1 > budget.max_runs_per_day:
                return "BLOCKED", "已达到适用预算的当日运行次数上限。", {"budget_count": len(budgets)}
            if items_used + items_reserved + requested_limit > budget.max_items_per_day:
                return "BLOCKED", "已达到适用预算的当日条目上限。", {"budget_count": len(budgets)}
            if comments_used + comments_reserved + comment_limit > budget.max_comments_per_day:
                return "BLOCKED", "已达到适用预算的当日评论上限。", {"budget_count": len(budgets)}
            if active_runs + 1 > budget.max_concurrency:
                return "BLOCKED", "已达到适用预算的并发运行上限。", {"budget_count": len(budgets)}
        return "READY", f"{len(budgets)} 条适用预算允许本次低量请求；当前未预留额度。", {"budget_count": len(budgets), "requested_items": requested_limit, "requested_comments": comment_limit}

    @staticmethod
    async def _cdp_reachable() -> bool:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(EXPECTED_CDP_HOST, EXPECTED_CDP_PORT), timeout=1.5)
            del reader
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    async def _login_marker_check(self, platform: str) -> tuple[str, str]:
        markers = LOGIN_STATE_MARKERS.get(platform)
        origin = _PLATFORM_ORIGINS.get(platform)
        if not markers or not origin or not LOGIN_HELPER_ENTRYPOINT.exists():
            return "BLOCKED", "当前平台没有可用的只读登录态检查器。"
        command = [
            self.settings.mediacrawler_python,
            str(LOGIN_HELPER_ENTRYPOINT),
            "--origin",
            origin,
            "--port",
            str(EXPECTED_CDP_PORT),
        ]
        for marker in markers:
            command.extend(["--marker", marker])
        safe_env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_NAMES}
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=safe_env,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            payload = json.loads(stdout.decode("utf-8"))
        except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError):
            return "BLOCKED", "只读登录态检查未能完成；未发起平台采集。"
        if not isinstance(payload, dict):
            return "BLOCKED", "只读登录态检查返回无效结果。"
        state = payload.get("login_state")
        if payload.get("status") == "READY":
            return "READY", "检测到既有登录标记；未读取或返回 Cookie 内容。"
        if state == "unknown":
            return "BLOCKED", "未确认登录态，请在专用 Profile 中人工登录后重新检查。"
        return "BLOCKED", "未检测到有效登录标记，请在专用 Profile 中人工登录。"
