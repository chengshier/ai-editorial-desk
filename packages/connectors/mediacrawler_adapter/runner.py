from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, BinaryIO, Protocol

from pydantic import ValidationError

from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
    build_subprocess_failure_diagnostic,
    classify_subprocess_failure,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)

logger = logging.getLogger(__name__)

PLATFORM_CLI_CODES = {
    "weibo": "wb",
    "bilibili": "bili",
    "zhihu": "zhihu",
    "douyin": "dy",
    "xiaohongshu": "xhs",
    "kuaishou": "ks",
    "baidu_tieba": "tieba",
}
MODE_CLI_CODES = {
    MediaCrawlerMode.SEARCH: "search",
    MediaCrawlerMode.ACCOUNT: "creator",
    MediaCrawlerMode.DETAIL: "detail",
    MediaCrawlerMode.COMMENTS: "detail",
}
SAFE_ENV_NAMES = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "HOME",
        "USERPROFILE",
        "USERNAME",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "TMPDIR",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
)
_RESULT_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "password",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "credential",
        "credential_ref",
        "browser_storage",
        "storage_state",
    }
)


class SubprocessFactory(Protocol):
    def __call__(self, *args: str, **kwargs: Any) -> Awaitable[asyncio.subprocess.Process]: ...


class _OutputLimitExceeded(RuntimeError):
    pass


class _ThreadedPopenProcess:
    """Async-shaped wrapper around Popen for Windows event-loop compatibility."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdout = process.stdout
        self.stderr = process.stderr

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    def kill(self) -> None:
        self._process.kill()


RunnerProcess = asyncio.subprocess.Process | _ThreadedPopenProcess


def _prepare_run_directory(temp_dir: str) -> tuple[Path, Path]:
    run_root = Path(temp_dir).resolve()
    data_root = run_root / "data"
    data_root.mkdir(mode=0o700)
    return run_root, data_root


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    *,
    max_bytes: int,
) -> bytes:
    if stream is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _OutputLimitExceeded
        chunks.append(chunk)
    return b"".join(chunks)


def _read_bounded_sync(
    stream: BinaryIO | None,
    *,
    max_bytes: int,
) -> bytes:
    if stream is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _OutputLimitExceeded
        chunks.append(chunk)
    return b"".join(chunks)


def _sanitize_untrusted_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _RESULT_SENSITIVE_KEYS:
                continue
            sanitized[str(key)] = _sanitize_untrusted_payload(nested)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_untrusted_payload(item) for item in value]
    return value


def load_result_envelope(
    path: Path,
    *,
    expected_run_id: str,
    expected_platform: str,
    max_bytes: int,
) -> MediaCrawlerResultEnvelope:
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_MISSING,
            "MediaCrawler result envelope is missing",
        ) from exc
    if size > max_bytes:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_TOO_LARGE,
            "MediaCrawler result envelope exceeds the configured size limit",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_MALFORMED,
            "MediaCrawler result envelope is not valid JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_MALFORMED,
            "MediaCrawler result envelope must be a JSON object",
        )
    if raw.get("protocol_version") != MEDIACRAWLER_PROTOCOL_VERSION:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.PROTOCOL_VERSION_MISMATCH,
            "MediaCrawler result protocol version is incompatible",
        )
    try:
        envelope = MediaCrawlerResultEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_MALFORMED,
            "MediaCrawler result envelope failed schema validation",
        ) from exc
    if str(envelope.run_id) != expected_run_id or envelope.platform.value != expected_platform:
        raise MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RESULT_MALFORMED,
            "MediaCrawler result identity does not match the invocation",
        )
    return envelope


class MediaCrawlerSubprocessRunner:
    """Bounded subprocess runner with a per-run, main-system-owned result directory."""

    def __init__(
        self,
        *,
        home: Path,
        python_executable: str,
        max_result_bytes: int = 8 * 1024 * 1024,
        max_diagnostic_bytes: int = 256 * 1024,
        process_factory: SubprocessFactory | None = None,
    ) -> None:
        self.home = home.expanduser().resolve()
        self.python_executable = python_executable
        self.max_result_bytes = max_result_bytes
        self.max_diagnostic_bytes = max_diagnostic_bytes
        self.process_factory = process_factory

    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        entrypoint = self.home / "main.py"
        if not entrypoint.is_file():
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MISSING,
                "MediaCrawler entrypoint is unavailable",
            )

        started_at = datetime.now(UTC)
        started = monotonic()
        prefix = f"ai-editorial-mc-{invocation.run_id.hex[:12]}-"
        with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
            run_root, data_root = _prepare_run_directory(temp_dir)
            command = self._build_command(entrypoint, data_root, invocation)
            process = await self._spawn(command, data_root)
            logger.info(
                "mediacrawler_subprocess_started",
                extra={
                    "run_id": str(invocation.run_id),
                    "platform": invocation.platform.value,
                    "mode": invocation.mode.value,
                    "subprocess_pid": process.pid,
                },
            )

            try:
                stdout, stderr = await self._communicate(
                    process,
                    timeout_seconds=invocation.timeout_seconds,
                )
            except TimeoutError as exc:
                await self._kill(process)
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.SUBPROCESS_TIMEOUT,
                    "MediaCrawler subprocess timed out",
                    retryable=True,
                    failure_diagnostic=build_subprocess_failure_diagnostic(
                        exit_code=None,
                        output_truncated=False,
                        timed_out=True,
                    ),
                ) from exc
            except asyncio.CancelledError as exc:
                await self._kill(process)
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.SUBPROCESS_CANCELLED,
                    "MediaCrawler subprocess was cancelled",
                ) from exc
            except _OutputLimitExceeded as exc:
                await self._kill(process)
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.SUBPROCESS_OUTPUT_TOO_LARGE,
                    "MediaCrawler diagnostic output exceeded the configured limit",
                    failure_diagnostic=build_subprocess_failure_diagnostic(
                        exit_code=process.returncode,
                        output_truncated=True,
                    ),
                ) from exc

            exit_code = process.returncode
            if exit_code != 0:
                diagnostic_stdout = stdout.decode("utf-8", errors="replace")
                diagnostic_stderr = stderr.decode("utf-8", errors="replace")
                code = classify_subprocess_failure(
                    exit_code=exit_code,
                    stdout=diagnostic_stdout,
                    stderr=diagnostic_stderr,
                )
                failure_diagnostic = build_subprocess_failure_diagnostic(
                    exit_code=exit_code,
                    stdout=diagnostic_stdout,
                    stderr=diagnostic_stderr,
                )
                if failure_diagnostic["platform_risk_detected"]:
                    code = MediaCrawlerErrorCode(failure_diagnostic["failure_code"])
                raise MediaCrawlerAdapterError(
                    code,
                    failure_diagnostic["safe_message"],
                    retryable=code is MediaCrawlerErrorCode.NETWORK_TIMEOUT,
                    failure_diagnostic=failure_diagnostic,
                )

            finished_at = datetime.now(UTC)
            envelope = self._build_envelope(
                data_root=data_root,
                invocation=invocation,
                started_at=started_at,
                finished_at=finished_at,
            )
            envelope_path = run_root / "result_envelope.json"
            encoded = envelope.model_dump_json().encode("utf-8")
            if len(encoded) > self.max_result_bytes:
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.RESULT_TOO_LARGE,
                    "MediaCrawler result envelope exceeds the configured size limit",
                )
            envelope_path.write_bytes(encoded)
            validated = load_result_envelope(
                envelope_path,
                expected_run_id=str(invocation.run_id),
                expected_platform=invocation.platform.value,
                max_bytes=self.max_result_bytes,
            )
            logger.info(
                "mediacrawler_subprocess_completed",
                extra={
                    "run_id": str(invocation.run_id),
                    "platform": invocation.platform.value,
                    "mode": invocation.mode.value,
                    "subprocess_pid": process.pid,
                    "duration": monotonic() - started,
                    "exit_code": exit_code,
                    "result_size": len(encoded),
                },
            )
            return validated

    async def _spawn(
        self,
        command: list[str],
        data_root: Path,
    ) -> RunnerProcess:
        if self.process_factory is not None:
            kwargs: dict[str, Any] = {
                "cwd": str(self.home),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "env": self._safe_environment(data_root),
            }
            return await self.process_factory(*command, **kwargs)
        try:
            process = await asyncio.to_thread(
                subprocess.Popen,
                command,
                cwd=str(self.home),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._safe_environment(data_root),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.NON_ZERO_EXIT,
                "MediaCrawler subprocess could not be started",
            ) from exc
        return _ThreadedPopenProcess(process)

    async def _communicate(
        self,
        process: RunnerProcess,
        *,
        timeout_seconds: int,
    ) -> tuple[bytes, bytes]:
        if isinstance(process, _ThreadedPopenProcess):
            stdout_task = asyncio.create_task(
                asyncio.to_thread(
                    _read_bounded_sync,
                    process.stdout,
                    max_bytes=self.max_diagnostic_bytes,
                )
            )
            stderr_task = asyncio.create_task(
                asyncio.to_thread(
                    _read_bounded_sync,
                    process.stderr,
                    max_bytes=self.max_diagnostic_bytes,
                )
            )
        else:
            stdout_task = asyncio.create_task(
                _read_bounded(process.stdout, max_bytes=self.max_diagnostic_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_bounded(process.stderr, max_bytes=self.max_diagnostic_bytes)
            )
        wait_task = asyncio.create_task(process.wait())
        try:
            _, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(wait_task, stdout_task, stderr_task),
                timeout=timeout_seconds,
            )
        finally:
            for task in (wait_task, stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
        return stdout, stderr

    async def _kill(self, process: RunnerProcess) -> None:
        if process.returncode is None:
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            logger.warning(
                "mediacrawler_subprocess_kill_wait_timed_out",
                extra={"subprocess_pid": process.pid},
            )

    def _build_command(
        self,
        entrypoint: Path,
        data_root: Path,
        invocation: MediaCrawlerInvocation,
    ) -> list[str]:
        command = [
            self.python_executable,
            str(entrypoint),
            "--platform",
            PLATFORM_CLI_CODES[invocation.platform.value],
            "--type",
            MODE_CLI_CODES[invocation.mode],
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(data_root),
            "--crawler_max_notes_count",
            str(invocation.requested_limit),
            "--max_comments_count_singlenotes",
            str(invocation.comment_limit),
            "--get_comment",
            str(invocation.include_comments).lower(),
            "--get_sub_comment",
            str(invocation.include_subcomments).lower(),
            "--enable_ip_proxy",
            "false",
        ]
        if invocation.keyword:
            command.extend(["--keywords", invocation.keyword])
        if invocation.creator_id:
            command.extend(["--creator_id", invocation.creator_id])
        if invocation.content_ids:
            command.extend(["--specified_id", ",".join(invocation.content_ids)])
        return command

    def _safe_environment(self, data_root: Path) -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_NAMES
        }
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "AI_EDITORIAL_MEDIACRAWLER_RESULT_ROOT": str(data_root),
            }
        )
        return environment

    def _build_envelope(
        self,
        *,
        data_root: Path,
        invocation: MediaCrawlerInvocation,
        started_at: datetime,
        finished_at: datetime,
    ) -> MediaCrawlerResultEnvelope:
        files = sorted(data_root.rglob("*.jsonl"))
        if not files:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MISSING,
                "MediaCrawler did not produce a JSONL result",
            )
        total_size = 0
        items: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        root = data_root.resolve()
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.RESULT_MALFORMED,
                    "MediaCrawler result path escaped the controlled run directory",
                )
            total_size += path.stat().st_size
            if total_size > self.max_result_bytes:
                raise MediaCrawlerAdapterError(
                    MediaCrawlerErrorCode.RESULT_TOO_LARGE,
                    "MediaCrawler JSONL output exceeds the configured size limit",
                )
            target = comments if "comment" in path.stem.casefold() else items
            self._read_jsonl(path, target)
        if not items and not comments:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MISSING,
                "MediaCrawler produced no usable result records",
            )
        return MediaCrawlerResultEnvelope(
            protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=MediaCrawlerResultStatus.SUCCESS,
            items=items,
            comments=comments,
            checkpoint=None,
            counters=MediaCrawlerCounters(
                items=len(items),
                comments=len(comments),
                warnings=0,
                errors=0,
            ),
            warnings=[],
            risk_events=[],
            errors=[],
            started_at=started_at,
            finished_at=finished_at,
        )

    @staticmethod
    def _read_jsonl(path: Path, target: list[dict[str, Any]]) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    payload = json.loads(stripped)
                    if not isinstance(payload, dict):
                        raise ValueError("JSONL record is not an object")
                    sanitized = _sanitize_untrusted_payload(payload)
                    if not isinstance(sanitized, dict):
                        raise ValueError("sanitized JSONL record is not an object")
                    target.append(sanitized)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MALFORMED,
                "MediaCrawler JSONL output is malformed",
            ) from exc

    @staticmethod
    def _safe_failure_message(code: MediaCrawlerErrorCode, exit_code: int | None) -> str:
        messages = {
            MediaCrawlerErrorCode.PERMISSION_DENIED: (
                "MediaCrawler platform permission denied (403)"
            ),
            MediaCrawlerErrorCode.AUTOMATION_DETECTED: (
                "MediaCrawler platform automation restriction detected (406)"
            ),
            MediaCrawlerErrorCode.RATE_LIMITED: "MediaCrawler platform rate limit detected (429)",
            MediaCrawlerErrorCode.CAPTCHA_REQUIRED: "MediaCrawler platform requires CAPTCHA review",
            MediaCrawlerErrorCode.LOGIN_EXPIRED: "MediaCrawler platform login state expired",
            MediaCrawlerErrorCode.AUTH_REQUIRED: "MediaCrawler platform authentication is required",
            MediaCrawlerErrorCode.ACCOUNT_RESTRICTED: "MediaCrawler platform account is restricted",
            MediaCrawlerErrorCode.ACCOUNT_ABNORMAL: "MediaCrawler platform account is abnormal",
            MediaCrawlerErrorCode.BROWSER_DISCONNECTED: "MediaCrawler browser process disconnected",
            MediaCrawlerErrorCode.NETWORK_TIMEOUT: "MediaCrawler platform network timeout",
            MediaCrawlerErrorCode.PARSE_ERROR: "MediaCrawler platform response parse failed",
        }
        return messages.get(
            code,
            f"MediaCrawler subprocess exited unsuccessfully (exit_code={exit_code})",
        )
