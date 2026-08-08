from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from packages.common.config import get_settings
from packages.connectors.mediacrawler_adapter.runner import SAFE_ENV_NAMES
from packages.connectors.mediacrawler_adapter.smoke import (
    LOGIN_STATE_MARKERS,
    M2D_TARGET_PLATFORMS,
)
from packages.database.session import dispose_database
from scripts import check_m2_smoke_environment as environment_preflight

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGIN_HELPER_ENTRYPOINT = (
    REPO_ROOT
    / "packages"
    / "connectors"
    / "mediacrawler_adapter"
    / "login_preflight_entry"
    / "main.py"
)
_CONFIRMATION = "M2D_LOGIN_PREFLIGHT"
_PLATFORM_ORIGINS = {
    "bilibili": "https://www.bilibili.com",
    "zhihu": "https://www.zhihu.com",
    "weibo": "https://m.weibo.cn",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M2-D login-only preflight. Reads marker presence from an already-open local CDP "
            "browser; never navigates a page or runs content collection."
        )
    )
    parser.add_argument("--platform", choices=M2D_TARGET_PLATFORMS, required=True)
    parser.add_argument("--connector-instance-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--mode", choices=("detail", "search", "comments"), required=True)
    parser.add_argument("--requested-limit", type=int, default=1)
    parser.add_argument("--comment-limit", type=int, default=0)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _safe_subprocess_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in SAFE_ENV_NAMES
    }


def _human_gate(actor: str, confirmation: str) -> str | None:
    settings = get_settings()
    if os.environ.get("CI") or settings.app_env.strip().casefold() in {
        "ci",
        "mock",
        "test",
    }:
        return "login-only preflight is forbidden in CI/Mock/Test environments"
    normalized_actor = actor.strip()
    if not normalized_actor or normalized_actor.casefold() in {"ci", "mock", "automation"}:
        return "login-only preflight requires an explicit human actor"
    if confirmation != _CONFIRMATION:
        return f"login-only preflight requires --confirm {_CONFIRMATION}"
    return None


async def _local_login_marker_check(platform: str) -> dict[str, str]:
    settings = get_settings()
    command = [
        settings.mediacrawler_python,
        str(LOGIN_HELPER_ENTRYPOINT),
        "--origin",
        _PLATFORM_ORIGINS[platform],
        "--port",
        str(environment_preflight.EXPECTED_CDP_PORT),
    ]
    for marker in LOGIN_STATE_MARKERS[platform]:
        command.extend(["--marker", marker])
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_safe_subprocess_environment(),
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    except (OSError, TimeoutError):
        return {
            "status": "BLOCKED",
            "login_state": "unknown",
            "reason": "local CDP login-state helper could not run",
        }
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {
            "status": "BLOCKED",
            "login_state": "unknown",
            "reason": "local CDP login-state helper returned an invalid result",
        }
    if not isinstance(payload, dict):
        return {
            "status": "BLOCKED",
            "login_state": "unknown",
            "reason": "local CDP login-state helper returned an invalid result",
        }
    status = payload.get("status")
    login_state = payload.get("login_state")
    reason = payload.get("reason")
    if (
        status not in {"READY", "BLOCKED"}
        or not isinstance(login_state, str)
        or not isinstance(reason, str)
    ):
        return {
            "status": "BLOCKED",
            "login_state": "unknown",
            "reason": "local CDP login-state helper returned an invalid result",
        }
    return {"status": status, "login_state": login_state, "reason": reason}


async def run_login_preflight(args: argparse.Namespace) -> dict[str, object]:
    gate_error = _human_gate(args.actor, args.confirm)
    if gate_error is not None:
        return {
            "status": "BLOCKED",
            "real_network_started": False,
            "login_state": "unknown",
            "reasons": [gate_error],
        }

    environment = await environment_preflight.run_preflight(args)
    if environment["status"] != "READY":
        reasons = [
            str(check["reason"])
            for check in environment["checks"]
            if check["status"] == "BLOCKED"
        ]
        return {
            "status": "BLOCKED",
            "real_network_started": False,
            "login_state": "unknown",
            "reasons": reasons,
        }

    login = await _local_login_marker_check(args.platform)
    return {
        "status": login["status"],
        "real_network_started": False,
        "login_state": login["login_state"],
        "reasons": [login["reason"]],
    }


def main() -> None:
    args = _parser().parse_args()
    try:
        payload = asyncio.run(run_login_preflight(args))
    except Exception:
        payload = {
            "status": "BLOCKED",
            "real_network_started": False,
            "login_state": "unknown",
            "reasons": ["unexpected local login-only preflight failure"],
        }
    finally:
        try:
            asyncio.run(dispose_database())
        except Exception:
            pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
