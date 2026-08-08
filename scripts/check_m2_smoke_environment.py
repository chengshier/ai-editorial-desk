from __future__ import annotations

import argparse
import asyncio
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from packages.collector_runtime.budget_repository import CollectionBudgetRepository
from packages.common.config import Settings, get_settings
from packages.connectors.mediacrawler_adapter.account_profile import (
    BrowserProfileResolutionError,
    BrowserProfileResolver,
    MediaCrawlerAccountContext,
)
from packages.connectors.mediacrawler_adapter.protocol import LoginState
from packages.connectors.mediacrawler_adapter.smoke import (
    M2D_TARGET_PLATFORMS,
    SmokeSafetyError,
    audit_platform,
    validate_smoke_request,
)
from packages.database.models import (
    CollectionBudgetUsage,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorValidationRecord,
    ConnectorValidationStatus,
    PlatformAccount,
    PlatformRiskEvent,
    Source,
)
from packages.database.session import dispose_database, get_async_sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_MEDIACRAWLER_COMMIT = "071c8c0acaece3e82f2532cffb19faeddc9ec1c3"
EXPECTED_DEFINITION_COUNT = 11
EXPECTED_MEDIACRAWLER_DEFINITION_COUNT = 7
EXPECTED_CDP_PORT = 9222

SAFE_MAX_RUNS_PER_DAY = 3
SAFE_MAX_ITEMS_PER_RUN = 5
SAFE_MAX_ITEMS_PER_DAY = 15
SAFE_MAX_COMMENTS_PER_RUN = 5
SAFE_MAX_COMMENTS_PER_DAY = 15
SAFE_MAX_CONCURRENCY = 1


@dataclass(slots=True, frozen=True)
class PreflightCheck:
    name: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "reason": self.reason}


def _ready(name: str, reason: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="READY", reason=reason)


def _blocked(name: str, reason: str) -> PreflightCheck:
    return PreflightCheck(name=name, status="BLOCKED", reason=reason)


def _safe_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _cdp_port_ready(host: str = "127.0.0.1", port: int = EXPECTED_CDP_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _pinned_vendor_record_ready(repo_root: Path) -> bool:
    vendor_home = repo_root / "third_party" / "MediaCrawler"
    local_changes = repo_root / "docs" / "MEDIACRAWLER_LOCAL_CHANGES.md"
    if not (vendor_home / "main.py").is_file() or not (vendor_home / "LICENSE").is_file():
        return False
    try:
        documentation = local_changes.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return PINNED_MEDIACRAWLER_COMMIT in documentation


def _profile_root_check(settings: Settings) -> PreflightCheck:
    profile_root = Path(settings.mediacrawler_profile_root).expanduser()
    if profile_root.is_dir():
        return _ready("profile_root", "MediaCrawler profile root exists")
    return _blocked("profile_root", "MediaCrawler profile root does not exist")


def _safe_budget_shape(budget: Any) -> bool:
    return (
        bool(budget.enabled)
        and int(budget.max_runs_per_day) <= SAFE_MAX_RUNS_PER_DAY
        and int(budget.max_items_per_run) <= SAFE_MAX_ITEMS_PER_RUN
        and int(budget.max_items_per_day) <= SAFE_MAX_ITEMS_PER_DAY
        and int(budget.max_comments_per_run) <= SAFE_MAX_COMMENTS_PER_RUN
        and int(budget.max_comments_per_day) <= SAFE_MAX_COMMENTS_PER_DAY
        and int(budget.max_concurrency) == SAFE_MAX_CONCURRENCY
    )


def _budget_allows_request(
    budget: Any,
    *,
    requested_limit: int,
    comment_limit: int,
) -> bool:
    return (
        bool(budget.enabled)
        and requested_limit <= int(budget.max_items_per_run)
        and comment_limit <= int(budget.max_comments_per_run)
        and int(budget.max_concurrency) >= 1
    )


def _budget_usage_projection_allows(
    budget: Any,
    usage: Any | None,
    *,
    requested_limit: int,
    comment_limit: int,
) -> bool:
    runs_reserved = int(usage.runs_reserved) if usage is not None else 0
    items_used = int(usage.items_used) if usage is not None else 0
    items_reserved = int(usage.items_reserved) if usage is not None else 0
    comments_used = int(usage.comments_used) if usage is not None else 0
    comments_reserved = int(usage.comments_reserved) if usage is not None else 0
    active_runs = int(usage.active_runs) if usage is not None else 0
    return (
        runs_reserved + 1 <= int(budget.max_runs_per_day)
        and items_used + items_reserved + requested_limit
        <= int(budget.max_items_per_day)
        and comments_used + comments_reserved + comment_limit
        <= int(budget.max_comments_per_day)
        and active_runs + 1 <= int(budget.max_concurrency)
    )


def _latest_validation_status(
    record: ConnectorValidationRecord | None,
    *,
    implementation_version: str,
) -> ConnectorValidationStatus:
    if record is None:
        return ConnectorValidationStatus.NOT_TESTED
    if record.implementation_version != implementation_version:
        return ConnectorValidationStatus.EXPIRED
    return record.status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only M2-D smoke environment preflight. It never logs in, opens a platform, "
            "starts collection runtime execution, or inspects credential contents."
        )
    )
    parser.add_argument("--platform", choices=M2D_TARGET_PLATFORMS, required=True)
    parser.add_argument("--connector-instance-id")
    parser.add_argument("--source-id")
    parser.add_argument("--account-id")
    parser.add_argument("--mode", choices=("detail", "search", "comments"), required=True)
    parser.add_argument("--requested-limit", type=int, default=1)
    parser.add_argument("--comment-limit", type=int, default=0)
    return parser


def _migration_check(repo_root: Path, database_versions: set[str]) -> PreflightCheck:
    try:
        config = AlembicConfig(str(repo_root / "alembic.ini"))
        heads = set(ScriptDirectory.from_config(config).get_heads())
    except Exception:
        return _blocked("migration", "unable to read local Alembic head metadata")
    if not heads:
        return _blocked("migration", "local Alembic head metadata is empty")
    if database_versions != heads:
        return _blocked("migration", "database migration revision does not match local head")
    return _ready("migration", "database revision matches local Alembic head")


async def _database_checks(
    *,
    repo_root: Path,
    settings: Settings,
    platform: str,
    connector_instance_id: UUID | None,
    source_id: UUID | None,
    account_id: UUID | None,
    mode: str,
    requested_limit: int,
    comment_limit: int,
) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return [_blocked("database", "DATABASE_URL is not reachable")]
        checks.append(_ready("database", "DATABASE_URL is reachable"))

        try:
            revision_rows = await session.execute(
                text("SELECT version_num FROM alembic_version")
            )
            database_versions = {str(row[0]) for row in revision_rows.all()}
        except Exception:
            database_versions = set()
        checks.append(_migration_check(repo_root, database_versions))

        total_definitions = int(
            await session.scalar(select(func.count()).select_from(ConnectorDefinition)) or 0
        )
        mc_definitions = int(
            await session.scalar(
                select(func.count())
                .select_from(ConnectorDefinition)
                .where(ConnectorDefinition.connector_type == "mediacrawler")
            )
            or 0
        )
        if (
            total_definitions == EXPECTED_DEFINITION_COUNT
            and mc_definitions == EXPECTED_MEDIACRAWLER_DEFINITION_COUNT
        ):
            checks.append(
                _ready(
                    "definitions",
                    "11 connector definitions exist, including 7 MediaCrawler platforms",
                )
            )
        else:
            checks.append(
                _blocked(
                    "definitions",
                    "connector definitions are not synchronized to the expected 11/7 state",
                )
            )

        definition = await session.scalar(
            select(ConnectorDefinition).where(
                ConnectorDefinition.connector_type == "mediacrawler",
                ConnectorDefinition.platform == platform,
            )
        )
        if definition is None:
            checks.append(
                _blocked(
                    "platform_definition",
                    "MediaCrawler platform definition is missing",
                )
            )
            return checks
        if not definition.is_enabled:
            checks.append(
                _blocked("platform_definition", "platform definition is disabled")
            )
        else:
            checks.append(
                _ready("platform_definition", "platform definition is enabled")
            )

        if connector_instance_id is None:
            checks.append(
                _blocked(
                    "connector_instance",
                    "connector instance id is missing or invalid",
                )
            )
            return checks
        instance = await session.get(ConnectorInstance, connector_instance_id)
        if instance is None or instance.definition_id != definition.id:
            checks.append(
                _blocked(
                    "connector_instance",
                    "connector instance is missing or mismatched",
                )
            )
            return checks
        if not instance.enabled or instance.status != "active":
            checks.append(
                _blocked(
                    "connector_instance",
                    "connector instance is not enabled and active",
                )
            )
        else:
            checks.append(
                _ready(
                    "connector_instance",
                    "connector instance is enabled and active",
                )
            )

        if source_id is None:
            checks.append(_blocked("source", "source id is missing or invalid"))
            return checks
        source = await session.get(Source, source_id)
        if source is None or source.connector_instance_id != instance.id:
            checks.append(
                _blocked(
                    "source",
                    "source is missing or does not belong to the instance",
                )
            )
            return checks
        if (
            source.source_type != "mediacrawler"
            or source.mode != mode
            or not source.enabled
            or source.status != "active"
        ):
            checks.append(
                _blocked(
                    "source",
                    "source type/mode/status/enabled state does not match this preflight",
                )
            )
        else:
            checks.append(
                _ready("source", "source is active and matches the requested mode")
            )
        include_subcomments = bool(dict(source.config).get("include_subcomments", False))
        try:
            validate_smoke_request(
                platform=platform,
                mode=mode,
                requested_limit=requested_limit,
                comment_limit=comment_limit,
                include_subcomments=include_subcomments,
            )
        except SmokeSafetyError as exc:
            checks.append(_blocked("smoke_limits", str(exc)))
        else:
            checks.append(
                _ready(
                    "smoke_limits",
                    "requested limits satisfy the M2-D fail-closed gate",
                )
            )

        if account_id is None:
            checks.append(_blocked("account", "platform account id is missing or invalid"))
            return checks
        account = await session.get(PlatformAccount, account_id)
        if (
            account is None
            or account.connector_instance_id != instance.id
            or account.platform != platform
        ):
            checks.append(_blocked("account", "platform account is missing or mismatched"))
            return checks
        account_context = MediaCrawlerAccountContext(
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
            account_context.ensure_runnable()
        except ValueError:
            checks.append(_blocked("account", "platform account state blocks execution"))
        else:
            credential_note = (
                "credential reference is configured; value hidden"
                if account.credential_ref
                else (
                    "credential reference is not configured; "
                    "manual browser profile login is expected"
                )
            )
            checks.append(
                _ready(
                    "account",
                    f"platform account is runnable; {credential_note}",
                )
            )

        try:
            BrowserProfileResolver(
                Path(settings.mediacrawler_profile_root)
            ).resolve(account_context)
        except (BrowserProfileResolutionError, ValueError):
            checks.append(
                _blocked(
                    "browser_profile",
                    "configured browser profile cannot be safely resolved",
                )
            )
        else:
            checks.append(
                _ready(
                    "browser_profile",
                    "configured browser profile resolves under the controlled root",
                )
            )

        budgets = await CollectionBudgetRepository(session).applicable(
            platform=platform,
            connector_instance_id=instance.id,
            platform_account_id=account.id,
            source_id=source.id,
        )
        budget_usage_ready = bool(budgets)
        if budgets:
            now = datetime.now(UTC)
            for budget in budgets:
                try:
                    usage_date = now.astimezone(ZoneInfo(budget.timezone)).date()
                except ZoneInfoNotFoundError:
                    budget_usage_ready = False
                    break
                usage = await session.scalar(
                    select(CollectionBudgetUsage).where(
                        CollectionBudgetUsage.budget_id == budget.id,
                        CollectionBudgetUsage.usage_date == usage_date,
                    )
                )
                if not _budget_usage_projection_allows(
                    budget,
                    usage,
                    requested_limit=requested_limit,
                    comment_limit=comment_limit,
                ):
                    budget_usage_ready = False
                    break

        if not budgets:
            checks.append(
                _blocked(
                    "budget",
                    "no explicit enabled budget applies; preflight will not create one",
                )
            )
        elif not all(
            _budget_allows_request(
                budget,
                requested_limit=requested_limit,
                comment_limit=comment_limit,
            )
            for budget in budgets
        ):
            checks.append(
                _blocked(
                    "budget",
                    "an applicable budget would reject the requested low-volume run",
                )
            )
        elif not any(_safe_budget_shape(budget) for budget in budgets):
            checks.append(
                _blocked(
                    "budget",
                    "no applicable budget is constrained to the M2-D low-volume safety caps",
                )
            )
        elif not budget_usage_ready:
            checks.append(
                _blocked(
                    "budget",
                    "current daily budget usage would reject the requested low-volume run",
                )
            )
        else:
            checks.append(
                _ready(
                    "budget",
                    "configured caps and current daily usage allow this low-volume run",
                )
            )

        unresolved_risks = int(
            await session.scalar(
                select(func.count())
                .select_from(PlatformRiskEvent)
                .where(
                    PlatformRiskEvent.platform_account_id == account.id,
                    PlatformRiskEvent.platform == platform,
                    PlatformRiskEvent.resolved_at.is_(None),
                )
            )
            or 0
        )
        if unresolved_risks:
            checks.append(
                _blocked(
                    "risk_guard",
                    "unresolved platform risk events exist for this account",
                )
            )
        else:
            checks.append(
                _ready(
                    "risk_guard",
                    "no unresolved platform risk event is recorded for this account",
                )
            )

        validation = await session.scalar(
            select(ConnectorValidationRecord)
            .where(
                ConnectorValidationRecord.connector_type == "mediacrawler",
                ConnectorValidationRecord.platform == platform,
            )
            .order_by(
                ConnectorValidationRecord.created_at.desc(),
                ConnectorValidationRecord.id.desc(),
            )
            .limit(1)
        )
        validation_status = _latest_validation_status(
            validation,
            implementation_version=definition.implementation_version,
        )
        checks.append(
            _ready(
                "validation",
                (
                    f"current validation status is {validation_status.value}; "
                    "preflight does not modify it"
                ),
            )
        )
        await session.rollback()
    return checks


async def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[PreflightCheck] = []

    if _pinned_vendor_record_ready(REPO_ROOT):
        checks.append(
            _ready(
                "pinned_vendor",
                "pinned MediaCrawler commit record and vendored entry files are present",
            )
        )
    else:
        checks.append(
            _blocked(
                "pinned_vendor",
                "pinned MediaCrawler commit record or vendored entry files are missing",
            )
        )

    audit = audit_platform(args.platform)
    if args.mode == "search" and not audit.search_low_volume_ready:
        checks.append(
            _blocked(
                "platform_search_gate",
                "platform has no evidenced <=5 real search request size",
            )
        )
    else:
        checks.append(
            _ready(
                "platform_search_gate",
                "platform/mode passes the current engineering low-volume gate",
            )
        )

    if audit.ip_proxy_enabled:
        checks.append(_blocked("proxy", "M2-D smoke proxy must remain disabled"))
    else:
        checks.append(_ready("proxy", "M2-D smoke proxy is disabled"))

    settings: Settings
    try:
        settings = get_settings()
    except Exception:
        checks.append(
            _blocked(
                "settings",
                "local application settings are incomplete or invalid",
            )
        )
        return _result(checks)
    checks.append(
        _ready(
            "settings",
            "local application settings loaded without exposing secret values",
        )
    )
    checks.append(_profile_root_check(settings))

    if _cdp_port_ready():
        checks.append(_ready("cdp", "localhost CDP port 9222 accepts a TCP connection"))
    else:
        checks.append(_blocked("cdp", "localhost CDP port 9222 is not listening"))

    checks.extend(
        await _database_checks(
            repo_root=REPO_ROOT,
            settings=settings,
            platform=args.platform,
            connector_instance_id=_safe_uuid(args.connector_instance_id),
            source_id=_safe_uuid(args.source_id),
            account_id=_safe_uuid(args.account_id),
            mode=args.mode,
            requested_limit=args.requested_limit,
            comment_limit=args.comment_limit,
        )
    )
    return _result(checks)


def _result(checks: list[PreflightCheck]) -> dict[str, Any]:
    overall = (
        "READY"
        if checks and all(item.status == "READY" for item in checks)
        else "BLOCKED"
    )
    return {
        "status": overall,
        "real_network_started": False,
        "checks": [item.to_dict() for item in checks],
    }


def main() -> None:
    args = _parser().parse_args()
    try:
        payload = asyncio.run(run_preflight(args))
    except Exception:
        payload = _result([_blocked("preflight", "unexpected local preflight failure")])
    finally:
        try:
            asyncio.run(dispose_database())
        except Exception:
            pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
