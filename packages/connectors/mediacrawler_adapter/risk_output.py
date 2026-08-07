from __future__ import annotations

from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.errors import MediaCrawlerAdapterError
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerPlatform,
    MediaCrawlerRiskSeverity,
    PlatformRiskSignal,
)

_CRITICAL_CODES = frozenset(
    {"ACCOUNT_RESTRICTED", "ACCOUNT_ABNORMAL", "AUTOMATION_DETECTED", "CAPTCHA_REQUIRED"}
)
_RISK_CODES = frozenset(
    {
        "AUTH_REQUIRED",
        "LOGIN_EXPIRED",
        "PERMISSION_DENIED",
        "RATE_LIMITED",
        "CAPTCHA_REQUIRED",
        "ACCOUNT_RESTRICTED",
        "ACCOUNT_ABNORMAL",
        "AUTOMATION_DETECTED",
    }
)
_TECHNICAL_RETRY_CODES = frozenset(
    {"SUBPROCESS_TIMEOUT", "NETWORK_TIMEOUT", "DNS_ERROR", "BROWSER_DISCONNECTED"}
)


def is_platform_risk_code(code: str) -> bool:
    return code in _RISK_CODES


def is_technical_retry_error(error: ConnectorFetchError) -> bool:
    return error.retryable and error.code in _TECHNICAL_RETRY_CODES


def risk_signal_from_error(
    error: ConnectorFetchError,
    *,
    platform: MediaCrawlerPlatform,
    checkpoint_safe_to_commit: bool,
    source_error_code: str | None = None,
) -> PlatformRiskSignal:
    code = error.code
    manual = is_platform_risk_code(code)
    if code in _CRITICAL_CODES:
        severity = MediaCrawlerRiskSeverity.CRITICAL
    elif manual:
        severity = MediaCrawlerRiskSeverity.ERROR
    else:
        severity = MediaCrawlerRiskSeverity.WARNING
    if isinstance(error, MediaCrawlerAdapterError):
        manual = error.is_risk
    return PlatformRiskSignal(
        platform=platform,
        source_error_code=source_error_code,
        standard_error_code=code,
        severity=severity,
        retryable=is_technical_retry_error(error) and not manual,
        action_hint="manual_review" if manual else ("limited_retry" if error.retryable else "stop"),
        requires_manual_review=manual,
        message=error.safe_message,
        checkpoint_safe_to_commit=checkpoint_safe_to_commit,
        metadata={},
    )
