from __future__ import annotations

import asyncio
import importlib
import os
import re
import sys
from pathlib import Path
from types import MethodType
from typing import Any

_TARGET_LOGIN_PATCHES: dict[str, tuple[str, str]] = {
    "bili": ("media_platform.bilibili.core", "BilibiliLogin"),
    "zhihu": ("media_platform.zhihu.core", "ZhiHuLogin"),
    "wb": ("media_platform.weibo.core", "WeiboLogin"),
}
_SAFE_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")


def _safe_import_error_marker(exc: ImportError) -> str:
    module = getattr(exc, "name", None)
    safe_module = (
        module
        if isinstance(module, str) and _SAFE_MODULE_NAME.fullmatch(module)
        else "unknown"
    )
    reason = "MODULE_NOT_FOUND" if isinstance(exc, ModuleNotFoundError) else "IMPORT_FAILED"
    return (
        "AI_EDITORIAL_SAFE_IMPORT_ERROR "
        f"exception_type={type(exc).__name__} module={safe_module} reason={reason}"
    )


class _BlockedInteractiveLogin:
    """Never initiate QR, phone, or cookie login from an automated smoke process."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def begin(self) -> None:
        raise RuntimeError(
            "AUTH_REQUIRED: dedicated test browser profile must be authenticated manually"
        )


def _vendor_home() -> Path:
    raw = os.environ.get("AI_EDITORIAL_MEDIACRAWLER_HOME", "").strip()
    if not raw:
        raise RuntimeError("M2D_SMOKE_CONFIGURATION_ERROR: MediaCrawler home is missing")
    home = Path(raw).expanduser().resolve()
    if not (home / "main.py").is_file():
        raise RuntimeError("M2D_SMOKE_CONFIGURATION_ERROR: MediaCrawler entrypoint is missing")
    return home


def _enforce_safe_config(config: Any, args: Any) -> None:
    if os.environ.get("AI_EDITORIAL_M2D_SMOKE") != "1":
        raise RuntimeError("M2D_SMOKE_CONFIGURATION_ERROR: explicit smoke mode is required")
    if config.PLATFORM not in _TARGET_LOGIN_PATCHES:
        raise RuntimeError("M2D_SMOKE_TARGET_ERROR: platform is outside the first validation batch")
    if bool(getattr(args, "get_sub_comment", False)):
        raise RuntimeError("M2D_SMOKE_SAFETY_ERROR: subcomments are disabled")

    config.ENABLE_IP_PROXY = False
    config.MAX_CONCURRENCY_NUM = 1
    config.HEADLESS = False
    config.CDP_HEADLESS = False
    config.ENABLE_CDP_MODE = True
    config.CDP_CONNECT_EXISTING = True
    config.ENABLE_GET_SUB_COMMENTS = False
    config.AUTO_CLOSE_BROWSER = False


def _patch_interactive_login(platform_code: str) -> None:
    module_name, class_name = _TARGET_LOGIN_PATCHES[platform_code]
    core_module = importlib.import_module(module_name)
    setattr(core_module, class_name, _BlockedInteractiveLogin)


def _block_standard_browser_fallback(crawler: Any) -> None:
    async def blocked_launch_browser(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        del self, args, kwargs
        raise RuntimeError(
            "M2D_SMOKE_CDP_REQUIRED: standard browser fallback is disabled"
        )

    crawler.launch_browser = MethodType(blocked_launch_browser, crawler)


async def _run() -> None:
    home = _vendor_home()
    os.chdir(home)
    sys.path.insert(0, str(home))

    cmd_arg = importlib.import_module("cmd_arg")
    config = importlib.import_module("config")
    vendored_main = importlib.import_module("main")

    args = await cmd_arg.parse_cmd()
    if bool(getattr(args, "init_db", False)):
        raise RuntimeError("M2D_SMOKE_SAFETY_ERROR: database initialization is disabled")

    _enforce_safe_config(config, args)
    _patch_interactive_login(config.PLATFORM)

    crawler = vendored_main.CrawlerFactory.create_crawler(platform=config.PLATFORM)
    _block_standard_browser_fallback(crawler)
    await crawler.start()


def main() -> None:
    try:
        asyncio.run(_run())
    except ImportError as exc:
        print(_safe_import_error_marker(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
