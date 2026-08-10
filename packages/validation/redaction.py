from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_MASK = "***"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "prompt",
    "browser_profile",
    "profile_path",
    "home_path",
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def mask_reference(value: str | None) -> str | None:
    """Keep only a reference scheme; never expose the referenced name/path/value."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if "://" in normalized:
        scheme = normalized.split("://", 1)[0]
        return f"{scheme}://{_MASK}"
    return _MASK


def sanitize_validation_payload(value: Any) -> Any:
    """Recursively redact validation output before it reaches stdout or Markdown/JSON."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            result[name] = _MASK if _sensitive_key(name) else sanitize_validation_payload(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_validation_payload(item) for item in value]
    return value


__all__ = ["mask_reference", "sanitize_validation_payload"]
