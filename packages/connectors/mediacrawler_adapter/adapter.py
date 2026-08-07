from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from packages.common.config import Settings, get_settings
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
    classify_subprocess_failure,
    to_platform_risk_error,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerInvocation,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.mediacrawler_adapter.runner import MediaCrawlerSubprocessRunner


class MediaCrawlerRunner(Protocol):
    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope: ...


def _entrypoint_available(settings: Settings) -> bool:
    home = Path(settings.mediacrawler_home).expanduser().resolve()
    return (home / "main.py").is_file()


class MediaCrawlerAdapter:
    """Own the stable main-system protocol and isolate the vendored subprocess."""

    def __init__(
        self,
        *,
        runner: MediaCrawlerRunner | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runner = runner or MediaCrawlerSubprocessRunner(
            home=Path(self.settings.mediacrawler_home),
            python_executable=self.settings.mediacrawler_python,
        )

    async def health_check(self) -> dict[str, Any]:
        available = _entrypoint_available(self.settings)
        return {
            "status": "ok" if available else "not_installed",
            "protocol_version": MEDIACRAWLER_PROTOCOL_VERSION,
            "entrypoint_available": available,
        }

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        try:
            envelope = await self.runner.run(invocation)
        except MediaCrawlerAdapterError as exc:
            if exc.is_risk:
                raise to_platform_risk_error(
                    exc,
                    platform=invocation.platform.value,
                    account_ref=invocation.account_ref,
                ) from exc
            raise

        if envelope.protocol_version != MEDIACRAWLER_PROTOCOL_VERSION:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.PROTOCOL_VERSION_MISMATCH,
                "MediaCrawler result protocol version is incompatible",
            )
        if envelope.run_id != invocation.run_id or envelope.platform != invocation.platform:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MALFORMED,
                "MediaCrawler result identity does not match the invocation",
            )

        if envelope.risk_events:
            event = envelope.risk_events[0]
            code = self._standardize_result_error(
                event.standard_error_code,
                event.message,
            )
            error = MediaCrawlerAdapterError(
                code,
                self._safe_result_message(code),
            )
            raise to_platform_risk_error(
                error,
                platform=invocation.platform.value,
                account_ref=invocation.account_ref,
            )

        if envelope.status is MediaCrawlerResultStatus.FAILED:
            if envelope.errors:
                first = envelope.errors[0]
                code = self._standardize_result_error(first.code, first.message)
            else:
                code = MediaCrawlerErrorCode.UNKNOWN_PLATFORM_ERROR
            error = MediaCrawlerAdapterError(
                code,
                self._safe_result_message(code),
                retryable=code is MediaCrawlerErrorCode.NETWORK_TIMEOUT,
            )
            if error.is_risk:
                raise to_platform_risk_error(
                    error,
                    platform=invocation.platform.value,
                    account_ref=invocation.account_ref,
                )
            raise error
        return envelope

    @staticmethod
    def _standardize_result_error(code: str, message: str) -> MediaCrawlerErrorCode:
        try:
            return MediaCrawlerErrorCode(code)
        except ValueError:
            return classify_subprocess_failure(
                exit_code=0,
                stderr=f"{code} {message}",
            )

    @staticmethod
    def _safe_result_message(code: MediaCrawlerErrorCode) -> str:
        messages = {
            MediaCrawlerErrorCode.PERMISSION_DENIED: "MediaCrawler platform permission denied",
            MediaCrawlerErrorCode.RATE_LIMITED: "MediaCrawler platform rate limit detected",
            MediaCrawlerErrorCode.CAPTCHA_REQUIRED: "MediaCrawler platform requires CAPTCHA review",
            MediaCrawlerErrorCode.ACCOUNT_RESTRICTED: "MediaCrawler platform account is restricted",
            MediaCrawlerErrorCode.ACCOUNT_ABNORMAL: "MediaCrawler platform account is abnormal",
            MediaCrawlerErrorCode.AUTOMATION_DETECTED: (
                "MediaCrawler platform automation restriction detected"
            ),
            MediaCrawlerErrorCode.AUTH_REQUIRED: "MediaCrawler platform authentication is required",
            MediaCrawlerErrorCode.LOGIN_EXPIRED: "MediaCrawler platform login state expired",
            MediaCrawlerErrorCode.NETWORK_TIMEOUT: "MediaCrawler platform network timeout",
            MediaCrawlerErrorCode.BROWSER_DISCONNECTED: "MediaCrawler browser process disconnected",
            MediaCrawlerErrorCode.PARSE_ERROR: "MediaCrawler platform response parse failed",
        }
        return messages.get(code, "MediaCrawler platform execution failed")
