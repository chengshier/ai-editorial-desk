from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from packages.connectors.base import CollectedComment, RawSignal
from packages.database.types import is_sensitive_key, sanitize_context

_CHINA_TZ = ZoneInfo("Asia/Shanghai")
_NUMBER_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([万亿]?)$")


class MapperDataError(ValueError):
    """One untrusted MediaCrawler record cannot be mapped safely."""

    def __init__(self, message: str, *, external_ref: str | None = None) -> None:
        super().__init__(message)
        self.external_ref = external_ref


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def required_id(value: Any, *, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MapperDataError(f"{field} missing")
    normalized = str(value).strip()
    if not normalized:
        raise MapperDataError(f"{field} missing")
    return normalized


def parse_count(value: Any) -> int | float | None:
    """Parse vendored numeric counters without inventing missing zero values."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    raw = value.strip().replace(",", "")
    if not raw or raw.casefold() in {"none", "null", "nan", "-"}:
        return None
    match = _NUMBER_RE.fullmatch(raw)
    if match is None:
        return None
    number = float(match.group(1))
    if number < 0:
        return None
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    converted = number * multiplier
    return int(converted) if converted.is_integer() else converted


def parse_like_count(value: Any) -> int | None:
    parsed = parse_count(value)
    if parsed is None:
        return None
    return int(parsed)


def parse_datetime(value: Any) -> datetime | None:
    """Normalize timestamps and naive China-local strings to aware UTC."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric >= 100_000_000_000:
            numeric /= 1000
        try:
            return datetime.fromtimestamp(numeric, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if _NUMBER_RE.fullmatch(raw):
        try:
            return parse_datetime(float(raw))
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_CHINA_TZ)
    return parsed.astimezone(UTC)


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not is_sensitive_key(key)
    ]
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc, parts.path, urlencode(query, doseq=True), "")
    )


def sanitize_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Apply the project's existing redaction and strip secret-bearing URL query params."""

    redacted = sanitize_context(value)
    if not isinstance(redacted, dict):
        raise MapperDataError("sanitized payload is not an object")

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): clean(nested) for key, nested in item.items()}
        if isinstance(item, list):
            return [clean(nested) for nested in item]
        if isinstance(item, tuple):
            return [clean(nested) for nested in item]
        if isinstance(item, str) and item.strip().startswith(("http://", "https://")):
            return safe_url(item) or "[REDACTED_URL]"
        return item

    cleaned = clean(redacted)
    if not isinstance(cleaned, dict):
        raise MapperDataError("sanitized payload is not an object")
    return cleaned


def metrics_from(item: dict[str, Any], mapping: dict[str, str]) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {}
    for output_key, source_key in mapping.items():
        value = parse_count(item.get(source_key))
        if value is not None:
            metrics[output_key] = value
    return metrics


def split_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        return []
    output: list[str] = []
    for entry in values:
        url = safe_url(entry)
        if url and url not in output:
            output.append(url)
    return output


def media_entry(
    *,
    media_type: str,
    index: int,
    url: Any = None,
    thumbnail_url: Any = None,
) -> dict[str, Any] | None:
    safe_media_url = safe_url(url)
    safe_thumbnail = safe_url(thumbnail_url)
    if safe_media_url is None and safe_thumbnail is None:
        return None
    result: dict[str, Any] = {"type": media_type, "index": index}
    if safe_media_url is not None:
        result["url"] = safe_media_url
    if safe_thumbnail is not None:
        result["thumbnail_url"] = safe_thumbnail
    return result


class PlatformMapper(ABC):
    platform: str

    @abstractmethod
    def validate_item(self, item: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def map_item(self, item: dict[str, Any]) -> RawSignal:
        raise NotImplementedError

    @abstractmethod
    def map_comment(self, comment: dict[str, Any]) -> CollectedComment:
        raise NotImplementedError

    @abstractmethod
    def normalize_metrics(self, item: dict[str, Any]) -> dict[str, int | float]:
        raise NotImplementedError

    @abstractmethod
    def normalize_media(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError
