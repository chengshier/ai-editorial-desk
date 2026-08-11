from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class AccountStatus(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    COOLDOWN = "cooldown"
    REVIEW_REQUIRED = "review_required"
    RESTRICTED = "restricted"
    DISABLED = "disabled"


class ErrorDisposition(StrEnum):
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    MANUAL_REVIEW = "manual_review"


class RiskAction(StrEnum):
    RETRY = "retry"
    STOP_TASK = "stop_task"
    PAUSE_ACCOUNT = "pause_account"
    PAUSE_PLATFORM = "pause_platform"
    REQUIRE_REVIEW = "require_review"


@dataclass(slots=True, frozen=True)
class RiskEvent:
    platform: str
    account_id: str | None
    code: str
    message: str
    disposition: ErrorDisposition
    action: RiskAction
    occurred_at: datetime

    @classmethod
    def now(
        cls,
        *,
        platform: str,
        account_id: str | None,
        code: str,
        message: str,
        disposition: ErrorDisposition,
        action: RiskAction,
    ) -> "RiskEvent":
        return cls(
            platform=platform,
            account_id=account_id,
            code=code,
            message=message,
            disposition=disposition,
            action=action,
            occurred_at=datetime.now(UTC),
        )


class PlatformRiskError(RuntimeError):
    """A platform response that must not enter ordinary retry logic."""

    def __init__(self, event: RiskEvent) -> None:
        super().__init__(f"{event.platform}:{event.code}: {event.message}")
        self.event = event
        self.subprocess_diagnostic: object | None = None
