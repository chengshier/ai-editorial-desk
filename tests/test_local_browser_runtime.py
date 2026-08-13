from uuid import uuid4

import pytest

from packages.common.config import get_settings
from packages.connectors.mediacrawler_adapter.browser_runtime import (
    LocalBrowserRuntimeError,
    LocalBrowserRuntimeManager,
)


def _manager(tmp_path, monkeypatch) -> LocalBrowserRuntimeManager:
    browser = tmp_path / "chrome.exe"
    browser.write_text("test browser placeholder", encoding="utf-8")
    settings = get_settings().model_copy(
        update={
            "app_env": "development",
            "app_host": "127.0.0.1",
            "local_browser_runtime_enabled": False,
            "local_browser_runtime_executable": str(browser),
            "mediacrawler_profile_root": str(tmp_path / "profiles"),
        }
    )
    manager = LocalBrowserRuntimeManager(settings)
    monkeypatch.setattr(manager, "_cdp_reachable", lambda: False)
    return manager


def test_local_browser_status_is_available_without_manual_cdp_command(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    snapshot = manager.status(account_id=uuid4(), profile_ref="bilibili-main")

    assert snapshot.enabled is True
    assert snapshot.status == "STOPPED"
    assert snapshot.can_start is True
    assert snapshot.cdp_host == "127.0.0.1"
    assert snapshot.cdp_port == 9222
    assert snapshot.profile_ready is False


def test_prepare_profile_creates_only_controlled_opaque_profile(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    profile = manager._prepare_profile("bilibili-main")

    assert profile.is_dir()
    assert profile.name == "bilibili-main"
    assert manager._profile_exists("bilibili-main") is True

    with pytest.raises(LocalBrowserRuntimeError):
        manager._prepare_profile("../escaped")


def test_browser_child_environment_does_not_inherit_provider_secret(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-browser")
    monkeypatch.setenv("PATH", "safe-path")

    environment = manager._safe_browser_environment()

    assert environment["PATH"] == "safe-path"
    assert "DEEPSEEK_API_KEY" not in environment
