from __future__ import annotations

from enum import StrEnum

from packages.connectors.http import ConnectorFetchError
from packages.risk_guard.classifier import classify_platform_error
from packages.risk_guard.models import PlatformRiskError, RiskEvent


class MediaCrawlerErrorCode(StrEnum):
    SUBPROCESS_TIMEOUT = "SUBPROCESS_TIMEOUT"
    SUBPROCESS_CANCELLED = "SUBPROCESS_CANCELLED"
    SUBPROCESS_OUTPUT_TOO_LARGE = "SUBPROCESS_OUTPUT_TOO_LARGE"
    NON_ZERO_EXIT = "NON_ZERO_EXIT"
    RESULT_MISSING = "RESULT_MISSING"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    RESULT_MALFORMED = "RESULT_MALFORMED"
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    BROWSER_DISCONNECTED = "BROWSER_DISCONNECTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    LOGIN_EXPIRED = "LOGIN_EXPIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"
    ACCOUNT_ABNORMAL = "ACCOUNT_ABNORMAL"
    AUTOMATION_DETECTED = "AUTOMATION_DETECTED"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    DNS_ERROR = "DNS_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    SIGNATURE_PROVIDER_ERROR = "SIGNATURE_PROVIDER_ERROR"
    UNKNOWN_PLATFORM_ERROR = "UNKNOWN_PLATFORM_ERROR"


RISK_ERROR_CODES = frozenset(
    {
        MediaCrawlerErrorCode.AUTH_REQUIRED,
        MediaCrawlerErrorCode.LOGIN_EXPIRED,
        MediaCrawlerErrorCode.PERMISSION_DENIED,
        MediaCrawlerErrorCode.RATE_LIMITED,
        MediaCrawlerErrorCode.CAPTCHA_REQUIRED,
        MediaCrawlerErrorCode.ACCOUNT_RESTRICTED,
        MediaCrawlerErrorCode.ACCOUNT_ABNORMAL,
        MediaCrawlerErrorCode.AUTOMATION_DETECTED,
    }
)


class MediaCrawlerAdapterError(ConnectorFetchError):
    """Safe, standardized Adapter failure; never exposes raw subprocess diagnostics."""

    def __init__(
        self,
        code: MediaCrawlerErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(code.value, message, retryable=retryable)
        self.error_code = code

    @property
    def is_risk(self) -> bool:
        return self.error_code in RISK_ERROR_CODES


def classify_subprocess_failure(
    *,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
) -> MediaCrawlerErrorCode:
    diagnostic = f"{stdout}\n{stderr}".casefold()

    if "captcha" in diagnostic or "验证码" in diagnostic or "滑块" in diagnostic:
        return MediaCrawlerErrorCode.CAPTCHA_REQUIRED
    if (
        "automation detected" in diagnostic
        or "检测到自动化" in diagnostic
        or "检测到ai操作" in diagnostic
        or "status 406" in diagnostic
        or "http 406" in diagnostic
    ):
        return MediaCrawlerErrorCode.AUTOMATION_DETECTED
    if (
        "account blocked" in diagnostic
        or "account restricted" in diagnostic
        or "账号受限" in diagnostic
        or "访问受限" in diagnostic
    ):
        return MediaCrawlerErrorCode.ACCOUNT_RESTRICTED
    if (
        "account abnormal" in diagnostic
        or "账号异常" in diagnostic
        or "-104" in diagnostic
    ):
        return MediaCrawlerErrorCode.ACCOUNT_ABNORMAL
    if (
        "login expired" in diagnostic
        or "登录失效" in diagnostic
        or "登录过期" in diagnostic
        or "repeated login invalidation" in diagnostic
    ):
        return MediaCrawlerErrorCode.LOGIN_EXPIRED
    if (
        "auth required" in diagnostic
        or "authentication required" in diagnostic
        or "请登录" in diagnostic
        or "未登录" in diagnostic
    ):
        return MediaCrawlerErrorCode.AUTH_REQUIRED
    if (
        "permission denied" in diagnostic
        or "没有权限" in diagnostic
        or "无权访问" in diagnostic
        or "status 403" in diagnostic
        or "http 403" in diagnostic
    ):
        return MediaCrawlerErrorCode.PERMISSION_DENIED
    if (
        "rate limit" in diagnostic
        or "too many requests" in diagnostic
        or "429" in diagnostic
    ):
        return MediaCrawlerErrorCode.RATE_LIMITED
    if (
        "browser disconnected" in diagnostic
        or "browser has been closed" in diagnostic
        or "target page, context or browser has been closed" in diagnostic
    ):
        return MediaCrawlerErrorCode.BROWSER_DISCONNECTED
    if (
        "name or service not known" in diagnostic
        or "temporary failure in name resolution" in diagnostic
        or "nodename nor servname provided" in diagnostic
        or "dns lookup" in diagnostic
        or "dns error" in diagnostic
    ):
        return MediaCrawlerErrorCode.DNS_ERROR
    if (
        "network timeout" in diagnostic
        or "timed out" in diagnostic
        or "timeout" in diagnostic
    ):
        return MediaCrawlerErrorCode.NETWORK_TIMEOUT
    if "parse error" in diagnostic or "解析失败" in diagnostic:
        return MediaCrawlerErrorCode.PARSE_ERROR
    if exit_code not in (None, 0):
        return MediaCrawlerErrorCode.NON_ZERO_EXIT
    return MediaCrawlerErrorCode.UNKNOWN_PLATFORM_ERROR


def to_platform_risk_error(
    error: MediaCrawlerAdapterError,
    *,
    platform: str,
    account_ref: str | None,
) -> PlatformRiskError:
    decision = classify_platform_error(code=error.code, message=error.safe_message)
    return PlatformRiskError(
        RiskEvent.now(
            platform=platform,
            account_id=account_ref,
            code=error.code,
            message=error.safe_message,
            disposition=decision.disposition,
            action=decision.action,
        )
    )
