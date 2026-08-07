from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from packages.connectors.http import ConnectorFetchError
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
    to_platform_risk_error,
)
from packages.connectors.mediacrawler_adapter.incremental import (
    build_search_checkpoint,
    filter_tieba_new_items,
    get_incremental_spec,
    last_item_external_id,
    latest_item_timestamp,
    resume_page,
    tieba_watermark_reached,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerFeatureMetadata,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultError,
    MediaCrawlerResultStatus,
)
from packages.connectors.mediacrawler_adapter.risk_output import (
    is_platform_risk_code,
    is_technical_retry_error,
    risk_signal_from_error,
)
from packages.connectors.mediacrawler_adapter.runner import MediaCrawlerSubprocessRunner
from packages.connectors.mediacrawler_adapter.signature import (
    SignatureProviderError,
    SignatureProviderRegistry,
    SignatureRequestContext,
    signature_provider_registry,
)
from packages.risk_guard.classifier import classify_platform_error
from packages.risk_guard.models import PlatformRiskError, RiskEvent

SleepCallable = Callable[[float], Awaitable[None]]
JitterCallable = Callable[[], float]


class EnvelopeRunner(Protocol):
    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope: ...


class ResumePageRunner(MediaCrawlerSubprocessRunner):
    """Use the pinned CLI's existing --start argument without changing vendored source."""

    def _build_command(
        self,
        entrypoint: Any,
        data_root: Any,
        invocation: MediaCrawlerInvocation,
    ) -> list[str]:
        command = super()._build_command(entrypoint, data_root, invocation)
        if invocation.mode is MediaCrawlerMode.SEARCH and invocation.checkpoint is not None:
            page = invocation.checkpoint.page
            if page is not None:
                command.extend(["--start", str(page)])
        return command


class MediaCrawlerResilienceRunner:
    """Main-system page resume, bounded technical retry and safe partial results."""

    def __init__(
        self,
        page_runner: EnvelopeRunner,
        *,
        max_technical_attempts: int = 3,
        sleep: SleepCallable = asyncio.sleep,
        jitter: JitterCallable = random.random,
        signature_registry: SignatureProviderRegistry | None = None,
    ) -> None:
        if max_technical_attempts < 1 or max_technical_attempts > 3:
            raise ValueError("max_technical_attempts must be between 1 and 3")
        self.page_runner = page_runner
        self.max_technical_attempts = max_technical_attempts
        self.sleep = sleep
        self.jitter = jitter
        self.signature_registry = signature_registry or signature_provider_registry

    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        try:
            signature_plan = self.signature_registry.get(invocation.platform).prepare_runtime(
                SignatureRequestContext(platform=invocation.platform, run_id=invocation.run_id)
            )
        except SignatureProviderError as exc:
            raise ConnectorFetchError(
                "SIGNATURE_PROVIDER_ERROR",
                "MediaCrawler signature provider preparation failed",
                retryable=False,
            ) from exc

        if invocation.mode is not MediaCrawlerMode.SEARCH:
            envelope = await self._run_with_retry(invocation)
            return envelope.model_copy(
                update={
                    "feature_metadata": MediaCrawlerFeatureMetadata(
                        signature_provider=signature_plan.provider_id,
                    )
                }
            )
        return await self._run_search(invocation, signature_plan.provider_id)

    async def _run_search(
        self,
        invocation: MediaCrawlerInvocation,
        signature_provider: str,
    ) -> MediaCrawlerResultEnvelope:
        spec = get_incremental_spec(invocation.platform)
        started_at = datetime.now(UTC)
        page = resume_page(invocation.checkpoint)
        remaining = invocation.requested_limit
        items: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        last_completed_page = max(0, page - 1)
        cycle_complete = False
        stopped_by_watermark = False

        while remaining > 0:
            page_limit = min(spec.page_size, remaining)
            page_checkpoint = self._page_checkpoint(invocation, page)
            page_invocation = invocation.model_copy(
                update={"requested_limit": page_limit, "checkpoint": page_checkpoint}
            )
            try:
                envelope = await self._run_with_retry(page_invocation)
            except ConnectorFetchError as exc:
                if exc.code == MediaCrawlerErrorCode.RESULT_MISSING.value and items:
                    cycle_complete = True
                    break
                if not items:
                    raise
                checkpoint = self._checkpoint(
                    invocation=invocation,
                    items=items,
                    next_page=page,
                    last_completed_page=last_completed_page,
                    cycle_complete=False,
                )
                signal = risk_signal_from_error(
                    exc,
                    platform=invocation.platform,
                    checkpoint_safe_to_commit=True,
                )
                return MediaCrawlerResultEnvelope(
                    protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
                    run_id=invocation.run_id,
                    platform=invocation.platform,
                    status=MediaCrawlerResultStatus.PARTIAL,
                    items=items,
                    comments=comments,
                    checkpoint=checkpoint,
                    counters=MediaCrawlerCounters(
                        items=len(items), comments=len(comments), errors=1
                    ),
                    risk_events=[signal],
                    errors=(
                        []
                        if signal.requires_manual_review
                        else [MediaCrawlerResultError(code=exc.code, message=exc.safe_message)]
                    ),
                    feature_metadata=MediaCrawlerFeatureMetadata(
                        checkpoint_strategy="main_system_page_checkpoint",
                        incremental_strategy=spec.search_strategy,
                        signature_provider=signature_provider,
                    ),
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )

            raw_items = envelope.items
            page_items = raw_items
            if invocation.platform is MediaCrawlerPlatform.BAIDU_TIEBA:
                stopped_by_watermark = tieba_watermark_reached(
                    items=raw_items,
                    checkpoint=invocation.checkpoint,
                )
                page_items = filter_tieba_new_items(
                    items=raw_items,
                    checkpoint=invocation.checkpoint,
                )
            items.extend(page_items)
            comments.extend(
                self._comments_for_page(
                    invocation.platform,
                    page_items,
                    raw_items,
                    envelope.comments,
                )
            )
            last_completed_page = page
            remaining -= min(len(raw_items), page_limit)
            if stopped_by_watermark or len(raw_items) < page_limit or not raw_items:
                cycle_complete = True
                break
            page += 1

        checkpoint = self._checkpoint(
            invocation=invocation,
            items=items,
            next_page=page,
            last_completed_page=last_completed_page,
            cycle_complete=cycle_complete,
            stopped_by_watermark=stopped_by_watermark,
        )
        return MediaCrawlerResultEnvelope(
            protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
            run_id=invocation.run_id,
            platform=invocation.platform,
            status=MediaCrawlerResultStatus.SUCCESS,
            items=items,
            comments=comments,
            checkpoint=checkpoint,
            counters=MediaCrawlerCounters(items=len(items), comments=len(comments)),
            feature_metadata=MediaCrawlerFeatureMetadata(
                checkpoint_strategy="main_system_page_checkpoint",
                incremental_strategy=spec.search_strategy,
                signature_provider=signature_provider,
            ),
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    async def _run_with_retry(
        self,
        invocation: MediaCrawlerInvocation,
    ) -> MediaCrawlerResultEnvelope:
        last_error: ConnectorFetchError | None = None
        for attempt in range(1, self.max_technical_attempts + 1):
            try:
                return await self.page_runner.run(invocation)
            except ConnectorFetchError as exc:
                last_error = exc
                if not is_technical_retry_error(exc) or attempt >= self.max_technical_attempts:
                    raise
                delay = 0.25 * (2 ** (attempt - 1)) + min(
                    0.1, max(0.0, self.jitter()) * 0.1
                )
                await self.sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _page_checkpoint(
        invocation: MediaCrawlerInvocation,
        page: int,
    ) -> MediaCrawlerCheckpoint:
        previous = invocation.checkpoint
        return MediaCrawlerCheckpoint(
            platform=invocation.platform,
            mode=MediaCrawlerMode.SEARCH,
            page=page,
            last_external_id=(previous.last_external_id if previous is not None else None),
            latest_published_at=(
                previous.latest_published_at if previous is not None else None
            ),
            metadata=(dict(previous.metadata) if previous is not None else {}),
        )

    @staticmethod
    def _checkpoint(
        *,
        invocation: MediaCrawlerInvocation,
        items: list[dict[str, Any]],
        next_page: int,
        last_completed_page: int,
        cycle_complete: bool,
        stopped_by_watermark: bool = False,
    ) -> MediaCrawlerCheckpoint:
        previous = invocation.checkpoint
        external_id = last_item_external_id(invocation.platform, items)
        published_at = latest_item_timestamp(invocation.platform, items)
        return build_search_checkpoint(
            platform=invocation.platform,
            next_page=next_page,
            last_external_id=(
                external_id
                if external_id is not None
                else (previous.last_external_id if previous is not None else None)
            ),
            latest_published_at=(
                published_at
                if published_at is not None
                else (previous.latest_published_at if previous is not None else None)
            ),
            last_completed_page=last_completed_page,
            cycle_complete=cycle_complete,
            stopped_by_watermark=stopped_by_watermark,
        )

    @classmethod
    def _comments_for_page(
        cls,
        platform: MediaCrawlerPlatform,
        page_items: list[dict[str, Any]],
        raw_items: list[dict[str, Any]],
        comments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if platform is not MediaCrawlerPlatform.BAIDU_TIEBA or len(page_items) == len(raw_items):
            return comments
        allowed = {
            value
            for value in (cls._raw_external_id(platform, item) for item in page_items)
            if value is not None
        }
        return [
            comment
            for comment in comments
            if cls._raw_comment_parent_id(platform, comment) in allowed
        ]

    @staticmethod
    def _raw_external_id(
        platform: MediaCrawlerPlatform,
        item: dict[str, Any],
    ) -> str | None:
        field = {
            MediaCrawlerPlatform.WEIBO: "note_id",
            MediaCrawlerPlatform.BILIBILI: "video_id",
            MediaCrawlerPlatform.ZHIHU: "content_id",
            MediaCrawlerPlatform.DOUYIN: "aweme_id",
            MediaCrawlerPlatform.XIAOHONGSHU: "note_id",
            MediaCrawlerPlatform.KUAISHOU: "video_id",
            MediaCrawlerPlatform.BAIDU_TIEBA: "note_id",
        }[platform]
        value = item.get(field)
        return str(value).strip() if value is not None and str(value).strip() else None

    @staticmethod
    def _raw_comment_parent_id(
        platform: MediaCrawlerPlatform,
        comment: dict[str, Any],
    ) -> str | None:
        field = {
            MediaCrawlerPlatform.WEIBO: "note_id",
            MediaCrawlerPlatform.BILIBILI: "video_id",
            MediaCrawlerPlatform.ZHIHU: "content_id",
            MediaCrawlerPlatform.DOUYIN: "aweme_id",
            MediaCrawlerPlatform.XIAOHONGSHU: "note_id",
            MediaCrawlerPlatform.KUAISHOU: "video_id",
            MediaCrawlerPlatform.BAIDU_TIEBA: "note_id",
        }[platform]
        value = comment.get(field)
        return str(value).strip() if value is not None and str(value).strip() else None


class MediaCrawlerResilienceAdapter:
    """Adapter for protocol 1.1 structured risks while Risk Guard remains authoritative."""

    def __init__(self, runner: EnvelopeRunner, *, timeout_seconds: int = 900) -> None:
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    async def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "protocol_version": MEDIACRAWLER_PROTOCOL_VERSION}

    async def invoke(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        envelope = await self.runner.run(invocation)
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
