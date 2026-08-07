from __future__ import annotations

from packages.common.config import Settings, get_settings
from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
    to_platform_risk_error,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerInvocation,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.mediacrawler_adapter.resilience import EnvelopeRunner
from packages.risk_guard.classifier import classify_platform_error
from packages.risk_guard.models import PlatformRiskError, RiskEvent


class MediaCrawlerResilienceAdapter(MediaCrawlerAdapter):
    """Protocol 1.1 adapter preserving the existing Adapter type boundary."""

    def __init__(
        self,
        runner: EnvelopeRunner,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runner = runner

    async def health_check(self) -> dict[str, object]:
        base = await super().health_check()
        return {**base, "protocol_version": MEDIACRAWLER_PROTOCOL_VERSION}

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        envelope = await self.runner.run(invocation)
        if envelope.protocol_version != MEDIACRAWLER_PROTOCOL_VERSION:
            raise ConnectorFetchError(
                "PROTOCOL_VERSION_MISMATCH",
                "MediaCrawler result protocol version is incompatible",
                retryable=False,
            )
        if envelope.run_id != invocation.run_id or envelope.platform != invocation.platform:
            raise ConnectorFetchError(
                "RESULT_MALFORMED",
                "MediaCrawler result identity does not match the invocation",
                retryable=False,
            )
        if envelope.risk_events:
            event = envelope.risk_events[0]
            safe_partial = (
                envelope.status is MediaCrawlerResultStatus.PARTIAL
                and bool(envelope.items)
                and envelope.checkpoint is not None
                and event.checkpoint_safe_to_commit
            )
            if event.requires_manual_review and not safe_partial:
                try:
                    code = MediaCrawlerErrorCode(event.standard_error_code)
                except ValueError:
                    decision = classify_platform_error(
                        code=event.standard_error_code,
                        message=event.message,
                    )
                    raise PlatformRiskError(
                        RiskEvent.now(
                            platform=invocation.platform.value,
                            account_id=invocation.account_ref,
                            code=event.standard_error_code,
                            message=event.message,
                            disposition=decision.disposition,
                            action=decision.action,
                        )
                    )
                raise to_platform_risk_error(
                    MediaCrawlerAdapterError(code, event.message),
                    platform=invocation.platform.value,
                    account_ref=invocation.account_ref,
                )
        if envelope.status is MediaCrawlerResultStatus.FAILED:
            first = envelope.errors[0] if envelope.errors else None
            raise ConnectorFetchError(
                first.code if first is not None else "UNKNOWN_PLATFORM_ERROR",
                first.message if first is not None else "MediaCrawler platform execution failed",
                retryable=False,
            )
        return envelope
