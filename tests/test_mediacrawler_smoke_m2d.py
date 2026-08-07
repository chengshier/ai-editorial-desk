from __future__ import annotations

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
    M2D_DEFERRED_PLATFORMS,
    M2D_TARGET_PLATFORMS,
    MAX_SMOKE_COMMENTS,
    MAX_SMOKE_ITEMS,
    PINNED_SEARCH_RESULT_FLOORS,
    M2DSmokeSubprocessRunner,
    SmokeSafetyError,
    audit_platform,
    validate_smoke_request,
)
from packages.connectors.mediacrawler_adapter.smoke_entry.main import (
    _BlockedInteractiveLogin,
    _enforce_safe_config,
)


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


def test_first_batch_audit_exposes_real_search_floor_blockers() -> None:
    assert M2D_TARGET_PLATFORMS == ("bilibili", "zhihu", "weibo")
    assert PINNED_SEARCH_RESULT_FLOORS == {
        "bilibili": 20,
        "zhihu": 20,
        "weibo": 10,
    }
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
        assert audit.search_low_volume_ready is False
        assert audit.blockers

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
