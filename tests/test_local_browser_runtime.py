import asyncio
import subprocess
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


@pytest.mark.asyncio
async def test_start_uses_popen_without_asyncio_subprocess_transport(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    account_id = uuid4()
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((list(command), kwargs))
        return FakeProcess()

    async def forbidden_asyncio_spawn(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise AssertionError("asyncio subprocess transport must not be used")

    cdp_checks = iter([False, True, True])
    monkeypatch.setattr(manager, "_cdp_reachable", lambda: next(cdp_checks, True))
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_asyncio_spawn)

    snapshot = await manager.start(
        account_id=account_id,
        profile_ref="bilibili-main",
    )

    assert snapshot.status == "RUNNING"
    assert snapshot.managed_by_api is True
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert any(item == "--remote-debugging-address=127.0.0.1" for item in command)
    assert any(item == "--remote-debugging-port=9222" for item in command)
    assert any(item.startswith("--user-data-dir=") for item in command)
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert "DEEPSEEK_API_KEY" not in environment

    LocalBrowserRuntimeManager._clear_managed_state()
