from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.connectors.base import CollectRequest
from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
    classify_subprocess_failure,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultError,
    MediaCrawlerResultStatus,
)
from packages.connectors.mediacrawler_adapter.runner import (
    MediaCrawlerSubprocessRunner,
    load_result_envelope,
)
from packages.risk_guard.models import ErrorDisposition, PlatformRiskError


def _invocation(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "run_id": uuid4(),
        "platform": MediaCrawlerPlatform.WEIBO,
        "mode": MediaCrawlerMode.SEARCH,
        "source_id": uuid4(),
        "keyword": "AI 编辑部",
        "requested_limit": 5,
        "comment_limit": 0,
        "include_comments": False,
        "include_subcomments": False,
        "checkpoint": {"cursor": "safe"},
        "account_ref": "account-id",
        "browser_profile_ref": "profile-ref",
        "timeout_seconds": 2,
    }
    values.update(overrides)
    return MediaCrawlerInvocation(**values)


def _envelope(invocation: MediaCrawlerInvocation, **overrides):  # type: ignore[no-untyped-def]
    values = {
        "protocol_version": MEDIACRAWLER_PROTOCOL_VERSION,
        "run_id": invocation.run_id,
        "platform": invocation.platform,
        "status": MediaCrawlerResultStatus.SUCCESS,
        "items": [
            {
                "note_id": "post-1",
                "content": "fixture",
                "create_time": 1786086000,
                "liked_count": "1",
                "comments_count": "2",
                "shared_count": "3",
                "note_url": "https://m.weibo.cn/detail/post-1",
                "creator_hash": "creator-hash",
                "nickname": "测***户",
            }
        ],
        "comments": [],
        "checkpoint": {"cursor": "next"},
        "counters": MediaCrawlerCounters(items=1),
        "warnings": [],
        "risk_events": [],
        "errors": [],
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
    }
    values.update(overrides)
    return MediaCrawlerResultEnvelope(**values)


def test_invocation_serializes_and_rejects_invalid_contracts() -> None:
    invocation = _invocation()
    payload = json.loads(invocation.model_dump_json())
    assert payload["protocol_version"] == MEDIACRAWLER_PROTOCOL_VERSION
    assert payload["platform"] == "weibo"
    assert payload["mode"] == "search"
    assert "DATABASE_URL" not in payload
    assert "cookie" not in json.dumps(payload).casefold()

    with pytest.raises(ValidationError):
        _invocation(platform="unknown")
    with pytest.raises(ValidationError):
        _invocation(mode="homefeed")
    with pytest.raises(ValidationError):
        _invocation(requested_limit=101)
    with pytest.raises(ValidationError):
        _invocation(protocol_version="2.0")
    with pytest.raises(ValidationError):
        _invocation(checkpoint={"cookies": "secret"})


def test_result_loader_rejects_malformed_version_missing_and_oversized(tmp_path: Path) -> None:
    invocation = _invocation()
    good = _envelope(invocation)
    result_path = tmp_path / "result.json"
    result_path.write_text(good.model_dump_json(), encoding="utf-8")
    loaded = load_result_envelope(
        result_path,
        expected_run_id=str(invocation.run_id),
        expected_platform=invocation.platform.value,
        max_bytes=1024 * 1024,
    )
    assert loaded.items[0]["note_id"] == "post-1"

    result_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(MediaCrawlerAdapterError) as malformed:
        load_result_envelope(
            result_path,
            expected_run_id=str(invocation.run_id),
            expected_platform=invocation.platform.value,
            max_bytes=1024 * 1024,
        )
    assert malformed.value.code == MediaCrawlerErrorCode.RESULT_MALFORMED.value

    raw = good.model_dump(mode="json")
    raw["protocol_version"] = "9.9"
    result_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(MediaCrawlerAdapterError) as version:
        load_result_envelope(
            result_path,
            expected_run_id=str(invocation.run_id),
            expected_platform=invocation.platform.value,
            max_bytes=1024 * 1024,
        )
    assert version.value.code == MediaCrawlerErrorCode.PROTOCOL_VERSION_MISMATCH.value

    raw["protocol_version"] = MEDIACRAWLER_PROTOCOL_VERSION
    raw.pop("started_at")
    result_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(MediaCrawlerAdapterError) as missing:
        load_result_envelope(
            result_path,
            expected_run_id=str(invocation.run_id),
            expected_platform=invocation.platform.value,
            max_bytes=1024 * 1024,
        )
    assert missing.value.code == MediaCrawlerErrorCode.RESULT_MALFORMED.value

    result_path.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(MediaCrawlerAdapterError) as oversized:
        load_result_envelope(
            result_path,
            expected_run_id=str(invocation.run_id),
            expected_platform=invocation.platform.value,
            max_bytes=10,
        )
    assert oversized.value.code == MediaCrawlerErrorCode.RESULT_TOO_LARGE.value


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        delay: float = 0,
        on_wait=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self._exit_code = exit_code
        self._delay = delay
        self._on_wait = on_wait
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()

    async def wait(self) -> int:
        if self.returncode is not None:
            return self.returncode
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._on_wait is not None:
            self._on_wait()
        if self.returncode is None:
            self.returncode = self._exit_code
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class FixtureRunner(MediaCrawlerSubprocessRunner):
    def __init__(
        self,
        *,
        home: Path,
        process: FakeProcess,
        write_result: bool,
        malformed: bool = False,
    ) -> None:
        super().__init__(
            home=home,
            python_executable="python",
            max_result_bytes=4096,
            max_diagnostic_bytes=64,
        )
        self.process = process
        self.write_result = write_result
        self.malformed = malformed

    async def _spawn(self, command, data_root):  # type: ignore[no-untyped-def]
        assert "--enable_ip_proxy" in command
        assert command[command.index("--enable_ip_proxy") + 1] == "false"
        if self.write_result:

            def write() -> None:
                path = data_root / "wb" / "jsonl"
                path.mkdir(parents=True, exist_ok=True)
                content = "{broken\n" if self.malformed else (
                    '{"note_id":"post-1","note_url":"https://m.weibo.cn/detail/post-1",'
                    '"cookie":"drop"}\n'
                )
                (path / "search_contents_fixture.jsonl").write_text(
                    content,
                    encoding="utf-8",
                )

            self.process._on_wait = write
        return self.process  # type: ignore[return-value]


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "MediaCrawler"
    home.mkdir()
    (home / "main.py").write_text("# fixture", encoding="utf-8")
    return home


async def test_subprocess_success_and_result_sanitization(tmp_path: Path) -> None:
    invocation = _invocation()
    runner = FixtureRunner(
        home=_home(tmp_path),
        process=FakeProcess(),
        write_result=True,
    )
    result = await runner.run(invocation)
    assert result.status is MediaCrawlerResultStatus.SUCCESS
    assert result.items[0]["note_id"] == "post-1"
    assert "cookie" not in result.items[0]


async def test_subprocess_timeout_cancel_nonzero_no_result_and_malformed(tmp_path: Path) -> None:
    home = _home(tmp_path)

    timeout_runner = FixtureRunner(
        home=home,
        process=FakeProcess(delay=2),
        write_result=False,
    )
    with pytest.raises(MediaCrawlerAdapterError) as timeout:
        await timeout_runner.run(_invocation(timeout_seconds=1))
    assert timeout.value.code == MediaCrawlerErrorCode.SUBPROCESS_TIMEOUT.value

    cancel_runner = FixtureRunner(
        home=home,
        process=FakeProcess(delay=10),
        write_result=False,
    )
    task = asyncio.create_task(cancel_runner.run(_invocation(timeout_seconds=30)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(MediaCrawlerAdapterError) as cancelled:
        await task
    assert cancelled.value.code == MediaCrawlerErrorCode.SUBPROCESS_CANCELLED.value

    nonzero_runner = FixtureRunner(
        home=home,
        process=FakeProcess(stderr=b"HTTP 429 too many requests", exit_code=1),
        write_result=False,
    )
    with pytest.raises(MediaCrawlerAdapterError) as nonzero:
        await nonzero_runner.run(_invocation())
    assert nonzero.value.code == MediaCrawlerErrorCode.RATE_LIMITED.value

    no_result_runner = FixtureRunner(
        home=home,
        process=FakeProcess(),
        write_result=False,
    )
    with pytest.raises(MediaCrawlerAdapterError) as no_result:
        await no_result_runner.run(_invocation())
    assert no_result.value.code == MediaCrawlerErrorCode.RESULT_MISSING.value

    malformed_runner = FixtureRunner(
        home=home,
        process=FakeProcess(),
        write_result=True,
        malformed=True,
    )
    with pytest.raises(MediaCrawlerAdapterError) as malformed:
        await malformed_runner.run(_invocation())
    assert malformed.value.code == MediaCrawlerErrorCode.RESULT_MALFORMED.value


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("HTTP 403 permission denied", MediaCrawlerErrorCode.PERMISSION_DENIED),
        ("HTTP 406 automation detected", MediaCrawlerErrorCode.AUTOMATION_DETECTED),
        ("HTTP 429 too many requests", MediaCrawlerErrorCode.RATE_LIMITED),
        ("CAPTCHA required", MediaCrawlerErrorCode.CAPTCHA_REQUIRED),
        ("login expired", MediaCrawlerErrorCode.LOGIN_EXPIRED),
        ("permission denied", MediaCrawlerErrorCode.PERMISSION_DENIED),
        ("检测到AI操作", MediaCrawlerErrorCode.AUTOMATION_DETECTED),
        ("account restricted", MediaCrawlerErrorCode.ACCOUNT_RESTRICTED),
        ("network timeout", MediaCrawlerErrorCode.NETWORK_TIMEOUT),
        ("browser disconnected", MediaCrawlerErrorCode.BROWSER_DISCONNECTED),
    ],
)
def test_error_mapping_fixtures(diagnostic: str, expected: MediaCrawlerErrorCode) -> None:
    assert classify_subprocess_failure(exit_code=1, stderr=diagnostic) is expected


class StaticRunner:
    def __init__(
        self,
        *,
        envelope: MediaCrawlerResultEnvelope | None = None,
        error: MediaCrawlerAdapterError | None = None,
    ) -> None:
        self.envelope = envelope
        self.error = error

    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        if self.error is not None:
            raise self.error
        assert self.envelope is not None
        return self.envelope


async def test_risk_error_does_not_become_ordinary_retry() -> None:
    invocation = _invocation()
    adapter = MediaCrawlerAdapter(
        runner=StaticRunner(
            error=MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.CAPTCHA_REQUIRED,
                "MediaCrawler platform requires CAPTCHA review",
            )
        ),
        settings=SimpleNamespace(  # type: ignore[arg-type]
            mediacrawler_home="third_party/MediaCrawler",
            mediacrawler_python="python",
            mediacrawler_timeout_seconds=30,
        ),
    )
    with pytest.raises(PlatformRiskError) as risk:
        await adapter.invoke(invocation)
    assert risk.value.event.disposition is ErrorDisposition.MANUAL_REVIEW


async def test_partial_envelope_maps_standard_item_and_error() -> None:
    invocation = _invocation()
    partial = _envelope(
        invocation,
        status=MediaCrawlerResultStatus.PARTIAL,
        errors=[
            MediaCrawlerResultError(
                code="PARSE_ERROR",
                message="fixture parse error",
                external_ref="bad-2",
            )
        ],
    )
    adapter = MediaCrawlerAdapter(
        runner=StaticRunner(envelope=partial),
        settings=SimpleNamespace(  # type: ignore[arg-type]
            mediacrawler_home="third_party/MediaCrawler",
            mediacrawler_python="python",
            mediacrawler_timeout_seconds=30,
        ),
    )
    connector = MediaCrawlerConnector(adapter=adapter)
    result = await connector.collect(
        CollectRequest(
            source_id=str(invocation.source_id),
            mode="search",
            query="AI 编辑部",
            limit=5,
            run_id=str(invocation.run_id),
            platform="weibo",
            account_ref="account-id",
        )
    )
    assert len(result.signals) == 1
    assert result.signals[0].external_id == "post-1"
    assert result.errors[0].code == "PARSE_ERROR"
