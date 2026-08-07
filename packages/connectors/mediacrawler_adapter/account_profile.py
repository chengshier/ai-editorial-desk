from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from packages.connectors.mediacrawler_adapter.protocol import LoginState
from packages.risk_guard.models import AccountStatus

_PROFILE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AccountExecutionBlocked(ValueError):
    """A safe pre-network account gate failure."""


class BrowserProfileResolutionError(ValueError):
    """A browser profile reference could not be resolved safely."""


@dataclass(slots=True, frozen=True)
class MediaCrawlerAccountContext:
    """Runtime-only account state; never serialize this object into RawSignal or logs."""

    platform_account_id: UUID
    account_identifier: str
    credential_ref: str | None
    browser_profile_ref: str | None
    account_status: AccountStatus
    cooldown_until: datetime | None
    manual_review_required: bool
    login_state: LoginState = LoginState.UNKNOWN

    def ensure_runnable(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        if self.manual_review_required:
            raise AccountExecutionBlocked("platform account requires manual review")
        if self.account_status in {
            AccountStatus.REVIEW_REQUIRED,
            AccountStatus.RESTRICTED,
            AccountStatus.DISABLED,
        }:
            raise AccountExecutionBlocked(
                f"platform account status blocks execution: {self.account_status.value}"
            )
        if (
            self.account_status is AccountStatus.COOLDOWN
            and self.cooldown_until is not None
            and self.cooldown_until > current
        ):
            raise AccountExecutionBlocked("platform account cooldown is still active")

    @property
    def profile_configured(self) -> bool:
        return self.browser_profile_ref is not None

    @property
    def credential_configured(self) -> bool:
        return self.credential_ref is not None


@dataclass(slots=True, frozen=True)
class ResolvedBrowserProfile:
    """Internal-only resolved profile. The path must never be exposed through API/logs."""

    platform_account_id: UUID
    path: Path


class BrowserProfileResolver:
    """Resolve an opaque profile ref to one existing directory below a controlled root."""

    def __init__(self, root: Path) -> None:
        try:
            resolved = root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BrowserProfileResolutionError(
                "MediaCrawler browser profile root is unavailable"
            ) from exc
        if not resolved.is_dir():
            raise BrowserProfileResolutionError(
                "MediaCrawler browser profile root is not a directory"
            )
        self._root = resolved

    def resolve(self, account: MediaCrawlerAccountContext) -> ResolvedBrowserProfile:
        account.ensure_runnable()
        ref = account.browser_profile_ref
        if ref is None:
            raise BrowserProfileResolutionError("browser profile is not configured")
        if not self._valid_ref(ref):
            raise BrowserProfileResolutionError("browser profile reference is invalid")

        candidate = self._root / ref
        if candidate.is_symlink():
            raise BrowserProfileResolutionError("browser profile symlinks are not allowed")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BrowserProfileResolutionError("browser profile does not exist") from exc
        if not resolved.is_dir():
            raise BrowserProfileResolutionError("browser profile is not a directory")
        if not resolved.is_relative_to(self._root):
            raise BrowserProfileResolutionError(
                "browser profile escaped the controlled profile root"
            )
        return ResolvedBrowserProfile(
            platform_account_id=account.platform_account_id,
            path=resolved,
        )

    @staticmethod
    def _valid_ref(ref: str) -> bool:
        if ref in {".", ".."} or "/" in ref or "\\" in ref:
            return False
        if ".." in ref:
            return False
        return bool(_PROFILE_REF_PATTERN.fullmatch(ref))
