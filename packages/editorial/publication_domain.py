from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from packages.connector_management.exceptions import BusinessValidationError, ConflictError
from packages.database.models.publication import PerformanceHorizon, PerformanceSourceType
from packages.editorial.domain import normalize_text, stable_hash

PUBLICATION_RECORD_VERSION = "publication-record-v1"
PERFORMANCE_SNAPSHOT_VERSION = "performance-snapshot-v1"
PERFORMANCE_CSV_VERSION = "performance-csv-v1"
MAX_PERFORMANCE_CSV_BYTES = 2 * 1024 * 1024
MAX_PERFORMANCE_CSV_ROWS = 1000
CANONICAL_PERFORMANCE_CSV_FIELDS = (
    "publication_id",
    "platform_key",
    "external_post_id",
    "public_url",
    "observed_at",
    "horizon",
    "views",
    "completion_rate_percent",
    "average_watch_seconds",
    "likes",
    "comments",
    "shares",
    "favorites",
    "follower_delta",
)


class PublicationValidationError(BusinessValidationError):
    code = "PUBLICATION_VALIDATION_ERROR"


class PublicationAlreadyRecordedError(ConflictError):
    code = "PUBLICATION_ALREADY_RECORDED"


class EditorialAdoptionRequiredError(ConflictError):
    code = "EDITORIAL_ADOPTION_REQUIRED"


class PublicationEventMergedError(ConflictError):
    code = "EVENT_MERGED"

    def __init__(self, target_event_id: UUID) -> None:
        super().__init__(
            "已合并 source Event 不能记录新的 Publication",
            details={"target_event_id": str(target_event_id)},
        )


class PerformanceValidationError(BusinessValidationError):
    code = "PERFORMANCE_VALIDATION_ERROR"


class PerformanceImportValidationError(BusinessValidationError):
    code = "PERFORMANCE_CSV_VALIDATION_ERROR"


class PerformanceImportConfirmationRequiredError(BusinessValidationError):
    code = "PERFORMANCE_IMPORT_CONFIRMATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    views: int | None = None
    completion_rate: float | None = None
    average_watch_seconds: float | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    favorites: int | None = None
    follower_delta: int | None = None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "views": self.views,
            "completion_rate": self.completion_rate,
            "average_watch_seconds": self.average_watch_seconds,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "favorites": self.favorites,
            "follower_delta": self.follower_delta,
        }

    def validate(self) -> PerformanceMetrics:
        for name in ("views", "likes", "comments", "shares", "favorites"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise PerformanceValidationError(f"{name} 不能小于 0")
        if self.average_watch_seconds is not None and self.average_watch_seconds < 0:
            raise PerformanceValidationError("average_watch_seconds 不能小于 0")
        if self.completion_rate is not None and not 0 <= self.completion_rate <= 1:
            raise PerformanceValidationError("completion_rate 必须在 0..1")
        if all(value is None for value in self.as_dict().values()):
            raise PerformanceValidationError("Performance Snapshot 至少需要一个真实指标")
        return self


def normalize_public_url(value: str) -> str:
    """Normalize an HTTP(S) public URL without making any network request."""

    raw = value.strip()
    if not raw or len(raw) > 2048:
        raise PublicationValidationError("public_url 必须是 1..2048 字符")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise PublicationValidationError("public_url 格式无效") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise PublicationValidationError("public_url 只允许 http:// 或 https://")
    if not parsed.hostname:
        raise PublicationValidationError("public_url 必须包含有效 host")
    if parsed.username is not None or parsed.password is not None:
        raise PublicationValidationError("public_url 不允许包含用户名或密码")
    normalized = urlunsplit((scheme, parsed.netloc.casefold(), parsed.path or "", parsed.query, ""))
    if len(normalized) > 2048:
        raise PublicationValidationError("public_url 规范化后超过 2048 字符")
    return normalized


def require_aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicationValidationError(f"{field} 必须是带时区 ISO 8601 时间")
    return value.astimezone(UTC)


def normalize_required_text(value: str, field: str, *, max_length: int = 5000) -> str:
    normalized = normalize_text(value)
    if not normalized:
        raise PublicationValidationError(f"{field} 不能为空")
    if len(normalized) > max_length:
        raise PublicationValidationError(f"{field} 超过 {max_length} 字符")
    return normalized


def normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise PublicationValidationError(f"文本超过 {max_length} 字符")
    return normalized


def publication_content_hash(
    *, title: str | None, cover_text: str | None, body: str | None
) -> str | None:
    if title is None and cover_text is None and body is None:
        return None
    return stable_hash({"title": title, "cover_text": cover_text, "body": body})


def performance_snapshot_hash(
    *,
    publication_id: UUID,
    observed_at: datetime,
    horizon: PerformanceHorizon,
    metrics: PerformanceMetrics,
    source: PerformanceSourceType,
) -> str:
    return stable_hash(
        {
            "version": PERFORMANCE_SNAPSHOT_VERSION,
            "publication_id": str(publication_id),
            "observed_at": require_aware_utc(observed_at, "observed_at"),
            "horizon": horizon.value,
            "metrics": metrics.as_dict(),
            "source": source.value,
        }
    )


def engagement_rate(metrics: PerformanceMetrics) -> tuple[float | None, str | None]:
    if metrics.views is None:
        return None, "views unavailable"
    if metrics.views <= 0:
        return None, "views must be greater than zero"
    components = {
        "likes": metrics.likes,
        "comments": metrics.comments,
        "shares": metrics.shares,
        "favorites": metrics.favorites,
    }
    missing = [name for name, value in components.items() if value is None]
    if missing:
        return None, f"missing: {', '.join(missing)}"
    numerator = sum(int(value) for value in components.values() if value is not None)
    return round(numerator / metrics.views, 8), None


def metric_delta(current: int | float | None, previous: int | float | None) -> int | float | None:
    if current is None or previous is None:
        return None
    return current - previous


def safe_score_snapshot(score: Any) -> dict[str, Any] | None:
    if score is None:
        return None
    return {
        "id": str(score.id),
        "score_template": score.score_template,
        "score_template_version": score.score_template_version,
        "scoring_version": score.scoring_version,
        "source_type": score.source_type.value,
        "emotion": score.emotion,
        "information_gap": score.information_gap,
        "visual_value": score.visual_value,
        "user_relevance": score.user_relevance,
        "discussion": score.discussion,
        "novelty": score.novelty,
        "extendability": score.extendability,
        "traffic_total": score.traffic_total,
        "risk_level": score.risk_level.value,
        "recommended_format": score.recommended_format.value,
    }
