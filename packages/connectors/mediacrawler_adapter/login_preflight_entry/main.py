from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from playwright.async_api import async_playwright  # type: ignore[import-not-found]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read login-marker presence from an already-open local CDP browser."
    )
    parser.add_argument("--origin", required=True)
    parser.add_argument("--marker", action="append", required=True)
    parser.add_argument("--port", type=int, default=9222)
    return parser


async def _connect_existing(port: int) -> tuple[Any, Any]:
    playwright = await async_playwright().start()
    direct = f"ws://127.0.0.1:{port}/devtools/browser"
    try:
        browser = await playwright.chromium.connect_over_cdp(direct, timeout=30_000)
    except Exception:
        browser = await playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{port}", timeout=30_000
        )
    return playwright, browser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    playwright: Any | None = None
    try:
        playwright, browser = await _connect_existing(args.port)
        contexts = browser.contexts
        if not contexts:
            return {
                "status": "BLOCKED",
                "login_state": "unknown",
                "reason": "existing CDP browser has no reusable browser context",
            }
        cookies = await contexts[0].cookies([args.origin])
        names = {str(cookie.get("name", "")) for cookie in cookies}
        marker_present = any(marker in names for marker in args.marker)
        return {
            "status": "READY" if marker_present else "BLOCKED",
            "login_state": "valid" if marker_present else "requires_interaction",
            "reason": (
                "expected login-state marker is present; cookie values were not emitted"
                if marker_present
                else "expected login-state marker is absent; manual login is required"
            ),
        }
    except Exception:
        return {
            "status": "BLOCKED",
            "login_state": "unknown",
            "reason": "unable to inspect the existing local CDP browser",
        }
    finally:
        if playwright is not None:
            await playwright.stop()


def main() -> None:
    args = _parser().parse_args()
    payload = asyncio.run(_run(args))
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0 if payload["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
