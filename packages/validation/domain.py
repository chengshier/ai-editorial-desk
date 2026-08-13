from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast

from packages.validation.redaction import sanitize_validation_payload

EXPECTED_MIGRATION_HEAD = "20260810_0015"
FAKE_MARKERS = (
    "fake",
    "mock",
    "stub",
    "synthetic",
    "offline",
    "fixture",
    "test-provider",
)


class CheckLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    key: str
    level: CheckLevel
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            sanitize_validation_payload(asdict(self)),
        )


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    checks: tuple[ValidationCheck, ...]

    @property
    def result(self) -> CheckLevel:
        levels = {item.level for item in self.checks}
        if CheckLevel.BLOCK in levels:
            return CheckLevel.BLOCK
        if CheckLevel.WARN in levels:
            return CheckLevel.WARN
        return CheckLevel.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "checks": [item.to_dict() for item in self.checks],
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class E2EVerificationResult:
    result: str
    checks: tuple[ValidationCheck, ...]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "result": self.result,
            "checks": [item.to_dict() for item in self.checks],
            "evidence": self.evidence,
            "read_only": True,
            "artifacts_created": False,
        }
        return cast(
            dict[str, Any],
            sanitize_validation_payload(payload),
        )


def check(
    key: str,
    level: CheckLevel,
    message: str,
    **details: Any,
) -> ValidationCheck:
    return ValidationCheck(key, level, message, details)


def contains_fake_marker(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    return any(marker in normalized for marker in FAKE_MARKERS)


def metadata_is_synthetic(metadata: dict[str, Any]) -> bool:
    for key, value in metadata.items():
        normalized = str(key).casefold()
        if any(marker in normalized for marker in FAKE_MARKERS):
            if value not in (False, None, "", 0):
                return True
        if isinstance(value, str) and contains_fake_marker(value):
            return True
    return False
