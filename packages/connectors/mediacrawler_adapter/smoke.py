from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.common.config import Settings, get_settings
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.protocol import MediaCrawlerInvocation
from packages.connectors.mediacrawler_adapter.resilience import (
    MediaCrawlerResilienceRunner,
    ResumePageRunner,
)
from packages.connectors.mediacrawler_adapter.resilient_adapter import (
    MediaCrawlerResilienceAdapter,
)
from packages.connectors.registry import ConnectorRegistry

M2D_TARGET_PLATFORMS = ("bilibili", "zhihu", "weibo")
M2D_DEFERRED_PLATFORMS = ("douyin", "xiaohongshu", "kuaishou", "baidu_tieba")

MAX_SMOKE_ITEMS = 5
MAX_SMOKE_COMMENTS = 5
MAX_DAILY_SMOKE_RUNS = 3

PINNED_SEARCH_RESULT_FLOORS: dict[str, int] = {
    "bilibili": 20,
    "zhihu": 20,
    "weibo": 10,
}
BILIBILI_LOW_VOLUME_PAGE_SIZE_PATCH = True
ZHIHU_LOW_VOLUME_PAGE_SIZE_PATCH = True

LOGIN_STATE_MARKERS: dict[str, tuple[str, ...]] = {
    "bilibili": ("SESSDATA", "DedeUserID"),
    "zhihu": ("z_c0",),
    "weibo": ("SSOLoginState", "WBPSESS"),
}


class SmokeSafetyError(ValueError):
    """M2-D real-smoke request violates a deliberate safety boundary."""


@dataclass(slots=True, frozen=True)
class SmokePreparationAudit:
    platform: str
    login_methods: tuple[str, ...]
    login_state_markers: tuple[str, ...]
    requires_human_login: bool
    requires_stable_browser_profile: bool
    requires_visible_browser: bool
    concurrency: int
    ip_proxy_enabled: bool
    max_items: int
    max_comments_per_content: int
    subcomments: bool
    search_result_floor: int
    search_low_volume_ready: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "login_methods": list(self.login_methods),
            "login_state_markers": list(self.login_state_markers),
            "requires_human_login": self.requires_human_login,
            "requires_stable_browser_profile": self.requires_stable_browser_profile,
            "requires_visible_browser": self.requires_visible_browser,
            "concurrency": self.concurrency,
            "ip_proxy_enabled": self.ip_proxy_enabled,
            "max_items": self.max_items,
            "max_comments_per_content": self.max_comments_per_content,
            "subcomments": self.subcomments,
            "search_result_floor": self.search_result_floor,
            "search_low_volume_ready": self.search_low_volume_ready,
            "blockers": list(self.blockers),
        }


def audit_platform(platform: str) -> SmokePreparationAudit:
    if platform not in M2D_TARGET_PLATFORMS:
        raise SmokeSafetyError(f"{platform} is not an M2-D first-batch real-smoke platform")
    pinned_floor = PINNED_SEARCH_RESULT_FLOORS[platform]
    patched_low_volume = (
        platform == "bilibili" and BILIBILI_LOW_VOLUME_PAGE_SIZE_PATCH
    ) or (
        platform == "zhihu" and ZHIHU_LOW_VOLUME_PAGE_SIZE_PATCH
    )
    low_volume_ready = patched_low_volume or pinned_floor <= MAX_SMOKE_ITEMS
    effective_floor = 1 if low_volume_ready else pinned_floor
    blockers: list[str] = []
    if not low_volume_ready:
        blockers.append(
            f"pinned MediaCrawler search returns at least {pinned_floor} results per first page, "
            f"which exceeds the M2-D limit of {MAX_SMOKE_ITEMS}"
        )
    blockers.extend(
        (
            "real smoke requires a dedicated pre-authenticated low-value test account",
            "real smoke requires a stable visible browser profile controlled by the operator",
        )
    )
    return SmokePreparationAudit(
        platform=platform,
        login_methods=("qrcode", "cookie"),
        login_state_markers=LOGIN_STATE_MARKERS[platform],
        requires_human_login=True,
        requires_stable_browser_profile=True,
        requires_visible_browser=True,
        concurrency=1,
        ip_proxy_enabled=False,
        max_items=MAX_SMOKE_ITEMS,
        max_comments_per_content=MAX_SMOKE_COMMENTS,
        subcomments=False,
        search_result_floor=effective_floor,
        search_low_volume_ready=low_volume_ready,
        blockers=tuple(blockers),
    )


def validate_smoke_request(
    *,
    platform: str,
    mode: str,
    requested_limit: int,
    comment_limit: int,
    include_subcomments: bool,
) -> None:
    audit = audit_platform(platform)
    if requested_limit < 1 or requested_limit > MAX_SMOKE_ITEMS:
        raise SmokeSafetyError(
            f"requested_limit must be between 1 and {MAX_SMOKE_ITEMS} for M2-D real smoke"
        )
    if comment_limit < 0 or comment_limit > MAX_SMOKE_COMMENTS:
        raise SmokeSafetyError(
            f"comment_limit must be between 0 and {MAX_SMOKE_COMMENTS} for M2-D real smoke"
        )
    if include_subcomments:
        raise SmokeSafetyError("subcomments are disabled for M2-D real smoke")
    if mode == "detail" and requested_limit != 1:
        raise SmokeSafetyError("detail smoke must request exactly one public content item")
    if mode == "comments" and requested_limit != 1:
        raise SmokeSafetyError("comments smoke must be scoped to exactly one main content item")
    if mode == "search" and not audit.search_low_volume_ready:
        raise SmokeSafetyError(
            "pinned MediaCrawler search page size exceeds the M2-D low-volume gate; "
            "do not access the platform until the compatibility issue is explicitly resolved"
        )
    if mode not in {"detail", "search", "comments"}:
        raise SmokeSafetyError("M2-D smoke only permits detail, search, and comments modes")


class M2DSmokeSubprocessRunner(ResumePageRunner):
    """Dedicated real-smoke runner; normal MediaCrawler runtime behavior is unchanged."""

    def __init__(self, *, vendor_home: Path, python_executable: str) -> None:
        self.vendor_home = vendor_home.expanduser().resolve()
        bridge_home = Path(__file__).with_name("smoke_entry").resolve()
        super().__init__(home=bridge_home, python_executable=python_executable)

    def _build_command(
        self,
        entrypoint: Path,
        data_root: Path,
        invocation: MediaCrawlerInvocation,
    ) -> list[str]:
        command = super()._build_command(entrypoint, data_root, invocation)
        command.extend(["--max_concurrency_num", "1", "--headless", "false"])
        return command

    def _safe_environment(self, data_root: Path) -> dict[str, str]:
        environment = super()._safe_environment(data_root)
        environment.update(
            {
                "AI_EDITORIAL_MEDIACRAWLER_HOME": str(self.vendor_home),
                "AI_EDITORIAL_M2D_SMOKE": "1",
            }
        )
        return environment


def build_smoke_registry(settings: Settings | None = None) -> ConnectorRegistry:
    resolved = settings or get_settings()
    page_runner = M2DSmokeSubprocessRunner(
        vendor_home=Path(resolved.mediacrawler_home),
        python_executable=resolved.mediacrawler_python,
    )
    resilience_runner = MediaCrawlerResilienceRunner(
        page_runner,
        max_technical_attempts=3,
    )
    connector = MediaCrawlerConnector(
        MediaCrawlerResilienceAdapter(resilience_runner, settings=resolved)
    )
    registry = ConnectorRegistry()
    registry.register("mediacrawler", lambda: connector)
    return registry


__all__ = [
    "BILIBILI_LOW_VOLUME_PAGE_SIZE_PATCH",
    "LOGIN_STATE_MARKERS",
    "M2D_DEFERRED_PLATFORMS",
    "M2D_TARGET_PLATFORMS",
    "MAX_DAILY_SMOKE_RUNS",
    "MAX_SMOKE_COMMENTS",
    "MAX_SMOKE_ITEMS",
    "M2DSmokeSubprocessRunner",
    "PINNED_SEARCH_RESULT_FLOORS",
    "SmokePreparationAudit",
    "SmokeSafetyError",
    "ZHIHU_LOW_VOLUME_PAGE_SIZE_PATCH",
    "audit_platform",
    "build_smoke_registry",
    "validate_smoke_request",
]
