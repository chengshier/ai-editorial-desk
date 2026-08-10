from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.credentials import EnvironmentCredentialResolver, credential_ref_mask
from packages.database.models import (
    AIBudgetRecord,
    AIInvocationAttemptRecord,
    AIInvocationRecord,
    AIModelRecord,
    AIProviderRecord,
    AITaskRouteRecord,
    CollectionBudget,
    CollectionBudgetUsage,
    ConnectorCheckpoint,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    DraftClaimReferenceRecord,
    DraftSourceType,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialDraftRecord,
    EditorialPackRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventCardRecord,
    EventRecord,
    EventSignalRecord,
    EventTrendSnapshotRecord,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    PlatformAccount,
    PlatformRiskEvent,
    RawSignalRecord,
    Source,
)
from packages.risk_guard.models import AccountStatus
from packages.validation.redaction import mask_reference, sanitize_validation_payload

EXPECTED_MIGRATION_HEAD = "20260810_0015"
_REQUIRED_E2E_TASKS = ("editorial_scoring", "draft_generation")
_ALLOWED_REAL_BUSINESS_TASKS = frozenset(
    {"evidence_extraction", "editorial_scoring", "draft_generation", "signal_embedding"}
)
_FAKE_MARKERS = ("fake", "mock", "stub", "synthetic", "offline", "fixture", "test-provider")


class CheckLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    key: str
    level: CheckLevel
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return sanitize_validation_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    checks: tuple[ValidationCheck, ...]

    @property
    def result(self) -> CheckLevel:
        levels = {item.level for item in self.checks}
        if CheckLevel.BLOCK in levels:
            return CheckLevel.BLOCK
        if CheckLevel.WARN in levels:
            return CheckLevel.WARN
        return CheckLevel.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "checks": [item.to_dict() for item in self.checks],
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class E2EVerificationResult:
    result: str
    checks: tuple[ValidationCheck, ...]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return sanitize_validation_payload(
            {
                "result": self.result,
                "checks": [item.to_dict() for item in self.checks],
                "evidence": self.evidence,
                "read_only": True,
                "artifacts_created": False,
            }
        )


def _check(
    key: str,
    level: CheckLevel,
    message: str,
    **details: Any,
) -> ValidationCheck:
    return ValidationCheck(key=key, level=level, message=message, details=details)


def _contains_fake_marker(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    return any(marker in normalized for marker in _FAKE_MARKERS)


def _metadata_declares_synthetic(metadata: dict[str, Any]) -> bool:
    for key, value in metadata.items():
        normalized = str(key).casefold()
        if any(marker in normalized for marker in _FAKE_MARKERS):
            if value not in (False, None, "", 0):
                return True
        if isinstance(value, str) and _contains_fake_marker(value):
            return True
    return False


async def _migration_head(session: AsyncSession) -> str | None:
    try:
        value = await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # pragma: no cover - exercised as a BLOCK by integration tests
        return None
    return str(value) if value is not None else None


async def _applicable_budgets(
    session: AsyncSession,
    *,
    platform: str,
    instance_id: UUID,
    account_id: UUID,
    source_id: UUID,
) -> tuple[CollectionBudget, ...]:
    conditions = (
        (CollectionBudget.scope_type == "platform") & (CollectionBudget.scope_key == platform),
        (CollectionBudget.scope_type == "connector")
        & (CollectionBudget.scope_key == str(instance_id)),
        (CollectionBudget.scope_type == "account") & (CollectionBudget.scope_key == str(account_id)),
        (CollectionBudget.scope_type == "task") & (CollectionBudget.scope_key == str(source_id)),
    )
    rows = await session.scalars(
        select(CollectionBudget)
        .where(CollectionBudget.enabled.is_(True), or_(*conditions))
        .order_by(CollectionBudget.id)
    )
    return tuple(rows.all())


async def _budget_check(
    session: AsyncSession,
    budgets: tuple[CollectionBudget, ...],
    *,
    requested_limit: int,
) -> ValidationCheck:
    if not budgets:
        return _check(
            "collection_budget",
            CheckLevel.BLOCK,
            "没有可用的显式 Collection Budget；Preflight 不会自动创建默认预算",
        )
    now = datetime.now(UTC)
    remaining: list[dict[str, Any]] = []
    for budget in budgets:
        if requested_limit > budget.max_items_per_run:
            return _check(
                "collection_budget",
                CheckLevel.BLOCK,
                "requested_limit 超过现有单次采集预算",
                budget_id=str(budget.id),
                max_items_per_run=budget.max_items_per_run,
            )
        usage_date = now.astimezone(ZoneInfo(budget.timezone)).date()
        usage = await session.scalar(
            select(CollectionBudgetUsage).where(
                CollectionBudgetUsage.budget_id == budget.id,
                CollectionBudgetUsage.usage_date == usage_date,
            )
        )
        runs_reserved = usage.runs_reserved if usage is not None else 0
        runs_completed = usage.runs_completed if usage is not None else 0
        items_reserved = usage.items_reserved if usage is not None else 0
        items_used = usage.items_used if usage is not None else 0
        active_runs = usage.active_runs if usage is not None else 0
        if runs_reserved + 1 > budget.max_runs_per_day:
            return _check(
                "collection_budget",
                CheckLevel.BLOCK,
                "Collection Budget 当日运行次数不足",
                budget_id=str(budget.id),
            )
        if items_used + items_reserved + requested_limit > budget.max_items_per_day:
            return _check(
                "collection_budget",
                CheckLevel.BLOCK,
                "Collection Budget 当日条目额度不足",
                budget_id=str(budget.id),
            )
        if active_runs + 1 > budget.max_concurrency:
            return _check(
                "collection_budget",
                CheckLevel.BLOCK,
                "Collection Budget 并发额度不足",
                budget_id=str(budget.id),
            )
        remaining.append(
            {
                "budget_id": str(budget.id),
                "runs_completed": runs_completed,
                "max_runs_per_day": budget.max_runs_per_day,
                "items_used": items_used,
                "max_items_per_day": budget.max_items_per_day,
                "max_concurrency": budget.max_concurrency,
            }
        )
    return _check(
        "collection_budget",
        CheckLevel.PASS,
        "Collection Budget 可支持本次低量验证",
        applicable=remaining,
    )


class M5DPreflightService:
    """Read-only checks before any real platform/provider/E2E operation."""

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
        checks.append(_check("database", CheckLevel.PASS, "PostgreSQL 可读"))

        revision = await _migration_head(self.session)
        checks.append(
            _check(
                "migration",
                CheckLevel.PASS if revision == EXPECTED_MIGRATION_HEAD else CheckLevel.BLOCK,
                (
                    "Alembic revision 与 M5-D 基线一致"
                    if revision == EXPECTED_MIGRATION_HEAD
                    else "Alembic revision 与 M5-D 基线不一致"
                ),
                revision=revision,
                expected=EXPECTED_MIGRATION_HEAD,
            )
        )

        instance = await self.session.get(ConnectorInstance, connector_instance_id)
        source = await self.session.get(Source, source_id)
        account = await self.session.get(PlatformAccount, account_id)
        if instance is None:
            checks.append(_check("connector_instance", CheckLevel.BLOCK, "Connector Instance 不存在"))
            return ValidationSummary(tuple(checks))
        definition = await self.session.get(ConnectorDefinition, instance.definition_id)
        definition_ok = bool(
            definition is not None
            and definition.is_enabled
            and definition.connector_type == "mediacrawler"
            and definition.platform == platform
            and instance.enabled
        )
        capabilities = definition.capabilities if definition is not None else {}
        search_ready = bool(capabilities.get("search"))
        checks.append(
            _check(
                "connector",
                CheckLevel.PASS if definition_ok and search_ready else CheckLevel.BLOCK,
                (
                    "MediaCrawler Connector/Definition 已启用且具备 search capability"
                    if definition_ok and search_ready
                    else "Connector/Definition/platform/capability 不满足真实 Smoke 前置条件"
                ),
                connector_instance_id=str(instance.id),
                platform=platform,
                implementation_version=(definition.implementation_version if definition else None),
            )
        )

        source_ok = bool(
            source is not None
            and source.connector_instance_id == instance.id
            and source.enabled
            and source.status == "active"
        )
        checks.append(
            _check(
                "source",
                CheckLevel.PASS if source_ok else CheckLevel.BLOCK,
                "Source 可用" if source_ok else "Source 不存在、未启用或不属于目标 Connector",
                source_id=str(source_id),
                mode=(source.mode if source else None),
            )
        )

        account_ok = bool(
            account is not None
            and account.connector_instance_id == instance.id
            and account.platform == platform
            and account.status is AccountStatus.HEALTHY
            and not account.manual_review_required
            and (account.cooldown_until is None or account.cooldown_until <= datetime.now(UTC))
        )
        profile_present = bool(account and account.browser_profile_ref)
        checks.append(
            _check(
                "platform_account",
                CheckLevel.PASS if account_ok and profile_present else CheckLevel.BLOCK,
                (
                    "PlatformAccount HEALTHY，且已有受控 browser profile reference"
                    if account_ok and profile_present
                    else "PlatformAccount 状态/Profile 阻止真实平台验证"
                ),
                account_id=str(account_id),
                status=(account.status.value if account else None),
                profile_ref=(mask_reference(account.browser_profile_ref) if account else None),
            )
        )

        if source is not None and account is not None:
            budgets = await _applicable_budgets(
                self.session,
                platform=platform,
                instance_id=instance.id,
                account_id=account.id,
                source_id=source.id,
            )
            checks.append(
                await _budget_check(self.session, budgets, requested_limit=requested_limit)
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
                _check(
                    "checkpoint",
                    CheckLevel.PASS if checkpoint_count else CheckLevel.WARN,
                    (
                        "Checkpoint 可读"
                        if checkpoint_count
                        else "尚无 Checkpoint；首次真实 Run 可以从空 Checkpoint 开始"
                    ),
                    count=checkpoint_count,
                )
            )
            open_risks = int(
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
                _check(
                    "platform_risk",
                    CheckLevel.PASS if open_risks == 0 else CheckLevel.BLOCK,
                    "无未解决平台风险" if open_risks == 0 else "存在未解决平台风险，必须停止真实验证",
                    open_risk_count=open_risks,
                )
            )

        checks.extend(await self._provider_checks(provider_id=provider_id, phase=phase))
        return ValidationSummary(tuple(checks))

    async def _provider_checks(
        self,
        *,
        provider_id: UUID | None,
        phase: str,
    ) -> list[ValidationCheck]:
        if phase == "platform" and provider_id is None:
            return [_check("production_provider", CheckLevel.WARN, "Platform-only preflight 未选择 AI Provider")]
        provider = (
            await self.session.get(AIProviderRecord, provider_id)
            if provider_id is not None
            else await self.session.scalar(
                select(AIProviderRecord)
                .where(AIProviderRecord.enabled.is_(True))
                .order_by(AIProviderRecord.created_at.desc())
                .limit(1)
            )
        )
        if provider is None:
            return [_check("production_provider", CheckLevel.BLOCK, "没有可用 AI Provider")]
        resolver = EnvironmentCredentialResolver()
        configured = resolver.configured(provider.credential_ref)
        base_level = CheckLevel.PASS if provider.enabled and configured else CheckLevel.BLOCK
        checks = [
            _check(
                "production_provider",
                base_level,
                (
                    "AI Provider 已启用且 credential reference 可解析"
                    if base_level is CheckLevel.PASS
                    else "AI Provider 未启用或 credential reference 当前不可解析"
                ),
                provider_id=str(provider.id),
                provider_key=provider.provider_key,
                credential_ref=credential_ref_mask(provider.credential_ref),
                validation_status=provider.validation_status,
            )
        ]
        if provider.validation_status != "PASSED":
            level = CheckLevel.BLOCK if phase == "e2e" else CheckLevel.WARN
            checks.append(
                _check(
                    "provider_validation",
                    level,
                    "Production Provider 尚无 PASSED 真实连接证据",
                    validation_status=provider.validation_status,
                )
            )
        else:
            checks.append(
                _check("provider_validation", CheckLevel.PASS, "Provider validation_status=PASSED")
            )

        route_rows = tuple(
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
        route_keys = {row.task_key for row in route_rows}
        missing_routes = [key for key in _REQUIRED_E2E_TASKS if key not in route_keys]
        checks.append(
            _check(
                "ai_routes",
                CheckLevel.PASS if not missing_routes else CheckLevel.BLOCK,
                "E2E AI Routes 已启用" if not missing_routes else "缺少 E2E 必需 AI Route",
                missing=missing_routes,
            )
        )
        enabled_budget_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AIBudgetRecord)
                .where(AIBudgetRecord.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            _check(
                "ai_budget",
                CheckLevel.PASS if enabled_budget_count else CheckLevel.BLOCK,
                "存在启用的 AI Budget" if enabled_budget_count else "没有启用的 AI Budget",
                enabled_budget_count=enabled_budget_count,
            )
        )
        return checks


class MVPDoctorService:
    """Read-only operational doctor. It reports; it never repairs configuration."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> ValidationSummary:
        checks: list[ValidationCheck] = []
        revision = await _migration_head(self.session)
        checks.append(
            _check(
                "migration",
                CheckLevel.PASS if revision == EXPECTED_MIGRATION_HEAD else CheckLevel.BLOCK,
                "Migration head 正确" if revision == EXPECTED_MIGRATION_HEAD else "Migration head 不匹配",
                revision=revision,
                expected=EXPECTED_MIGRATION_HEAD,
            )
        )
        restricted = int(
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
            _check(
                "account_risk",
                CheckLevel.WARN if restricted else CheckLevel.PASS,
                "存在需要人工处理的采集账号" if restricted else "无 REVIEW_REQUIRED/RESTRICTED 账号",
                blocked_account_count=restricted,
            )
        )
        collection_budget_count = int(
            await self.session.scalar(
                select(func.count()).select_from(CollectionBudget).where(CollectionBudget.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            _check(
                "collection_budgets",
                CheckLevel.PASS if collection_budget_count else CheckLevel.WARN,
                "Collection Budget 已配置" if collection_budget_count else "未发现启用的 Collection Budget",
                enabled_count=collection_budget_count,
            )
        )
        provider_count = int(
            await self.session.scalar(
                select(func.count()).select_from(AIProviderRecord).where(AIProviderRecord.enabled.is_(True))
            )
            or 0
        )
        validated_provider_count = int(
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
        checks.append(
            _check(
                "production_provider",
                (
                    CheckLevel.PASS
                    if validated_provider_count
                    else CheckLevel.WARN if provider_count else CheckLevel.BLOCK
                ),
                (
                    "至少一个启用 Provider 已通过真实 Connection Validation"
                    if validated_provider_count
                    else "Production Provider 仍阻止真实 E2E"
                ),
                enabled_count=provider_count,
                passed_validation_count=validated_provider_count,
            )
        )
        ai_budget_count = int(
            await self.session.scalar(
                select(func.count()).select_from(AIBudgetRecord).where(AIBudgetRecord.enabled.is_(True))
            )
            or 0
        )
        checks.append(
            _check(
                "ai_budgets",
                CheckLevel.PASS if ai_budget_count else CheckLevel.BLOCK,
                "AI Budget 已配置" if ai_budget_count else "AI Budget 缺失",
                enabled_count=ai_budget_count,
            )
        )
        recent_failed = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ConnectorRun)
                .where(ConnectorRun.status.in_((ConnectorRunStatus.FAILED, ConnectorRunStatus.PAUSED_RISK)))
            )
            or 0
        )
        checks.append(
            _check(
                "collection_failures",
                CheckLevel.WARN if recent_failed else CheckLevel.PASS,
                "存在历史 failed/paused_risk Collection Run" if recent_failed else "当前数据库无 failed/paused_risk Collection Run",
                count=recent_failed,
            )
        )
        return ValidationSummary(tuple(checks))


async def verify_business_invocation(
    session: AsyncSession,
    invocation_id: UUID,
    *,
    expected_provider_key: str | None = None,
) -> ValidationSummary:
    invocation = await session.get(AIInvocationRecord, invocation_id)
    if invocation is None:
        return ValidationSummary(
            (_check("business_invocation", CheckLevel.BLOCK, "AI Invocation 不存在"),)
        )
    checks: list[ValidationCheck] = []
    task_ok = invocation.task_key in _ALLOWED_REAL_BUSINESS_TASKS
    checks.append(
        _check(
            "business_task",
            CheckLevel.PASS if task_ok else CheckLevel.BLOCK,
            "Invocation 是允许的业务任务" if task_ok else "Invocation 不是 M5-D 认可的业务任务",
            task_key=invocation.task_key,
        )
    )
    provider_ok = bool(
        invocation.provider_key
        and not _contains_fake_marker(invocation.provider_key)
        and (
            expected_provider_key is None
            or invocation.provider_key == expected_provider_key
        )
    )
    checks.append(
        _check(
            "real_provider_identity",
            CheckLevel.PASS if provider_ok else CheckLevel.BLOCK,
            "Invocation provider identity 未命中 Fake/Mock 标记" if provider_ok else "Invocation provider identity 不满足真实 Provider Gate",
            provider_key=invocation.provider_key,
        )
    )
    attempts = tuple(
        (
            await session.scalars(
                select(AIInvocationAttemptRecord)
                .where(AIInvocationAttemptRecord.invocation_id == invocation.id)
                .order_by(AIInvocationAttemptRecord.attempt_no)
            )
        ).all()
    )
    successful_real_attempt = any(
        item.status == "succeeded"
        and not _contains_fake_marker(item.provider_key)
        and (expected_provider_key is None or item.provider_key == expected_provider_key)
        for item in attempts
    )
    checks.append(
        _check(
            "provider_attempt",
            CheckLevel.PASS if successful_real_attempt else CheckLevel.BLOCK,
            "至少一个真实 Provider Attempt succeeded" if successful_real_attempt else "没有可验证的真实 succeeded Provider Attempt",
            attempt_count=len(attempts),
        )
    )
    invocation_success = invocation.status == "succeeded"
    checks.append(
        _check(
            "invocation_status",
            CheckLevel.PASS if invocation_success else CheckLevel.BLOCK,
            "Invocation succeeded" if invocation_success else "Invocation 未成功",
            status=invocation.status,
            usage="available" if invocation.total_tokens is not None else "unknown",
            cost="available" if invocation.estimated_cost is not None else "unknown",
        )
    )
    return ValidationSummary(tuple(checks))


async def verify_m5d_e2e(
    session: AsyncSession,
    *,
    collection_run_id: UUID,
    event_id: UUID,
    candidate_run_id: UUID,
    decision_id: UUID,
    draft_id: UUID,
) -> E2EVerificationResult:
    checks: list[ValidationCheck] = []
    evidence: dict[str, Any] = {
        "collection_run_id": str(collection_run_id),
        "event_id": str(event_id),
        "candidate_run_id": str(candidate_run_id),
        "decision_id": str(decision_id),
        "draft_id": str(draft_id),
    }

    run = await session.get(ConnectorRun, collection_run_id)
    run_ok = bool(
        run is not None
        and run.status is ConnectorRunStatus.SUCCEEDED
        and not _metadata_declares_synthetic(run.run_metadata)
    )
    checks.append(
        _check(
            "collection_run",
            CheckLevel.PASS if run_ok else CheckLevel.BLOCK,
            "CollectionRun 可作为真实链路候选证据" if run_ok else "CollectionRun 不存在、未成功或显式标记为 synthetic/mock/offline",
            status=(run.status.value if run else None),
        )
    )
    if run is None:
        return E2EVerificationResult("FAIL", tuple(checks), evidence)

    instance = await session.get(ConnectorInstance, run.connector_instance_id)
    definition = await session.get(ConnectorDefinition, instance.definition_id) if instance else None
    connector_ok = bool(definition and definition.connector_type == "mediacrawler")
    checks.append(
        _check(
            "collection_connector",
            CheckLevel.PASS if connector_ok else CheckLevel.BLOCK,
            "CollectionRun 来自 MediaCrawler 主系统链" if connector_ok else "CollectionRun 不是 MediaCrawler 主系统链",
            platform=(definition.platform if definition else None),
            implementation_version=(definition.implementation_version if definition else None),
        )
    )

    signal_ids = tuple(
        (
            await session.scalars(
                select(RawSignalRecord.id).where(RawSignalRecord.connector_run_id == collection_run_id)
            )
        ).all()
    )
    checks.append(
        _check(
            "raw_signal",
            CheckLevel.PASS if signal_ids else CheckLevel.BLOCK,
            "CollectionRun 产生至少一个 RawSignal" if signal_ids else "CollectionRun 没有关联 RawSignal",
            count=len(signal_ids),
        )
    )
    evidence["raw_signal_count"] = len(signal_ids)

    event = await session.get(EventRecord, event_id)
    event_ok = bool(event is not None and event.merged_into_event_id is None)
    checks.append(
        _check(
            "event",
            CheckLevel.PASS if event_ok else CheckLevel.BLOCK,
            "Event active 且未 merged" if event_ok else "Event 不存在或已 merged",
        )
    )
    linked_signal_count = 0
    if signal_ids:
        linked_signal_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EventSignalRecord)
                .where(
                    EventSignalRecord.event_id == event_id,
                    EventSignalRecord.signal_id.in_(signal_ids),
                )
            )
            or 0
        )
    checks.append(
        _check(
            "event_signal_provenance",
            CheckLevel.PASS if linked_signal_count else CheckLevel.BLOCK,
            "Event 绑定本次真实 Run 的 RawSignal" if linked_signal_count else "Event 未绑定本次 Run 的 RawSignal",
            linked_signal_count=linked_signal_count,
        )
    )

    claim_source_count = 0
    if signal_ids:
        claim_source_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EvidenceClaimSourceRecord)
                .join(EvidenceClaimRecord, EvidenceClaimRecord.id == EvidenceClaimSourceRecord.claim_id)
                .where(
                    EvidenceClaimRecord.event_id == event_id,
                    EvidenceClaimSourceRecord.signal_id.in_(signal_ids),
                )
            )
            or 0
        )
    checks.append(
        _check(
            "evidence_chain",
            CheckLevel.PASS if claim_source_count else CheckLevel.BLOCK,
            "Evidence Claim 可追溯到本次 Run 的 RawSignal" if claim_source_count else "缺少 RawSignal → Evidence Claim provenance",
            claim_source_count=claim_source_count,
        )
    )
    evidence["evidence_claim_source_count"] = claim_source_count

    trend = await session.scalar(
        select(EventTrendSnapshotRecord)
        .where(EventTrendSnapshotRecord.event_id == event_id)
        .order_by(EventTrendSnapshotRecord.created_at.desc())
        .limit(1)
    )
    checks.append(
        _check(
            "trend",
            CheckLevel.PASS if trend else CheckLevel.BLOCK,
            "Event Trend Snapshot 存在" if trend else "Event 缺少 Trend Snapshot",
        )
    )
    evidence["trend_snapshot_id"] = str(trend.id) if trend else None

    score = await session.scalar(
        select(EditorialScoreRecord)
        .where(
            EditorialScoreRecord.event_id == event_id,
            EditorialScoreRecord.source_type == EditorialScoreSourceType.AI,
        )
        .order_by(EditorialScoreRecord.created_at.desc())
        .limit(1)
    )
    score_invocation = await verify_business_invocation(
        session,
        score.ai_invocation_id,
    ) if score is not None and score.ai_invocation_id is not None else ValidationSummary(
        (_check("score_invocation", CheckLevel.BLOCK, "AI Score 缺少 Invocation"),)
    )
    score_ok = score is not None and score_invocation.result is not CheckLevel.BLOCK
    checks.append(
        _check(
            "editorial_score",
            CheckLevel.PASS if score_ok else CheckLevel.BLOCK,
            "真实 Provider AI Editorial Score 存在" if score_ok else "缺少可验证的真实 Provider AI Score",
            score_id=(str(score.id) if score else None),
            invocation_id=(str(score.ai_invocation_id) if score and score.ai_invocation_id else None),
        )
    )
    checks.extend(score_invocation.checks)
    evidence["editorial_score_id"] = str(score.id) if score else None
    evidence["score_invocation_id"] = str(score.ai_invocation_id) if score and score.ai_invocation_id else None

    candidate_run = await session.get(DailyCandidateRunRecord, candidate_run_id)
    candidate = await session.scalar(
        select(DailyCandidateRecord).where(
            DailyCandidateRecord.run_id == candidate_run_id,
            DailyCandidateRecord.event_id == event_id,
        )
    )
    candidate_ok = bool(candidate_run is not None and candidate is not None)
    checks.append(
        _check(
            "candidate",
            CheckLevel.PASS if candidate_ok else CheckLevel.BLOCK,
            "Event 位于指定 Candidate Run" if candidate_ok else "Candidate Run/Event provenance 不一致",
            rank=(candidate.rank if candidate else None),
            ranking_version=(candidate_run.ranking_version if candidate_run else None),
        )
    )
    evidence["algorithmic_rank"] = candidate.rank if candidate else None

    decision = await session.get(EditorialDecisionRecord, decision_id)
    decision_ok = bool(
        decision is not None
        and decision.event_id == event_id
        and decision.decision is EditorialDecisionType.ADOPT
        and decision.actor.strip()
        and decision.reason.strip()
        and candidate is not None
        and decision.candidate_id == candidate.id
    )
    checks.append(
        _check(
            "human_decision",
            CheckLevel.PASS if decision_ok else CheckLevel.BLOCK,
            "Human Adopt Decision 与 Candidate/Event 一致" if decision_ok else "Decision 不是指定 Candidate 的真实 Human Adopt",
            actor_present=bool(decision and decision.actor.strip()),
            reason_present=bool(decision and decision.reason.strip()),
        )
    )

    card = await session.scalar(
        select(EventCardRecord)
        .where(EventCardRecord.event_id == event_id)
        .order_by(EventCardRecord.created_at.desc())
        .limit(1)
    )
    pack = await session.scalar(
        select(EditorialPackRecord)
        .where(EditorialPackRecord.event_id == event_id)
        .order_by(EditorialPackRecord.created_at.desc())
        .limit(1)
    )
    card_pack_ok = bool(card and pack and pack.event_card_id == card.id)
    checks.append(
        _check(
            "card_pack",
            CheckLevel.PASS if card_pack_ok else CheckLevel.BLOCK,
            "Event Card / Editorial Pack provenance 一致" if card_pack_ok else "缺少一致的 Card / Pack",
        )
    )
    evidence["card_id"] = str(card.id) if card else None
    evidence["pack_id"] = str(pack.id) if pack else None

    draft = await session.get(EditorialDraftRecord, draft_id)
    draft_ok = bool(
        draft is not None
        and draft.event_id == event_id
        and draft.source_type is DraftSourceType.AI
        and draft.ai_invocation_id is not None
        and card is not None
        and pack is not None
        and draft.event_card_id == card.id
        and draft.editorial_pack_id == pack.id
    )
    checks.append(
        _check(
            "draft",
            CheckLevel.PASS if draft_ok else CheckLevel.BLOCK,
            "AI Draft 与 Event/Card/Pack provenance 一致" if draft_ok else "Draft 不属于该 Event/Card/Pack 或不是 AI Draft",
            draft_version=(draft.draft_version if draft else None),
            source_type=(draft.source_type.value if draft else None),
        )
    )
    draft_ref_count = 0
    invalid_ref_count = 0
    if draft is not None:
        draft_ref_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DraftClaimReferenceRecord)
                .where(DraftClaimReferenceRecord.draft_id == draft.id)
            )
            or 0
        )
        invalid_ref_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DraftClaimReferenceRecord)
                .join(EvidenceClaimRecord, EvidenceClaimRecord.id == DraftClaimReferenceRecord.claim_id)
                .where(
                    DraftClaimReferenceRecord.draft_id == draft.id,
                    EvidenceClaimRecord.event_id != event_id,
                )
            )
            or 0
        )
    refs_ok = draft_ref_count > 0 and invalid_ref_count == 0
    checks.append(
        _check(
            "draft_claim_refs",
            CheckLevel.PASS if refs_ok else CheckLevel.BLOCK,
            "Draft Claim references 属于同一 Event" if refs_ok else "Draft Claim reference 缺失或跨 Event",
            reference_count=draft_ref_count,
            invalid_reference_count=invalid_ref_count,
        )
    )

    draft_invocation = await verify_business_invocation(
        session,
        draft.ai_invocation_id,
    ) if draft is not None and draft.ai_invocation_id is not None else ValidationSummary(
        (_check("draft_invocation", CheckLevel.BLOCK, "AI Draft 缺少 Invocation"),)
    )
    checks.extend(draft_invocation.checks)
    evidence["draft_invocation_id"] = str(draft.ai_invocation_id) if draft and draft.ai_invocation_id else None

    failed = any(item.level is CheckLevel.BLOCK for item in checks)
    return E2EVerificationResult("FAIL" if failed else "PASS", tuple(checks), evidence)


__all__ = [
    "EXPECTED_MIGRATION_HEAD",
    "CheckLevel",
    "E2EVerificationResult",
    "M5DPreflightService",
    "MVPDoctorService",
    "ValidationCheck",
    "ValidationSummary",
    "verify_business_invocation",
    "verify_m5d_e2e",
]
