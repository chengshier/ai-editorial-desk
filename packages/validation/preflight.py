from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.credentials import (
    EnvironmentCredentialResolver,
    credential_ref_mask,
)
from packages.database.models import (
    AIBudgetRecord,
    AIProviderRecord,
    AITaskRouteRecord,
    CollectionBudget,
    CollectionBudgetUsage,
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunStatus,
    PlatformAccount,
    PlatformRiskEvent,
    Source,
)
from packages.risk_guard.models import AccountStatus
from packages.validation.domain import (
    EXPECTED_MIGRATION_HEAD,
    CheckLevel,
    ValidationCheck,
    ValidationSummary,
    check,
)
from packages.validation.redaction import mask_reference

_REQUIRED_E2E_TASKS = ("editorial_scoring", "draft_generation")


async def migration_head(session: AsyncSession) -> str | None:
    try:
        value = await session.scalar(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
    except Exception:  # pragma: no cover - returned as BLOCK by integration use
        return None
    return str(value) if value is not None else None


async def applicable_budgets(
    session: AsyncSession,
    *,
    platform: str,
    instance_id: UUID,
    account_id: UUID,
    source_id: UUID,
) -> tuple[CollectionBudget, ...]:
    conditions = (
        (CollectionBudget.scope_type == "platform")
        & (CollectionBudget.scope_key == platform),
        (CollectionBudget.scope_type == "connector")
        & (CollectionBudget.scope_key == str(instance_id)),
        (CollectionBudget.scope_type == "account")
        & (CollectionBudget.scope_key == str(account_id)),
        (CollectionBudget.scope_type == "task")
        & (CollectionBudget.scope_key == str(source_id)),
    )
    rows = await session.scalars(
        select(CollectionBudget)
        .where(CollectionBudget.enabled.is_(True), or_(*conditions))
        .order_by(CollectionBudget.id)
    )
    return tuple(rows.all())


async def budget_check(
    session: AsyncSession,
    budgets: tuple[CollectionBudget, ...],
    *,
    requested_limit: int,
) -> ValidationCheck:
    if not budgets:
        return check(
            "collection_budget",
            CheckLevel.BLOCK,
            "没有显式 Collection Budget；Preflight 不会自动创建默认预算",
        )
    now = datetime.now(UTC)
    for budget in budgets:
        if requested_limit > budget.max_items_per_run:
            return check(
                "collection_budget",
                CheckLevel.BLOCK,
                "requested_limit 超过单次 Collection Budget",
                budget_id=str(budget.id),
            )
        usage_date = now.astimezone(ZoneInfo(budget.timezone)).date()
        usage = await session.scalar(
            select(CollectionBudgetUsage).where(
                CollectionBudgetUsage.budget_id == budget.id,
                CollectionBudgetUsage.usage_date == usage_date,
            )
        )
        runs_reserved = usage.runs_reserved if usage else 0
        items_reserved = usage.items_reserved if usage else 0
        items_used = usage.items_used if usage else 0
        active_runs = usage.active_runs if usage else 0
        if runs_reserved + 1 > budget.max_runs_per_day:
            return check(
                "collection_budget",
                CheckLevel.BLOCK,
                "当日 Collection Run 预算已满",
                budget_id=str(budget.id),
            )
        if items_used + items_reserved + requested_limit > budget.max_items_per_day:
            return check(
                "collection_budget",
                CheckLevel.BLOCK,
                "当日 Collection item 预算不足",
                budget_id=str(budget.id),
            )
        if active_runs + 1 > budget.max_concurrency:
            return check(
                "collection_budget",
                CheckLevel.BLOCK,
                "Collection concurrency 预算不足",
                budget_id=str(budget.id),
            )
    return check(
        "collection_budget",
        CheckLevel.PASS,
        "Collection Budget 可支持本次低量验证",
        applicable_count=len(budgets),
    )


class M5DPreflightService:
    """Read-only preflight; it never logs in, collects, calls AI, or mutates state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        *,
        platform: str,
        connector_instance_id: UUID,
        source_id: UUID,
        account_id: UUID,
        requested_limit: int = 1,
        provider_id: UUID | None = None,
        phase: str = "e2e",
    ) -> ValidationSummary:
        checks: list[ValidationCheck] = []
        await self.session.scalar(select(func.count()).select_from(ConnectorDefinition))
        checks.append(check("database", CheckLevel.PASS, "PostgreSQL 可读"))

        revision = await migration_head(self.session)
        revision_ok = revision == EXPECTED_MIGRATION_HEAD
        checks.append(
            check(
                "migration",
                CheckLevel.PASS if revision_ok else CheckLevel.BLOCK,
                "Alembic revision 正确" if revision_ok else "Alembic revision 不匹配",
                revision=revision,
                expected=EXPECTED_MIGRATION_HEAD,
            )
        )

        instance = await self.session.get(ConnectorInstance, connector_instance_id)
        source = await self.session.get(Source, source_id)
        account = await self.session.get(PlatformAccount, account_id)
        if instance is None:
            checks.append(
                check("connector_instance", CheckLevel.BLOCK, "Connector Instance 不存在")
            )
            return ValidationSummary(tuple(checks))

        definition = await self.session.get(ConnectorDefinition, instance.definition_id)
        capabilities = definition.capabilities if definition else {}
        connector_ok = bool(
            definition
            and definition.is_enabled
            and definition.connector_type == "mediacrawler"
            and definition.platform == platform
            and instance.enabled
            and capabilities.get("search")
        )
        checks.append(
            check(
                "connector",
                CheckLevel.PASS if connector_ok else CheckLevel.BLOCK,
                "MediaCrawler search capability 可用"
                if connector_ok
                else "Connector/Definition/platform/search capability 不满足条件",
                platform=platform,
                connector_instance_id=str(instance.id),
                implementation_version=(
                    definition.implementation_version if definition else None
                ),
            )
        )

        source_ok = bool(
            source
            and source.connector_instance_id == instance.id
            and source.enabled
            and source.status == "active"
        )
        checks.append(
            check(
                "source",
                CheckLevel.PASS if source_ok else CheckLevel.BLOCK,
                "Source 可用" if source_ok else "Source 不可用或不属于目标 Connector",
                source_id=str(source_id),
                mode=source.mode if source else None,
            )
        )

        now = datetime.now(UTC)
        account_ok = bool(
            account
            and account.connector_instance_id == instance.id
            and account.platform == platform
            and account.status is AccountStatus.HEALTHY
            and not account.manual_review_required
            and (account.cooldown_until is None or account.cooldown_until <= now)
            and account.browser_profile_ref
        )
        checks.append(
            check(
                "platform_account",
                CheckLevel.PASS if account_ok else CheckLevel.BLOCK,
                "PlatformAccount HEALTHY 且 Profile reference 已配置"
                if account_ok
                else "Account 状态、人工复核、cooldown 或 Profile 阻止真实 Smoke",
                account_id=str(account_id),
                status=account.status.value if account else None,
                profile_ref=(
                    mask_reference(account.browser_profile_ref) if account else None
                ),
            )
        )

        if source and account:
            budgets = await applicable_budgets(
                self.session,
                platform=platform,
                instance_id=instance.id,
                account_id=account.id,
                source_id=source.id,
            )
            checks.append(
                await budget_check(
                    self.session,
                    budgets,
                    requested_limit=requested_limit,
                )
            )
            checkpoint_count = int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(ConnectorCheckpoint)
                    .where(
                        ConnectorCheckpoint.connector_instance_id == instance.id,
                        ConnectorCheckpoint.platform_account_id == account.id,
                        ConnectorCheckpoint.source_id == source.id,
                    )
                )
                or 0
            )
            checks.append(
                check(
                    "checkpoint",
                    CheckLevel.PASS if checkpoint_count else CheckLevel.WARN,
                    "Checkpoint 可读"
                    if checkpoint_count
                    else "首次运行尚无 Checkpoint；允许从空状态开始",
                    count=checkpoint_count,
                )
            )
            risk_count = int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(PlatformRiskEvent)
                    .where(
                        PlatformRiskEvent.platform_account_id == account.id,
                        PlatformRiskEvent.resolved_at.is_(None),
                    )
                )
                or 0
            )
            checks.append(
                check(
                    "platform_risk",
                    CheckLevel.PASS if risk_count == 0 else CheckLevel.BLOCK,
                    "无未解决平台风险"
                    if risk_count == 0
                    else "存在未解决平台风险，必须停止真实验证",
                    open_risk_count=risk_count,
                )
            )

        checks.extend(await self._provider_checks(provider_id, phase))
        return ValidationSummary(tuple(checks))

    async def _provider_checks(
        self,
        provider_id: UUID | None,
        phase: str,
    ) -> list[ValidationCheck]:
        if phase == "platform" and provider_id is None:
            return [
                check(
                    "production_provider",
                    CheckLevel.WARN,
                    "Platform-only preflight 未选择 AI Provider",
                )
            ]
        provider = (
            await self.session.get(AIProviderRecord, provider_id)
            if provider_id
            else await self.session.scalar(
                select(AIProviderRecord)
                .where(AIProviderRecord.enabled.is_(True))
                .order_by(AIProviderRecord.created_at.desc())
                .limit(1)
            )
        )
        if provider is None:
            return [check("production_provider", CheckLevel.BLOCK, "没有 AI Provider")]

        resolver = EnvironmentCredentialResolver()
        configured = resolver.configured(provider.credential_ref)
        checks = [
            check(
                "production_provider",
                CheckLevel.PASS if provider.enabled and configured else CheckLevel.BLOCK,
                "Provider 与 credential reference 可用"
                if provider.enabled and configured
                else "Provider 未启用或 credential reference 不可解析",
                provider_id=str(provider.id),
                provider_key=provider.provider_key,
                credential_ref=credential_ref_mask(provider.credential_ref),
            )
        ]
        validated = provider.validation_status == "PASSED"
        validation_level = (
            CheckLevel.PASS
            if validated
            else CheckLevel.BLOCK if phase == "e2e" else CheckLevel.WARN
        )
        checks.append(
            check(
                "provider_validation",
                validation_level,
                "Production Provider Connection Validation 已通过"
                if validated
                else "Production Provider Validation 尚未通过",
                validation_status=provider.validation_status,
            )
        )

        routes = tuple(
            (
                await self.session.scalars(
                    select(AITaskRouteRecord).where(
                        AITaskRouteRecord.task_key.in_(_REQUIRED_E2E_TASKS),
                        AITaskRouteRecord.enabled.is_(True),
                        AITaskRouteRecord.is_active.is_(True),
                    )
                )
            ).all()
        )
        route_keys = {route.task_key for route in routes}
        missing = [key for key in _REQUIRED_E2E_TASKS if key not in route_keys]
        checks.append(
            check(
                "ai_routes",
                CheckLevel.PASS if not missing else CheckLevel.BLOCK,
                "E2E AI Routes 已启用" if not missing else "缺少 E2E AI Route",
                missing=missing,
            )
        )
        budget_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AIBudgetRecord)
                .where(AIBudgetRecord.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            check(
                "ai_budget",
                CheckLevel.PASS if budget_count else CheckLevel.BLOCK,
                "AI Budget 已配置" if budget_count else "AI Budget 缺失",
                enabled_count=budget_count,
            )
        )
        return checks


class MVPDoctorService:
    """Read-only operational summary; WARN and BLOCK are intentionally distinct."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> ValidationSummary:
        checks: list[ValidationCheck] = []
        revision = await migration_head(self.session)
        revision_ok = revision == EXPECTED_MIGRATION_HEAD
        checks.append(
            check(
                "migration",
                CheckLevel.PASS if revision_ok else CheckLevel.BLOCK,
                "Migration head 正确" if revision_ok else "Migration head 不匹配",
                revision=revision,
                expected=EXPECTED_MIGRATION_HEAD,
            )
        )
        risky_accounts = int(
            await self.session.scalar(
                select(func.count())
                .select_from(PlatformAccount)
                .where(
                    or_(
                        PlatformAccount.status.in_(
                            (AccountStatus.REVIEW_REQUIRED, AccountStatus.RESTRICTED)
                        ),
                        PlatformAccount.manual_review_required.is_(True),
                    )
                )
            )
            or 0
        )
        checks.append(
            check(
                "account_risk",
                CheckLevel.WARN if risky_accounts else CheckLevel.PASS,
                "存在需人工处理账号" if risky_accounts else "无阻塞账号",
                count=risky_accounts,
            )
        )
        collection_budgets = int(
            await self.session.scalar(
                select(func.count())
                .select_from(CollectionBudget)
                .where(CollectionBudget.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            check(
                "collection_budgets",
                CheckLevel.PASS if collection_budgets else CheckLevel.WARN,
                "Collection Budget 已配置"
                if collection_budgets
                else "未发现启用的 Collection Budget",
                count=collection_budgets,
            )
        )
        providers = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AIProviderRecord)
                .where(AIProviderRecord.enabled.is_(True))
            )
            or 0
        )
        validated = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AIProviderRecord)
                .where(
                    AIProviderRecord.enabled.is_(True),
                    AIProviderRecord.validation_status == "PASSED",
                )
            )
            or 0
        )
        provider_level = (
            CheckLevel.PASS
            if validated
            else CheckLevel.WARN if providers else CheckLevel.BLOCK
        )
        checks.append(
            check(
                "production_provider",
                provider_level,
                "Production Provider 有 PASSED 证据"
                if validated
                else "Production Provider 阻止真实 E2E",
                enabled_count=providers,
                passed_count=validated,
            )
        )
        ai_budgets = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AIBudgetRecord)
                .where(AIBudgetRecord.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            check(
                "ai_budgets",
                CheckLevel.PASS if ai_budgets else CheckLevel.BLOCK,
                "AI Budget 已配置" if ai_budgets else "AI Budget 缺失",
                count=ai_budgets,
            )
        )
        failures = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ConnectorRun)
                .where(
                    ConnectorRun.status.in_(
                        (ConnectorRunStatus.FAILED, ConnectorRunStatus.PAUSED_RISK)
                    )
                )
            )
            or 0
        )
        checks.append(
            check(
                "collection_failures",
                CheckLevel.WARN if failures else CheckLevel.PASS,
                "存在 failed/paused_risk Collection Run"
                if failures
                else "无 failed/paused_risk Collection Run",
                count=failures,
            )
        )
        return ValidationSummary(tuple(checks))
