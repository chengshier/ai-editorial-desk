from __future__ import annotations

import re
from enum import StrEnum
from typing import TypedDict

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
    CDP_CONNECT_FAILED = "CDP_CONNECT_FAILED"
    PROFILE_UNAVAILABLE = "PROFILE_UNAVAILABLE"
    SMOKE_CONFIGURATION_ERROR = "SMOKE_CONFIGURATION_ERROR"
    DEPENDENCY_IMPORT_ERROR = "DEPENDENCY_IMPORT_ERROR"


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
_SAFE_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
_SAFE_IMPORT_MARKER = re.compile(
    r"AI_EDITORIAL_SAFE_IMPORT_ERROR\s+"
    r"exception_type=(ModuleNotFoundError|ImportError)\s+"
    r"module=(.*?)\s+reason=(MODULE_NOT_FOUND|IMPORT_FAILED)"
)
_SAFE_RUNTIME_STAGES = (
    "bootstrap",
    "cdp_connect",
    "page_navigation",
    "client_create",
    "login_state",
    "search",
)
_SAFE_RUNTIME_STAGE_MARKER = re.compile(
    r"(?m)^AI_EDITORIAL_SAFE_STAGE stage=("
    + "|".join(_SAFE_RUNTIME_STAGES)
    + r")\s*$"
)
_MODULE_NOT_FOUND = re.compile(
    r"ModuleNotFoundError:\s+No module named "
    r"['\"]([A-Za-z_][A-Za-z0-9_.]{0,127})['\"]"
)


class SubprocessFailureDiagnostic(TypedDict):
    """Safe, fixed-shape summary derived from untrusted subprocess output."""

    exit_code: int | None
    failure_category: str
    failure_code: str
    safe_message: str
    exception_type: str | None
    cdp_connect_failed: bool
    auth_required: bool
    profile_error: bool
    configuration_error: bool
    dependency_error: bool
    timeout: bool
    platform_risk_detected: bool
    platform_risk_type: str | None
    output_truncated: bool
    dependency_module: str | None
    dependency_reason: str | None
    runtime_stage: str | None


def build_subprocess_failure_diagnostic(
    *,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    output_truncated: bool = False,
    timed_out: bool = False,
) -> SubprocessFailureDiagnostic:
    """Classify output in memory; return no text copied from that output."""

    diagnostic = f"{stdout}\n{stderr}".casefold()
    code = classify_subprocess_failure(exit_code=exit_code, stdout=stdout, stderr=stderr)
    category = "UNKNOWN"
    safe_code = code.value
    safe_message = "MediaCrawler subprocess exited unsuccessfully"
    exception_type: str | None = None
    dependency_module: str | None = None
    dependency_reason: str | None = None
    stage_markers = _SAFE_RUNTIME_STAGE_MARKER.findall(f"{stdout}\n{stderr}")
    runtime_stage = stage_markers[-1] if stage_markers else None

    explicit_auth = "auth_required" in diagnostic
    if explicit_auth:
        category, safe_code, safe_message = (
            "AUTH",
            "AUTH_REQUIRED",
            "MediaCrawler authentication is required",
        )
    elif "m2d_smoke_cdp_required" in diagnostic or any(
        marker in diagnostic
        for marker in (
            "connection refused",
            "econnrefused",
            "connect_over_cdp",
            "cdp endpoint unavailable",
            "browser closed",
        )
    ):
        category, safe_code, safe_message = (
            "CDP",
            "CDP_CONNECT_FAILED",
            "MediaCrawler CDP connection failed",
        )
    elif any(
        marker in diagnostic
        for marker in (
            "profile/user-data-dir unavailable",
            "user-data-dir unavailable",
            "profile unavailable",
        )
    ):
        category, safe_code, safe_message = (
            "PROFILE",
            "PROFILE_UNAVAILABLE",
            "MediaCrawler browser profile is unavailable",
        )
    elif any(
        marker in diagnostic
        for marker in (
            "m2d_smoke_configuration_error",
            "m2d_smoke_target_error",
            "m2d_smoke_safety_error",
        )
    ):
        category, safe_code, safe_message = (
            "CONFIGURATION",
            "SMOKE_CONFIGURATION_ERROR",
            "MediaCrawler smoke configuration failed",
        )
    elif marker := _SAFE_IMPORT_MARKER.search(f"{stdout}\n{stderr}"):
        category, safe_code, safe_message, exception_type = (
            "DEPENDENCY",
            "DEPENDENCY_IMPORT_ERROR",
            "MediaCrawler dependency import failed",
            marker.group(1),
        )
        dependency_module = (
            marker.group(2)
            if _SAFE_MODULE_NAME.fullmatch(marker.group(2))
            else "unknown"
        )
        dependency_reason = marker.group(3)
    elif missing := _MODULE_NOT_FOUND.search(f"{stdout}\n{stderr}"):
        category, safe_code, safe_message, exception_type = (
            "DEPENDENCY",
            "DEPENDENCY_IMPORT_ERROR",
            "MediaCrawler dependency import failed",
            "ModuleNotFoundError",
        )
        dependency_module, dependency_reason = missing.group(1), "MODULE_NOT_FOUND"
    elif timed_out or code is MediaCrawlerErrorCode.NETWORK_TIMEOUT:
        category, safe_code, safe_message = (
            "TIMEOUT",
            "SUBPROCESS_TIMEOUT",
            "MediaCrawler subprocess timed out",
        )
    elif (
        runtime_stage is not None
        and exit_code not in (None, 0)
        and code is MediaCrawlerErrorCode.NON_ZERO_EXIT
    ):
        category, safe_code, safe_message = (
            "RUNTIME",
            "NON_ZERO_EXIT",
            "MediaCrawler subprocess exited unsuccessfully",
        )

    risk = code in RISK_ERROR_CODES or explicit_auth
    if risk:
        category = (
            "AUTH"
            if explicit_auth
            or code in {MediaCrawlerErrorCode.AUTH_REQUIRED, MediaCrawlerErrorCode.LOGIN_EXPIRED}
            else "PLATFORM_RISK"
        )
        if not explicit_auth:
            safe_code = code.value
            safe_message = _safe_diagnostic_message(code)

    return {
        "exit_code": exit_code,
        "failure_category": category,
        "failure_code": safe_code,
        "safe_message": safe_message,
        "exception_type": exception_type,
        "cdp_connect_failed": category == "CDP",
        "auth_required": explicit_auth
        or code in {MediaCrawlerErrorCode.AUTH_REQUIRED, MediaCrawlerErrorCode.LOGIN_EXPIRED},
        "profile_error": category == "PROFILE",
        "configuration_error": category == "CONFIGURATION",
        "dependency_error": category == "DEPENDENCY",
        "timeout": category == "TIMEOUT",
        "platform_risk_detected": risk,
        "platform_risk_type": safe_code if risk else None,
        "output_truncated": output_truncated,
        "dependency_module": dependency_module,
        "dependency_reason": dependency_reason,
        "runtime_stage": runtime_stage,
    }


def _safe_diagnostic_message(code: MediaCrawlerErrorCode) -> str:
    automation_message = "MediaCrawler platform automation restriction detected"
    return {
        MediaCrawlerErrorCode.PERMISSION_DENIED: "MediaCrawler platform permission denied",
        MediaCrawlerErrorCode.AUTOMATION_DETECTED: automation_message,
        MediaCrawlerErrorCode.RATE_LIMITED: "MediaCrawler platform rate limit detected",
        MediaCrawlerErrorCode.CAPTCHA_REQUIRED: "MediaCrawler platform requires CAPTCHA review",
        MediaCrawlerErrorCode.LOGIN_EXPIRED: "MediaCrawler platform login state expired",
        MediaCrawlerErrorCode.AUTH_REQUIRED: "MediaCrawler platform authentication is required",
        MediaCrawlerErrorCode.ACCOUNT_RESTRICTED: "MediaCrawler platform account is restricted",
        MediaCrawlerErrorCode.ACCOUNT_ABNORMAL: "MediaCrawler platform account is abnormal",
    }.get(code, "MediaCrawler platform risk detected")


class MediaCrawlerAdapterError(ConnectorFetchError):
    """Safe, standardized Adapter failure; never exposes raw subprocess diagnostics."""

    def __init__(
        self,
        code: MediaCrawlerErrorCode,
        message: str,
        *,
        retryable: bool = False,
        failure_diagnostic: SubprocessFailureDiagnostic | None = None,
    ) -> None:
        super().__init__(code.value, message, retryable=retryable)
        self.error_code = code
        self.failure_diagnostic = failure_diagnostic

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
    platform_error = PlatformRiskError(
        RiskEvent.now(
            platform=platform,
            account_id=account_ref,
            code=error.code,
            message=error.safe_message,
            disposition=decision.disposition,
            action=decision.action,
        )
    )
    platform_error.subprocess_diagnostic = error.failure_diagnostic
    return platform_error
