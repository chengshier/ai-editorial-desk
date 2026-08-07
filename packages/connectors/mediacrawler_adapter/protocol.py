from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MEDIACRAWLER_PROTOCOL_VERSION = "1.0"
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


class MediaCrawlerResultError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    external_ref: str | None = Field(default=None, max_length=500)


class MediaCrawlerRiskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class MediaCrawlerCounters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)


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
    checkpoint: dict[str, Any] | None = None
    account_ref: str | None = Field(default=None, min_length=1, max_length=500)
    browser_profile_ref: str | None = Field(default=None, min_length=1, max_length=500)
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

    @field_validator("checkpoint")
    @classmethod
    def reject_sensitive_checkpoint(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is not None and _contains_sensitive_key(value):
            raise ValueError("checkpoint must not contain credentials or authorization data")
        return value

    @model_validator(mode="after")
    def validate_comment_contract(self) -> MediaCrawlerInvocation:
        if self.include_subcomments and not self.include_comments:
            raise ValueError("include_subcomments requires include_comments")
        if not self.include_comments and self.comment_limit:
            raise ValueError("comment_limit must be zero when include_comments is false")
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
    checkpoint: dict[str, Any] | None = None
    counters: MediaCrawlerCounters = Field(default_factory=MediaCrawlerCounters)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    risk_events: list[MediaCrawlerRiskEvent] = Field(default_factory=list, max_length=100)
    errors: list[MediaCrawlerResultError] = Field(default_factory=list, max_length=100)
    started_at: datetime
    finished_at: datetime

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("result timestamps must include timezone")
        return value

    @field_validator("checkpoint")
    @classmethod
    def reject_sensitive_checkpoint(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is not None and _contains_sensitive_key(value):
            raise ValueError("checkpoint must not contain credentials or authorization data")
        return value

    @model_validator(mode="after")
    def validate_timeline(self) -> MediaCrawlerResultEnvelope:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self
