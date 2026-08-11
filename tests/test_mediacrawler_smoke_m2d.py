from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.connectors.definitions.manifest import (
    CONNECTOR_DEFINITIONS,
    M2D_DEFAULT_ENABLED_PLATFORMS,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
)
from packages.connectors.mediacrawler_adapter.smoke import (
    BILIBILI_LOW_VOLUME_PAGE_SIZE_PATCH,
    M2D_DEFERRED_PLATFORMS,
    M2D_TARGET_PLATFORMS,
    MAX_SMOKE_COMMENTS,
    MAX_SMOKE_ITEMS,
    PINNED_SEARCH_RESULT_FLOORS,
    ZHIHU_LOW_VOLUME_PAGE_SIZE_PATCH,
    M2DSmokeSubprocessRunner,
    SmokeSafetyError,
    audit_platform,
    validate_smoke_request,
)
from packages.connectors.mediacrawler_adapter.smoke_entry.main import (
    _BlockedInteractiveLogin,
    _enforce_safe_config,
    _safe_import_error_marker,
)
from scripts.mediacrawler_smoke import _failure_diagnostic_summary


def _invocation() -> MediaCrawlerInvocation:
    return MediaCrawlerInvocation(
        run_id=uuid4(),
        platform=MediaCrawlerPlatform.BILIBILI,
        mode=MediaCrawlerMode.DETAIL,
        source_id=uuid4(),
        content_ids=("BV1fixture",),
        requested_limit=1,
        comment_limit=5,
        include_comments=True,
        include_subcomments=False,
        timeout_seconds=60,
    )


def test_first_batch_audit_releases_only_supported_low_volume_search_gates() -> None:
    assert M2D_TARGET_PLATFORMS == ("bilibili", "zhihu", "weibo")
    assert PINNED_SEARCH_RESULT_FLOORS == {
        "bilibili": 20,
        "zhihu": 20,
        "weibo": 10,
    }
    assert BILIBILI_LOW_VOLUME_PAGE_SIZE_PATCH is True
    assert ZHIHU_LOW_VOLUME_PAGE_SIZE_PATCH is True

    for platform in ("bilibili", "zhihu"):
        audit = audit_platform(platform)
        assert audit.search_low_volume_ready is True
        assert audit.search_result_floor == 1
        assert len(audit.blockers) == 2

    weibo = audit_platform("weibo")
    assert weibo.search_low_volume_ready is False
    assert weibo.search_result_floor == PINNED_SEARCH_RESULT_FLOORS["weibo"]
    assert len(weibo.blockers) == 3

    for platform in M2D_TARGET_PLATFORMS:
        audit = audit_platform(platform)
        assert audit.requires_human_login is True
        assert audit.requires_stable_browser_profile is True
        assert audit.requires_visible_browser is True
        assert audit.concurrency == 1
        assert audit.ip_proxy_enabled is False
        assert audit.max_items == MAX_SMOKE_ITEMS == 5
        assert audit.max_comments_per_content == MAX_SMOKE_COMMENTS == 5
        assert audit.subcomments is False

    with pytest.raises(SmokeSafetyError):
        audit_platform("douyin")


def test_smoke_request_limits_fail_closed_before_network() -> None:
    validate_smoke_request(
        platform="bilibili",
        mode="detail",
        requested_limit=1,
        comment_limit=5,
        include_subcomments=False,
    )
    validate_smoke_request(
        platform="bilibili",
        mode="search",
        requested_limit=5,
        comment_limit=0,
        include_subcomments=False,
    )
    validate_smoke_request(
        platform="zhihu",
        mode="search",
        requested_limit=5,
        comment_limit=0,
        include_subcomments=False,
    )
    validate_smoke_request(
        platform="zhihu",
        mode="comments",
        requested_limit=1,
        comment_limit=3,
        include_subcomments=False,
    )

    with pytest.raises(SmokeSafetyError, match="requested_limit"):
        validate_smoke_request(
            platform="weibo",
            mode="detail",
            requested_limit=6,
            comment_limit=0,
            include_subcomments=False,
        )
    with pytest.raises(SmokeSafetyError, match="comment_limit"):
        validate_smoke_request(
            platform="weibo",
            mode="comments",
            requested_limit=1,
            comment_limit=6,
            include_subcomments=False,
        )
    with pytest.raises(SmokeSafetyError, match="subcomments"):
        validate_smoke_request(
            platform="weibo",
            mode="comments",
            requested_limit=1,
            comment_limit=3,
            include_subcomments=True,
        )
    with pytest.raises(SmokeSafetyError, match="search page size"):
        validate_smoke_request(
            platform="weibo",
            mode="search",
            requested_limit=3,
            comment_limit=0,
            include_subcomments=False,
        )
    with pytest.raises(SmokeSafetyError):
        validate_smoke_request(
            platform="douyin",
            mode="detail",
            requested_limit=1,
            comment_limit=0,
            include_subcomments=False,
        )


def test_smoke_runner_forces_visible_single_concurrency_no_proxy(tmp_path: Path) -> None:
    vendor_home = tmp_path / "MediaCrawler"
    runner = M2DSmokeSubprocessRunner(
        vendor_home=vendor_home,
        python_executable="python",
    )
    bridge_entrypoint = runner.home / "main.py"
    command = runner._build_command(
        bridge_entrypoint,
        tmp_path / "result",
        _invocation(),
    )

    assert bridge_entrypoint.name == "main.py"
    assert "smoke_entry" in str(bridge_entrypoint)
    assert command[command.index("--enable_ip_proxy") + 1] == "false"
    assert command[command.index("--max_concurrency_num") + 1] == "1"
    assert command[command.index("--headless") + 1] == "false"
    assert command[command.index("--get_sub_comment") + 1] == "false"

    environment = runner._safe_environment(tmp_path / "result")
    assert environment["AI_EDITORIAL_M2D_SMOKE"] == "1"
    assert environment["AI_EDITORIAL_MEDIACRAWLER_HOME"] == str(vendor_home.resolve())
    assert "DATABASE_URL" not in environment
    assert "APP_ADMIN_TOKEN" not in environment


def test_smoke_entry_forces_existing_visible_cdp_and_blocks_auto_login(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AI_EDITORIAL_M2D_SMOKE", "1")
    config = SimpleNamespace(
        PLATFORM="bili",
        ENABLE_IP_PROXY=True,
        MAX_CONCURRENCY_NUM=4,
        HEADLESS=True,
        CDP_HEADLESS=True,
        ENABLE_CDP_MODE=False,
        CDP_CONNECT_EXISTING=False,
        ENABLE_GET_SUB_COMMENTS=True,
        AUTO_CLOSE_BROWSER=True,
    )
    _enforce_safe_config(config, SimpleNamespace(get_sub_comment=False))
    assert config.ENABLE_IP_PROXY is False
    assert config.MAX_CONCURRENCY_NUM == 1
    assert config.HEADLESS is False
    assert config.CDP_HEADLESS is False
    assert config.ENABLE_CDP_MODE is True
    assert config.CDP_CONNECT_EXISTING is True
    assert config.ENABLE_GET_SUB_COMMENTS is False
    assert config.AUTO_CLOSE_BROWSER is False

    with pytest.raises(RuntimeError, match="AUTH_REQUIRED"):
        import asyncio

        asyncio.run(_BlockedInteractiveLogin().begin())

    config.PLATFORM = "dy"
    with pytest.raises(RuntimeError, match="outside the first validation batch"):
        _enforce_safe_config(config, SimpleNamespace(get_sub_comment=False))


def test_only_first_batch_is_enabled_by_default_on_fresh_definition_sync() -> None:
    definitions = {
        item.platform: item
        for item in CONNECTOR_DEFINITIONS
        if item.connector_type == "mediacrawler"
    }
    assert set(definitions) == set(M2D_TARGET_PLATFORMS) | set(M2D_DEFERRED_PLATFORMS)
    assert M2D_DEFAULT_ENABLED_PLATFORMS == frozenset(M2D_TARGET_PLATFORMS)
    for platform in M2D_TARGET_PLATFORMS:
        assert definitions[platform].is_enabled_default is True
    for platform in M2D_DEFERRED_PLATFORMS:
        assert definitions[platform].is_enabled_default is False
        assert definitions[platform].capabilities["homefeed"] is False
        assert definitions[platform].capabilities["hotlist"] is False


def test_smoke_cli_failure_summary_exposes_only_safe_diagnostic_fields() -> None:
    summary = _failure_diagnostic_summary(
        {
            "failure_category": "CDP",
            "failure_code": "CDP_CONNECT_FAILED",
            "platform_risk_detected": False,
            "stderr": "SESSDATA=SECRET",
        }
    )
    assert summary == {
        "category": "CDP",
        "code": "CDP_CONNECT_FAILED",
        "risk_stop_required": False,
    }


def test_smoke_entry_import_marker_is_safe() -> None:
    assert _safe_import_error_marker(ModuleNotFoundError(name="playwright")) == (
        "AI_EDITORIAL_SAFE_IMPORT_ERROR exception_type=ModuleNotFoundError "
        "module=playwright reason=MODULE_NOT_FOUND"
    )
    assert "SECRET" not in _safe_import_error_marker(ImportError(name="foo token=SECRET"))


def test_smoke_entry_import_failure_writes_safe_marker_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke_entry_main = importlib.import_module(
        "packages.connectors.mediacrawler_adapter.smoke_entry.main"
    )

    async def raise_missing_module() -> None:
        raise ModuleNotFoundError(name="playwright")

    monkeypatch.setattr(smoke_entry_main, "_run", raise_missing_module)

    with pytest.raises(SystemExit) as exc_info:
        smoke_entry_main.main()

    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.err == (
        "AI_EDITORIAL_SAFE_IMPORT_ERROR "
        "exception_type=ModuleNotFoundError module=playwright "
        "reason=MODULE_NOT_FOUND\n"
    )
    assert "Traceback" not in captured.err


def test_smoke_cli_dependency_summary_exposes_only_safe_fields() -> None:
    summary = _failure_diagnostic_summary(
        {
            "failure_category": "DEPENDENCY",
            "failure_code": "DEPENDENCY_IMPORT_ERROR",
            "platform_risk_detected": False,
            "dependency_module": "playwright",
            "dependency_reason": "MODULE_NOT_FOUND",
            "stderr": "Cookie=SECRET",
        }
    )
    assert summary == {
        "category": "DEPENDENCY",
        "code": "DEPENDENCY_IMPORT_ERROR",
        "risk_stop_required": False,
        "dependency_module": "playwright",
        "dependency_reason": "MODULE_NOT_FOUND",
    }
