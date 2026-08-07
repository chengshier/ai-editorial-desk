from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MEDIACRAWLER_PROTOCOL_VERSION = "1.1"
MEDIACRAWLER_LEGACY_PROTOCOL_VERSION = "1.0"
SUPPORTED_MEDIACRAWLER_PROTOCOL_VERSIONS = frozenset(
    {MEDIACRAWLER_LEGACY_PROTOCOL_VERSION, MEDIACRAWLER_PROTOCOL_VERSION}
)
MEDIACRAWLER_CHECKPOINT_SCHEMA_VERSION = "1.0"
MAX_INVOCATION_ITEMS = 100
MAX_RESULT_ITEMS = 5000

_SENSITIVE_KEYS = {
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
    "browser_profile_ref",
    "profile_path",
    "localstorage",
    "local_storage",
    "sessionstorage",
    "session_storage",
}


class MediaCrawlerPlatform(StrEnum):
    WEIBO = "weibo"
    BILIBILI = "bilibili"
    ZHIHU = "zhihu"
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    KUAISHOU = "kuaishou"
    BAIDU_TIEBA = "baidu_tieba"


class MediaCrawlerMode(StrEnum):
    SEARCH = "search"
    ACCOUNT = "account"
    DETAIL = "detail"
    COMMENTS = "comments"


class MediaCrawlerResultStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MediaCrawlerRiskSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LoginState(StrEnum):
    UNKNOWN = "unknown"
    VALID = "valid"
    EXPIRED = "expired"
    REQUIRES_INTERACTION = "requires_interaction"
    RESTRICTED = "restricted"


class MediaCrawlerResultError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    external_ref: str | None = Field(default=None, max_length=500)


class PlatformRiskSignal(BaseModel):
    """Sanitized platform risk report; Risk Guard remains the decision authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: MediaCrawlerPlatform
    source_error_code: str | None = Field(default=None, max_length=100)
    standard_error_code: str = Field(min_length=1, max_length=100)
    severity: MediaCrawlerRiskSeverity = MediaCrawlerRiskSeverity.ERROR
    retryable: bool = False
    action_hint: str = Field(default="stop", min_length=1, max_length=100)
    requires_manual_review: bool = True
    message: str = Field(min_length=1, max_length=1000)
    checkpoint_safe_to_commit: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_sensitive_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if _contains_sensitive_key(value):
            raise ValueError("risk metadata must not contain credentials or profile references")
        return value


class MediaCrawlerCounters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)


class MediaCrawlerCheckpoint(BaseModel):
    """Main-system checkpoint candidate; never an authority by itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = MEDIACRAWLER_CHECKPOINT_SCHEMA_VERSION
    platform: MediaCrawlerPlatform
    mode: MediaCrawlerMode
    cursor: dict[str, Any] | None = None
    page: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    last_external_id: str | None = Field(default=None, min_length=1, max_length=500)
    latest_published_at: datetime | None = None
    creator_watermark: str | None = Field(default=None, max_length=500)
    platform_cursor: dict[str, Any] | None = None
    last_completed_scope: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != MEDIACRAWLER_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(f"unsupported MediaCrawler checkpoint schema version: {value}")
        return value

    @field_validator("latest_published_at")
    @classmethod
    def require_checkpoint_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("checkpoint latest_published_at must include timezone")
        return value

    @field_validator("cursor", "platform_cursor", "metadata")
    @classmethod
    def reject_sensitive_checkpoint_parts(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is not None and _contains_sensitive_key(value):
            raise ValueError("checkpoint must not contain credentials or profile references")
        return value


class MediaCrawlerProfileContext(BaseModel):
    """Safe profile state crossing the protocol boundary; never contains refs or paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_configured: bool = False
    browser_profile_configured: bool = False
    login_state: LoginState = LoginState.UNKNOWN


class MediaCrawlerFeatureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_strategy: str | None = Field(default=None, max_length=100)
    incremental_strategy: str | None = Field(default=None, max_length=100)
    signature_provider: str | None = Field(default=None, max_length=100)
    homefeed_hook_available: bool = False
    hotlist_hook_available: bool = False
    legacy_protocol_source: str | None = Field(default=None, max_length=20)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


class MediaCrawlerInvocation(BaseModel):
    """Versioned, JSON-safe main-system contract for one MediaCrawler execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = MEDIACRAWLER_PROTOCOL_VERSION
    run_id: UUID
    platform: MediaCrawlerPlatform
    mode: MediaCrawlerMode
    source_id: UUID
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    creator_id: str | None = Field(default=None, min_length=1, max_length=500)
    content_ids: tuple[str, ...] = Field(default=(), max_length=MAX_INVOCATION_ITEMS)
    requested_limit: int = Field(ge=1, le=MAX_INVOCATION_ITEMS)
    comment_limit: int = Field(default=0, ge=0, le=MAX_INVOCATION_ITEMS)
    include_comments: bool = False
    include_subcomments: bool = False
    checkpoint: MediaCrawlerCheckpoint | None = None
    account_ref: str | None = Field(default=None, min_length=1, max_length=500)
    browser_profile_ref: str | None = Field(default=None, min_length=1, max_length=500)
    profile_context: MediaCrawlerProfileContext = Field(
        default_factory=MediaCrawlerProfileContext
    )
    timeout_seconds: int = Field(default=900, ge=1, le=7200)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol_version(cls, value: str) -> str:
        if value != MEDIACRAWLER_PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported MediaCrawler invocation protocol version: {value}"
            )
        return value

    @field_validator("content_ids")
    @classmethod
    def validate_content_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item or len(item) > 500 for item in normalized):
            raise ValueError("content_ids must contain non-empty values up to 500 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("content_ids must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_comment_contract(self) -> MediaCrawlerInvocation:
        if self.include_subcomments and not self.include_comments:
            raise ValueError("include_subcomments requires include_comments")
        if not self.include_comments and self.comment_limit:
            raise ValueError("comment_limit must be zero when include_comments is false")
        if self.checkpoint is not None:
            if self.checkpoint.platform is not self.platform:
                raise ValueError("checkpoint platform must match invocation platform")
            if self.checkpoint.mode is not self.mode:
                raise ValueError("checkpoint mode must match invocation mode")
        return self


class MediaCrawlerResultEnvelope(BaseModel):
    """Untrusted subprocess output after validation at the Adapter boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str
    run_id: UUID
    platform: MediaCrawlerPlatform
    status: MediaCrawlerResultStatus
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_RESULT_ITEMS)
    comments: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_RESULT_ITEMS)
    checkpoint: MediaCrawlerCheckpoint | None = None
    counters: MediaCrawlerCounters = Field(default_factory=MediaCrawlerCounters)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    risk_events: list[PlatformRiskSignal] = Field(default_factory=list, max_length=100)
    errors: list[MediaCrawlerResultError] = Field(default_factory=list, max_length=100)
    feature_metadata: MediaCrawlerFeatureMetadata = Field(
        default_factory=MediaCrawlerFeatureMetadata
    )
    started_at: datetime
    finished_at: datetime

    @field_validator("protocol_version")
    @classmethod
    def validate_result_protocol_version(cls, value: str) -> str:
        if value != MEDIACRAWLER_PROTOCOL_VERSION:
            raise ValueError(f"unsupported MediaCrawler result protocol version: {value}")
        return value

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("result timestamps must include timezone")
        return value

    @model_validator(mode="after")
    def validate_timeline(self) -> MediaCrawlerResultEnvelope:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.checkpoint is not None and self.checkpoint.platform is not self.platform:
            raise ValueError("result checkpoint platform must match result platform")
        return self


def _legacy_risk_signal(
    payload: dict[str, Any], platform: MediaCrawlerPlatform
) -> dict[str, Any]:
    code = str(payload.get("code") or "UNKNOWN_PLATFORM_ERROR")
    message = str(payload.get("message") or "legacy MediaCrawler risk signal")
    return {
        "platform": platform.value,
        "source_error_code": code,
        "standard_error_code": code,
        "severity": MediaCrawlerRiskSeverity.ERROR.value,
        "retryable": False,
        "action_hint": "manual_review",
        "requires_manual_review": True,
        "message": message,
        "checkpoint_safe_to_commit": False,
        "metadata": {},
    }


def _upgrade_checkpoint(
    raw_checkpoint: Any,
    *,
    platform: MediaCrawlerPlatform,
    mode: MediaCrawlerMode,
) -> dict[str, Any] | None:
    if raw_checkpoint is None:
        return None
    if not isinstance(raw_checkpoint, dict):
        raise ValueError("legacy checkpoint must be a JSON object")
    if raw_checkpoint.get("schema_version") == MEDIACRAWLER_CHECKPOINT_SCHEMA_VERSION:
        return raw_checkpoint
    return {
        "schema_version": MEDIACRAWLER_CHECKPOINT_SCHEMA_VERSION,
        "platform": platform.value,
        "mode": mode.value,
        "cursor": raw_checkpoint.get("cursor")
        if isinstance(raw_checkpoint.get("cursor"), dict)
        else None,
        "page": raw_checkpoint.get("page"),
        "offset": raw_checkpoint.get("offset"),
        "last_external_id": raw_checkpoint.get("last_external_id"),
        "latest_published_at": raw_checkpoint.get("latest_published_at"),
        "creator_watermark": raw_checkpoint.get("creator_watermark"),
        "platform_cursor": raw_checkpoint.get("platform_cursor")
        if isinstance(raw_checkpoint.get("platform_cursor"), dict)
        else None,
        "last_completed_scope": raw_checkpoint.get("last_completed_scope"),
        "metadata": raw_checkpoint.get("metadata")
        if isinstance(raw_checkpoint.get("metadata"), dict)
        else {},
    }


def parse_media_crawler_invocation(payload: dict[str, Any]) -> MediaCrawlerInvocation:
    """Parse 1.1 or explicitly upgrade supported legacy 1.0 invocation payloads."""

    version = str(payload.get("protocol_version") or "")
    if version not in SUPPORTED_MEDIACRAWLER_PROTOCOL_VERSIONS:
        raise ValueError(f"unsupported MediaCrawler invocation protocol version: {version}")
    if version == MEDIACRAWLER_PROTOCOL_VERSION:
        return MediaCrawlerInvocation.model_validate(payload)

    upgraded = dict(payload)
    platform = MediaCrawlerPlatform(upgraded["platform"])
    mode = MediaCrawlerMode(upgraded["mode"])
    upgraded["protocol_version"] = MEDIACRAWLER_PROTOCOL_VERSION
    upgraded["checkpoint"] = _upgrade_checkpoint(
        upgraded.get("checkpoint"),
        platform=platform,
        mode=mode,
    )
    upgraded["profile_context"] = {
        "account_configured": bool(upgraded.get("account_ref")),
        "browser_profile_configured": bool(upgraded.get("browser_profile_ref")),
        "login_state": LoginState.UNKNOWN.value,
    }
    return MediaCrawlerInvocation.model_validate(upgraded)


def parse_media_crawler_result(payload: dict[str, Any]) -> MediaCrawlerResultEnvelope:
    """Parse 1.1 or explicitly upgrade supported legacy 1.0 result payloads."""

    version = str(payload.get("protocol_version") or "")
    if version not in SUPPORTED_MEDIACRAWLER_PROTOCOL_VERSIONS:
        raise ValueError(f"unsupported MediaCrawler result protocol version: {version}")
    if version == MEDIACRAWLER_PROTOCOL_VERSION:
        return MediaCrawlerResultEnvelope.model_validate(payload)

    upgraded = dict(payload)
    platform = MediaCrawlerPlatform(upgraded["platform"])
    upgraded["protocol_version"] = MEDIACRAWLER_PROTOCOL_VERSION
    legacy_checkpoint = upgraded.get("checkpoint")
    if legacy_checkpoint is not None:
        if not isinstance(legacy_checkpoint, dict) or "mode" not in legacy_checkpoint:
            raise ValueError(
                "legacy 1.0 result checkpoint cannot be upgraded without an explicit mode"
            )
        checkpoint_mode = MediaCrawlerMode(legacy_checkpoint["mode"])
    else:
        checkpoint_mode = MediaCrawlerMode.SEARCH
    upgraded["checkpoint"] = _upgrade_checkpoint(
        legacy_checkpoint,
        platform=platform,
        mode=checkpoint_mode,
    )
    upgraded["risk_events"] = [
        _legacy_risk_signal(item, platform)
        for item in upgraded.get("risk_events", [])
        if isinstance(item, dict)
    ]
    upgraded["feature_metadata"] = {
        "legacy_protocol_source": MEDIACRAWLER_LEGACY_PROTOCOL_VERSION
    }
    return MediaCrawlerResultEnvelope.model_validate(upgraded)
