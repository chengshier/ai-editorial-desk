from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from sqlalchemy import DateTime, Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

EnumT = TypeVar("EnumT", bound=StrEnum)

SENSITIVE_CONTEXT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credentials",
        "password",
        "proxy_authorization",
        "secret",
        "set_cookie",
        "token",
    }
)
REDACTED_VALUE = "[REDACTED]"


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store aware timestamps and normalize bound/result values to UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _normalized_key(key: str) -> str:
    return key.strip().casefold().replace("-", "_").replace(" ", "_")


def sanitize_context(value: Any) -> Any:
    """Recursively redact common credential/header keys before JSONB persistence."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_VALUE
            if _normalized_key(str(key)) in SENSITIVE_CONTEXT_KEYS
            else sanitize_context(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_context(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_context(item) for item in value]
    return value


class SanitizedJSONB(TypeDecorator[dict[str, Any]]):
    """JSONB that redacts credential-like values before binding."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(
        self, value: dict[str, Any] | None, dialect: Dialect
    ) -> dict[str, Any] | None:
        del dialect
        if value is None:
            return None
        sanitized = sanitize_context(value)
        if not isinstance(sanitized, dict):
            raise TypeError("risk context must be a JSON object")
        return sanitized


def string_enum(enum_type: type[EnumT], *, name: str) -> SqlEnum[EnumT]:
    """Create a portable string-backed enum with a database CHECK constraint."""

    values = [member.value for member in enum_type]
    return SqlEnum(
        enum_type,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(len(value) for value in values),
    )
