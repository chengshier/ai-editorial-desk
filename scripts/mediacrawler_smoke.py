from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select

from packages.collector_runtime import CollectionTask, CollectorRuntime, TriggerType
from packages.common.config import get_settings
from packages.connectors.mediacrawler_adapter.account_profile import (
    BrowserProfileResolver,
    MediaCrawlerAccountContext,
)
from packages.connectors.mediacrawler_adapter.protocol import LoginState
from packages.connectors.mediacrawler_adapter.smoke import (
    M2D_TARGET_PLATFORMS,
    MAX_DAILY_SMOKE_RUNS,
    SmokeSafetyError,
    audit_platform,
    build_smoke_registry,
    validate_smoke_request,
)
from packages.database.models import (
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunTriggerType,
    PlatformAccount,
    Source,
)
from packages.database.session import dispose_database, get_async_sessionmaker

_CONFIRMATION = "M2D_REAL_SMOKE"


def _failure_diagnostic_summary(metadata: object) -> dict[str, object] | None:
    """Return the CLI-safe projection; never echo arbitrary run metadata."""
    if not isinstance(metadata, dict):
        return None
    category = metadata.get("failure_category")
    code = metadata.get("failure_code")
    risk_stop_required = metadata.get("platform_risk_detected")
    if not isinstance(category, str) or not isinstance(code, str):
        return None
    return {
        "category": category,
        "code": code,
        "risk_stop_required": bool(risk_stop_required),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M2-D MediaCrawler low-volume real-smoke harness"
    )
    parser.add_argument("--platform", choices=M2D_TARGET_PLATFORMS)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--connector-instance-id")
    parser.add_argument("--source-id")
    parser.add_argument("--account-id")
    parser.add_argument("--mode", choices=("detail", "search", "comments"))
    parser.add_argument("--requested-limit", type=int, default=1)
    parser.add_argument("--actor")
    parser.add_argument("--confirm")
    return parser


def _uuid(value: str | None, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise SmokeSafetyError(f"{name} must be a valid UUID") from exc


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _audit(platform: str | None) -> int:
    platforms = (platform,) if platform else M2D_TARGET_PLATFORMS
    _print(
        {
            "status": "preparation_audit",
            "real_network_started": False,
            "platforms": [audit_platform(item).to_dict() for item in platforms],
        }
    )
    return 0


def _require_explicit_real_execution(actor: str | None, confirmation: str | None) -> str:
    settings = get_settings()
    if os.environ.get("CI") or settings.app_env.strip().casefold() in {"ci", "mock", "test"}:
        raise SmokeSafetyError("real smoke is forbidden in CI/Mock/Test environments")
    normalized_actor = (actor or "").strip()
    if not normalized_actor or normalized_actor.casefold() in {"ci", "mock", "automation"}:
        raise SmokeSafetyError("real smoke requires an explicit human actor")
    if confirmation != _CONFIRMATION:
        raise SmokeSafetyError(
            f"real smoke requires --confirm {_CONFIRMATION}; audit mode never needs confirmation"
        )
    return normalized_actor


async def _execute(args: argparse.Namespace) -> int:
    actor = _require_explicit_real_execution(args.actor, args.confirm)
    if args.platform is None or args.mode is None:
        raise SmokeSafetyError("--platform and --mode are required for --execute")

    instance_id = _uuid(args.connector_instance_id, "connector-instance-id")
    source_id = _uuid(args.source_id, "source-id")
    account_id = _uuid(args.account_id, "account-id")
    session_factory = get_async_sessionmaker()
    settings = get_settings()

    async with session_factory() as session:
        instance = await session.get(ConnectorInstance, instance_id)
        source = await session.get(Source, source_id)
        account = await session.get(PlatformAccount, account_id)
        if instance is None or source is None or account is None:
            raise SmokeSafetyError("smoke instance/source/account must already exist")
        definition = await session.get(ConnectorDefinition, instance.definition_id)
        if definition is None:
            raise SmokeSafetyError("smoke Connector Definition does not exist")
        if (
            definition.connector_type != "mediacrawler"
            or definition.platform != args.platform
        ):
            raise SmokeSafetyError(
                "smoke platform does not match the selected Connector Definition"
            )
        if (
            source.connector_instance_id != instance.id
            or account.connector_instance_id != instance.id
        ):
            raise SmokeSafetyError("smoke source/account must belong to the selected instance")
        if source.mode != args.mode:
            raise SmokeSafetyError("smoke mode must match the configured Source mode")
        if not account.browser_profile_ref:
            raise SmokeSafetyError("real smoke requires a stable browser_profile_ref")

        source_config = dict(source.config)
        include_comments = (
            bool(source_config.get("include_comments", False))
            or args.mode == "comments"
        )
        raw_comment_limit = source_config.get("comment_limit", 0)
        comment_limit = raw_comment_limit if isinstance(raw_comment_limit, int) else 0
        include_subcomments = bool(source_config.get("include_subcomments", False))
        validate_smoke_request(
            platform=args.platform,
            mode=args.mode,
            requested_limit=args.requested_limit,
            comment_limit=comment_limit if include_comments else 0,
            include_subcomments=include_subcomments,
        )

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
        account_context.ensure_runnable()
        BrowserProfileResolver(Path(settings.mediacrawler_profile_root)).resolve(account_context)

        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_runs = int(
            await session.scalar(
                select(func.count())
                .select_from(ConnectorRun)
                .where(
                    ConnectorRun.platform_account_id == account_id,
                    ConnectorRun.created_at >= day_start,
                    ConnectorRun.trigger_type.in_(
                        (ConnectorRunTriggerType.TEST, ConnectorRunTriggerType.MANUAL)
                    ),
                )
            )
            or 0
        )
        if daily_runs >= MAX_DAILY_SMOKE_RUNS:
            raise SmokeSafetyError("daily real-smoke run limit has been reached for this account")
        await session.rollback()

    runtime = CollectorRuntime(
        session_factory=session_factory,
        registry=build_smoke_registry(settings),
    )
    result = await runtime.execute(
        CollectionTask(
            task_id=uuid4(),
            connector_instance_id=instance_id,
            source_id=source_id,
            platform_account_id=account_id,
            mode=args.mode,
            requested_limit=args.requested_limit,
            checkpoint_version=None,
            trigger_type=TriggerType.TEST,
            triggered_by=actor,
            created_at=datetime.now(UTC),
        )
    )
    async with session_factory() as session:
        run = await session.get(ConnectorRun, result.run_id)
        diagnostic = _failure_diagnostic_summary(
            run.run_metadata.get("subprocess_diagnostic") if run is not None else None
        )
    payload: dict[str, object] = {
        "run_id": str(result.run_id),
        "status": result.status.value,
        "collected": result.collected_count,
        "inserted": result.inserted_count,
        "duplicates": result.duplicate_count,
        "failed": result.failed_count,
    }
    if diagnostic is not None:
        payload["failure_diagnostic"] = diagnostic
    _print(payload)
    return 0


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.execute:
            return await _execute(args)
        return _audit(args.platform)
    finally:
        await dispose_database()


def main() -> None:
    args = _parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except SmokeSafetyError as exc:
        _print({"status": "blocked", "reason": str(exc), "real_network_started": False})
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
