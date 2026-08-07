from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.account_profile import (
    AccountExecutionBlocked,
    BrowserProfileResolutionError,
    BrowserProfileResolver,
    MediaCrawlerAccountContext,
)
from packages.connectors.mediacrawler_adapter.discovery import (
    SAFE_DISCOVERY_POLICY,
    DiscoveryHookUnavailable,
    DiscoveryKind,
    discovery_hook_registry,
)
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    LoginState,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
)
from packages.connectors.mediacrawler_adapter.resilience import (
    MediaCrawlerResilienceRunner,
)
from packages.connectors.mediacrawler_adapter.risk_output import (
    is_technical_retry_error,
    risk_signal_from_error,
)
from packages.connectors.mediacrawler_adapter.signature import (
    DefaultSignatureProvider,
    SignatureProviderError,
    SignatureProviderRegistry,
    SignatureRequestContext,
    signature_provider_registry,
)
from packages.risk_guard.models import AccountStatus


def _account(
    status: AccountStatus = AccountStatus.HEALTHY,
    *,
    profile_ref: str | None = None,
    manual_review: bool = False,
    cooldown_until: datetime | None = None,
) -> MediaCrawlerAccountContext:
    return MediaCrawlerAccountContext(
        platform_account_id=uuid4(),
        account_identifier="fixture-account",
        credential_ref="credential-ref-fixture",
        browser_profile_ref=profile_ref,
        account_status=status,
        cooldown_until=cooldown_until,
        manual_review_required=manual_review,
        login_state=LoginState.UNKNOWN,
    )


def test_account_execution_rules_are_conservative() -> None:
    _account(AccountStatus.HEALTHY).ensure_runnable()
    _account(AccountStatus.WARNING).ensure_runnable()
    _account(
        AccountStatus.COOLDOWN,
        cooldown_until=datetime.now(UTC) - timedelta(seconds=1),
    ).ensure_runnable()

    blocked = [
        _account(AccountStatus.REVIEW_REQUIRED),
        _account(AccountStatus.RESTRICTED),
        _account(AccountStatus.DISABLED),
        _account(
            AccountStatus.COOLDOWN,
            cooldown_until=datetime.now(UTC) + timedelta(minutes=5),
        ),
        _account(AccountStatus.HEALTHY, manual_review=True),
    ]
    for account in blocked:
        with pytest.raises(AccountExecutionBlocked):
            account.ensure_runnable()


def test_browser_profile_resolver_accepts_only_existing_controlled_profile(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    profile = root / "account-a"
    profile.mkdir()
    account = _account(profile_ref="account-a")

    resolver = BrowserProfileResolver(root)
    first = resolver.resolve(account)
    second = resolver.resolve(account)
    assert first.platform_account_id == account.platform_account_id
    assert first.path == profile.resolve()
    assert second.path == first.path


@pytest.mark.parametrize(
    "profile_ref",
    ["../escape", "a/b", "a\\b", "..", ".", "/absolute", "a..b"],
)
def test_browser_profile_resolver_rejects_invalid_refs(
    tmp_path: Path,
    profile_ref: str,
) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    resolver = BrowserProfileResolver(root)
    with pytest.raises(BrowserProfileResolutionError):
        resolver.resolve(_account(profile_ref=profile_ref))


def test_browser_profile_resolver_rejects_missing_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    resolver = BrowserProfileResolver(root)
    with pytest.raises(BrowserProfileResolutionError):
        resolver.resolve(_account(profile_ref="missing"))

    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this test environment")
    with pytest.raises(BrowserProfileResolutionError):
        resolver.resolve(_account(profile_ref="linked"))


def test_signature_provider_registry_is_code_owned_for_all_seven_platforms() -> None:
    for platform in MediaCrawlerPlatform:
        plan = signature_provider_registry.get(platform).prepare_runtime(
            SignatureRequestContext(platform=platform, run_id=uuid4())
        )
        assert plan.provider_id == "vendor-default"
        assert plan.upstream_signer.startswith("vendor-default/")

    registry = SignatureProviderRegistry()
    registry.register(MediaCrawlerPlatform.WEIBO, DefaultSignatureProvider())
    with pytest.raises(ValueError):
        registry.register(MediaCrawlerPlatform.WEIBO, DefaultSignatureProvider())
    with pytest.raises(SignatureProviderError):
        registry.get(MediaCrawlerPlatform.BILIBILI)


class BrokenSignatureProvider:
    provider_id = "broken-fixture"

    def prepare_runtime(
        self,
        context: SignatureRequestContext,
    ):  # type: ignore[no-untyped-def]
        del context
        raise SignatureProviderError("fixture provider failed")


class NoopRunner:
    calls = 0

    async def run(self, invocation):  # type: ignore[no-untyped-def]
        del invocation
        self.calls += 1
        raise AssertionError(
            "page runner must not be called after signature failure"
        )


async def test_signature_provider_failure_is_standardized_without_network_call() -> None:
    registry = SignatureProviderRegistry()
    registry.register(MediaCrawlerPlatform.WEIBO, BrokenSignatureProvider())
    page_runner = NoopRunner()
    runner = MediaCrawlerResilienceRunner(
        page_runner,
        signature_registry=registry,
    )
    invocation = MediaCrawlerInvocation(
        run_id=uuid4(),
        platform=MediaCrawlerPlatform.WEIBO,
        mode=MediaCrawlerMode.SEARCH,
        source_id=uuid4(),
        keyword="AI",
        requested_limit=1,
        timeout_seconds=30,
    )
    with pytest.raises(ConnectorFetchError) as failed:
        await runner.run(invocation)
    assert failed.value.code == "SIGNATURE_PROVIDER_ERROR"
    assert page_runner.calls == 0


def test_standard_risk_output_separates_platform_risk_from_technical_retry() -> None:
    risk = risk_signal_from_error(
        MediaCrawlerAdapterError(
            MediaCrawlerErrorCode.RATE_LIMITED,
            "MediaCrawler platform rate limit detected",
        ),
        platform=MediaCrawlerPlatform.WEIBO,
        checkpoint_safe_to_commit=True,
    )
    assert risk.standard_error_code == "RATE_LIMITED"
    assert risk.source_error_code == "429"
    assert risk.requires_manual_review is True
    assert risk.retryable is False

    timeout = ConnectorFetchError(
        "DNS_ERROR",
        "MediaCrawler DNS lookup failed",
        retryable=True,
    )
    technical = risk_signal_from_error(
        timeout,
        platform=MediaCrawlerPlatform.WEIBO,
        checkpoint_safe_to_commit=False,
    )
    assert is_technical_retry_error(timeout) is True
    assert technical.requires_manual_review is False
    assert technical.retryable is True

    browser_disconnect = MediaCrawlerAdapterError(
        MediaCrawlerErrorCode.BROWSER_DISCONNECTED,
        "MediaCrawler browser process disconnected",
    )
    assert is_technical_retry_error(browser_disconnect) is True


@pytest.mark.parametrize(
    "code",
    [
        MediaCrawlerErrorCode.PERMISSION_DENIED,
        MediaCrawlerErrorCode.AUTOMATION_DETECTED,
        MediaCrawlerErrorCode.RATE_LIMITED,
        MediaCrawlerErrorCode.CAPTCHA_REQUIRED,
        MediaCrawlerErrorCode.LOGIN_EXPIRED,
        MediaCrawlerErrorCode.ACCOUNT_RESTRICTED,
        MediaCrawlerErrorCode.ACCOUNT_ABNORMAL,
    ],
)
def test_platform_risks_never_become_ordinary_retry(
    code: MediaCrawlerErrorCode,
) -> None:
    error = MediaCrawlerAdapterError(code, "fixture risk")
    assert is_technical_retry_error(error) is False
    signal = risk_signal_from_error(
        error,
        platform=MediaCrawlerPlatform.WEIBO,
        checkpoint_safe_to_commit=False,
    )
    assert signal.requires_manual_review is True
    assert signal.retryable is False


def test_homefeed_hotlist_hooks_remain_unregistered_and_disabled() -> None:
    assert SAFE_DISCOVERY_POLICY.enabled_by_default is False
    assert SAFE_DISCOVERY_POLICY.max_concurrency == 1
    assert SAFE_DISCOVERY_POLICY.max_requested_limit == 20
    for platform in MediaCrawlerPlatform:
        for kind in DiscoveryKind:
            assert discovery_hook_registry.is_available(platform, kind) is False
            with pytest.raises(DiscoveryHookUnavailable):
                discovery_hook_registry.get(platform, kind)
