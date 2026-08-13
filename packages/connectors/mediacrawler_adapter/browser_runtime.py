from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from packages.common.config import Settings, get_settings

_CDP_HOST = "127.0.0.1"
_CDP_PORT = 9222
_PROFILE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOGIN_URLS = {
    "bilibili": "https://www.bilibili.com/",
    "weibo": "https://weibo.com/",
    "zhihu": "https://www.zhihu.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "douyin": "https://www.douyin.com/",
    "kuaishou": "https://www.kuaishou.com/",
    "baidu_tieba": "https://tieba.baidu.com/",
}
_SAFE_BROWSER_ENV_NAMES = {
    "APPDATA",
    "COMSPEC",
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WAYLAND_DISPLAY",
    "WINDIR",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
}


class LocalBrowserRuntimeError(RuntimeError):
    """A safe local-browser runtime operation could not be completed."""


@dataclass(slots=True, frozen=True)
class LocalBrowserRuntimeSnapshot:
    status: str
    enabled: bool
    browser_name: str | None
    cdp_ready: bool
    managed_by_api: bool
    profile_configured: bool
    profile_ready: bool
    can_start: bool
    can_stop: bool
    can_open_login: bool
    cdp_host: str
    cdp_port: int
    message: str


class LocalBrowserRuntimeManager:
    """Manage one local dedicated Chrome/Edge CDP process for human-operated login.

    Web requests never provide executable paths, shell commands, ports, URLs, or
    profile paths. The executable is auto-detected or deployment-configured; CDP is
    loopback-only; profiles are opaque refs under the controlled runtime root; and
    login URLs come from a server-side allow-list.
    """

    _process: ClassVar[subprocess.Popen[bytes] | None] = None
    _account_id: ClassVar[UUID | None] = None
    _browser_name: ClassVar[str | None] = None
    _profile_ref: ClassVar[str | None] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def status(
        self,
        *,
        account_id: UUID,
        profile_ref: str | None,
    ) -> LocalBrowserRuntimeSnapshot:
        enabled = self._enabled()
        executable = self._discover_browser()
        browser_name = self._browser_label(executable) if executable is not None else None
        profile_configured = bool(profile_ref)
        profile_ready = self._profile_exists(profile_ref)
        cdp_ready = self._cdp_reachable()
        process_running = self._managed_process_running()
        managed = bool(
            cdp_ready
            and process_running
            and self.__class__._account_id == account_id
        )
        managed_other = bool(
            cdp_ready
            and process_running
            and self.__class__._account_id != account_id
        )

        if not enabled:
            message = (
                "当前 API 不是本机浏览器运行模式。远程 / 云端部署需要本地 Runtime Agent；"
                "不会尝试从服务器控制用户电脑上的浏览器。"
            )
            status = "UNAVAILABLE"
        elif executable is None:
            message = (
                "未检测到可用的 Chrome / Edge。可安装浏览器，或通过部署配置指定"
                "白名单浏览器路径。"
            )
            status = "BROWSER_NOT_FOUND"
        elif managed_other:
            message = "本地专用浏览器正在服务另一个平台账号。请先结束当前会话后再切换账号。"
            status = "CONFLICT"
        elif cdp_ready and managed:
            message = "专用浏览器已由 AI 编辑部启动，可继续打开平台登录页或执行采集前检查。"
            status = "RUNNING"
        elif cdp_ready:
            message = (
                "检测到本地调试浏览器，但它不是当前后端进程启动的实例。为避免误用其他 Profile，"
                "请在原浏览器窗口中人工确认；本页面不会接管或关闭它。"
            )
            status = "RUNNING_EXTERNAL"
        elif not profile_configured:
            message = "平台账号尚未配置专用 Browser Profile 引用。请先编辑账号配置。"
            status = "PROFILE_REQUIRED"
        else:
            message = (
                "专用浏览器尚未启动。点击“启动专用浏览器”即可自动准备 Profile "
                "与本地调试环境。"
            )
            status = "STOPPED"

        return LocalBrowserRuntimeSnapshot(
            status=status,
            enabled=enabled,
            browser_name=browser_name,
            cdp_ready=cdp_ready,
            managed_by_api=managed,
            profile_configured=profile_configured,
            profile_ready=profile_ready,
            can_start=bool(enabled and executable and profile_configured and not cdp_ready),
            can_stop=managed,
            can_open_login=managed,
            cdp_host=_CDP_HOST,
            cdp_port=_CDP_PORT,
            message=message,
        )

    async def start(
        self,
        *,
        account_id: UUID,
        profile_ref: str | None,
    ) -> LocalBrowserRuntimeSnapshot:
        async with self.__class__._lock:
            current = self.status(account_id=account_id, profile_ref=profile_ref)
            if current.status == "RUNNING":
                return current
            if not current.enabled:
                raise LocalBrowserRuntimeError(current.message)
            if current.cdp_ready:
                raise LocalBrowserRuntimeError(current.message)
            executable = self._discover_browser()
            if executable is None:
                raise LocalBrowserRuntimeError("未检测到可用的 Chrome / Edge。")
            profile_path = self._prepare_profile(profile_ref)
            command = [
                str(executable),
                f"--remote-debugging-address={_CDP_HOST}",
                f"--remote-debugging-port={_CDP_PORT}",
                f"--user-data-dir={profile_path}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ]
            try:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=self._safe_browser_environment(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise LocalBrowserRuntimeError(
                    "专用浏览器启动失败，请检查浏览器安装与运行权限。"
                ) from exc

            self.__class__._process = process
            self.__class__._account_id = account_id
            self.__class__._browser_name = self._browser_label(executable)
            self.__class__._profile_ref = profile_ref

            for _ in range(40):
                if process.poll() is not None:
                    self._clear_managed_state()
                    raise LocalBrowserRuntimeError(
                        "浏览器进程已退出，未能建立本地调试连接。"
                    )
                if self._cdp_reachable():
                    return self.status(account_id=account_id, profile_ref=profile_ref)
                await asyncio.sleep(0.2)

            process.terminate()
            await self._wait_for_exit(process)
            self._clear_managed_state()
            raise LocalBrowserRuntimeError(
                "浏览器已启动，但本地调试环境在等待时间内没有就绪。"
            )

    async def stop(
        self,
        *,
        account_id: UUID,
        profile_ref: str | None,
    ) -> LocalBrowserRuntimeSnapshot:
        async with self.__class__._lock:
            process = self.__class__._process
            if (
                process is None
                or not self._managed_process_running()
                or self.__class__._account_id != account_id
            ):
                snapshot = self.status(account_id=account_id, profile_ref=profile_ref)
                if snapshot.cdp_ready:
                    raise LocalBrowserRuntimeError(
                        "当前浏览器不是由本后端进程启动，出于安全原因不会强制结束；"
                        "请在浏览器窗口中人工关闭。"
                    )
                self._clear_managed_state()
                return snapshot
            process.terminate()
            await self._wait_for_exit(process)
            self._clear_managed_state()
            for _ in range(15):
                if not self._cdp_reachable():
                    break
                await asyncio.sleep(0.2)
            return self.status(account_id=account_id, profile_ref=profile_ref)

    async def open_login(
        self,
        *,
        account_id: UUID,
        profile_ref: str | None,
        platform: str,
    ) -> LocalBrowserRuntimeSnapshot:
        snapshot = self.status(account_id=account_id, profile_ref=profile_ref)
        if not snapshot.can_open_login:
            raise LocalBrowserRuntimeError(snapshot.message)
        login_url = _LOGIN_URLS.get(platform)
        if login_url is None:
            raise LocalBrowserRuntimeError("当前平台尚未配置安全的人工登录入口。")
        try:
            await asyncio.to_thread(self._open_cdp_tab, login_url)
        except (OSError, TimeoutError, ValueError) as exc:
            raise LocalBrowserRuntimeError(
                "无法在专用浏览器中打开平台登录页，请刷新运行状态后重试。"
            ) from exc
        return self.status(account_id=account_id, profile_ref=profile_ref)

    def _enabled(self) -> bool:
        env = self.settings.app_env.strip().casefold()
        if env in {"ci", "mock", "test"}:
            return False
        if self.settings.local_browser_runtime_enabled:
            return True
        return (
            env not in {"prod", "production"}
            and self.settings.app_host.strip().casefold()
            in {_CDP_HOST, "localhost", "::1"}
        )

    def _discover_browser(self) -> Path | None:
        configured = self.settings.local_browser_runtime_executable
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.is_file():
                return candidate
            return None

        path_candidates: list[Path] = []
        if sys.platform == "win32":
            for root_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                root = os.environ.get(root_name)
                if not root:
                    continue
                path_candidates.extend(
                    [
                        Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
                        Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    ]
                )
        elif sys.platform == "darwin":
            path_candidates.extend(
                [
                    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                ]
            )
        for candidate in path_candidates:
            if candidate.is_file():
                return candidate
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
            "msedge",
        ):
            resolved = shutil.which(name)
            if resolved:
                return Path(resolved)
        return None

    def _prepare_profile(self, profile_ref: str | None) -> Path:
        if not profile_ref or not self._valid_profile_ref(profile_ref):
            raise LocalBrowserRuntimeError("Browser Profile 引用缺失或格式无效。")
        root_value = Path(self.settings.mediacrawler_profile_root).expanduser()
        root = root_value if root_value.is_absolute() else Path.cwd() / root_value
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        candidate = root / profile_ref
        if candidate.is_symlink():
            raise LocalBrowserRuntimeError("Browser Profile 不允许使用符号链接。")
        candidate.mkdir(exist_ok=True)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise LocalBrowserRuntimeError("Browser Profile 超出受控目录。")
        return resolved

    def _profile_exists(self, profile_ref: str | None) -> bool:
        if not profile_ref or not self._valid_profile_ref(profile_ref):
            return False
        root_value = Path(self.settings.mediacrawler_profile_root).expanduser()
        root = root_value if root_value.is_absolute() else Path.cwd() / root_value
        try:
            root = root.resolve()
            unresolved = root / profile_ref
            if unresolved.is_symlink():
                return False
            candidate = unresolved.resolve()
        except OSError:
            return False
        return candidate.is_relative_to(root) and candidate.is_dir()

    @classmethod
    def _managed_process_running(cls) -> bool:
        process = cls._process
        return process is not None and process.poll() is None

    @staticmethod
    def _cdp_reachable() -> bool:
        try:
            with socket.create_connection((_CDP_HOST, _CDP_PORT), timeout=0.25):
                return True
        except OSError:
            return False

    @staticmethod
    def _valid_profile_ref(value: str) -> bool:
        return (
            value not in {".", ".."}
            and "/" not in value
            and "\\" not in value
            and ".." not in value
            and bool(_PROFILE_REF_PATTERN.fullmatch(value))
        )

    @staticmethod
    def _browser_label(executable: Path | None) -> str | None:
        if executable is None:
            return None
        return "Microsoft Edge" if "edge" in executable.name.casefold() else "Google Chrome"

    @staticmethod
    def _safe_browser_environment() -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in _SAFE_BROWSER_ENV_NAMES
        }

    @staticmethod
    def _open_cdp_tab(login_url: str) -> None:
        encoded = urllib.parse.quote(login_url, safe="")
        request = urllib.request.Request(
            f"http://{_CDP_HOST}:{_CDP_PORT}/json/new?{encoded}",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            if response.status >= 400:
                raise OSError("CDP refused to open a new tab")

    @staticmethod
    async def _wait_for_exit(process: subprocess.Popen[bytes]) -> None:
        try:
            await asyncio.to_thread(process.wait, timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait)

    @classmethod
    def _clear_managed_state(cls) -> None:
        cls._process = None
        cls._account_id = None
        cls._browser_name = None
        cls._profile_ref = None
