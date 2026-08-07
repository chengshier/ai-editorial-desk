from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.connectors.base import (
    BaseConnector,
    CollectionItemError,
    CollectionResult,
    CollectRequest,
    RawSignal,
)
from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
)


class MediaCrawlerConnector(BaseConnector):
    """Main-system Connector wrapper around the versioned MediaCrawler Adapter."""

    connector_type = "mediacrawler"

    def __init__(self, adapter: MediaCrawlerAdapter | None = None) -> None:
        self.adapter = adapter or MediaCrawlerAdapter()

    async def health_check(self) -> dict[str, Any]:
        return await self.adapter.health_check()

    async def collect(self, request: CollectRequest) -> CollectionResult:
        if request.run_id is None or request.platform is None:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MALFORMED,
                "MediaCrawler collection requires Runtime run_id and platform context",
            )
        try:
            mode = MediaCrawlerMode(request.mode)
            platform = MediaCrawlerPlatform(request.platform)
        except ValueError as exc:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MALFORMED,
                "MediaCrawler collection request is outside the M2-A protocol",
            ) from exc

        parameters = dict(request.parameters)
        target_ids = request.target_ids or self._string_tuple(parameters.get("target_ids"))
        keyword: str | None = None
        creator_id: str | None = None
        content_ids: tuple[str, ...] = ()
        if mode is MediaCrawlerMode.SEARCH:
            keyword = request.query or self._first_string(parameters.get("keywords"))
        elif mode is MediaCrawlerMode.ACCOUNT:
            creator_id = request.query or (target_ids[0] if target_ids else None)
        elif mode in {MediaCrawlerMode.DETAIL, MediaCrawlerMode.COMMENTS}:
            content_ids = target_ids or ((request.query,) if request.query else ())

        include_comments = bool(parameters.get("include_comments", False))
        if mode is MediaCrawlerMode.COMMENTS:
            include_comments = True
        include_subcomments = bool(parameters.get("include_subcomments", False))
        comment_limit = min(
            100,
            max(
                0,
                self._integer_value(
                    parameters.get("comment_limit"),
                    default=20 if include_comments else 0,
                ),
            ),
        )
        if not include_comments:
            include_subcomments = False
            comment_limit = 0

        invocation = MediaCrawlerInvocation(
            run_id=request.run_id,
            platform=platform,
            mode=mode,
            source_id=request.source_id,
            keyword=keyword,
            creator_id=creator_id,
            content_ids=content_ids,
            requested_limit=request.limit,
            comment_limit=comment_limit,
            include_comments=include_comments,
            include_subcomments=include_subcomments,
            checkpoint=request.checkpoint,
            account_ref=request.account_ref or request.account_id,
            browser_profile_ref=request.browser_profile_ref,
            timeout_seconds=self.adapter.settings.mediacrawler_timeout_seconds,
        )
        envelope = await self.adapter.invoke(invocation)
        return self._to_collection_result(envelope)

    def _to_collection_result(
        self,
        envelope: MediaCrawlerResultEnvelope,
    ) -> CollectionResult:
        signals: list[RawSignal] = []
        item_errors: list[CollectionItemError] = [
            CollectionItemError(
                code=error.code,
                message=error.message,
                external_ref=error.external_ref,
            )
            for error in envelope.errors
        ]
        for item in envelope.items:
            try:
                signals.append(self._map_standard_item(item, envelope.platform.value))
            except (TypeError, ValueError):
                item_errors.append(
                    CollectionItemError(
                        code="mediacrawler_item_unmapped",
                        message="MediaCrawler item is not yet in the M2-A standard item shape",
                        external_ref=self._safe_external_ref(item),
                    )
                )
                if len(item_errors) >= 100:
                    break

        return CollectionResult(
            signals=tuple(signals),
            checkpoint=envelope.checkpoint,
            errors=tuple(item_errors),
            metadata={
                "mediacrawler_protocol_version": envelope.protocol_version,
                "mediacrawler_status": envelope.status.value,
                "mediacrawler_counters": envelope.counters.model_dump(mode="json"),
                "mediacrawler_warning_count": len(envelope.warnings),
                "mediacrawler_comment_count": len(envelope.comments),
            },
        )

    @staticmethod
    def _map_standard_item(item: dict[str, Any], platform: str) -> RawSignal:
        external_id = item.get("external_id")
        url = item.get("url")
        if not isinstance(external_id, (str, int)) or not str(external_id).strip():
            raise ValueError("external_id missing")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url missing")

        published_at: datetime | None = None
        raw_published_at = item.get("published_at")
        if isinstance(raw_published_at, str) and raw_published_at:
            try:
                published_at = datetime.fromisoformat(raw_published_at.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
            if published_at is not None and (
                published_at.tzinfo is None or published_at.utcoffset() is None
            ):
                published_at = None

        metrics: dict[str, int | float] = {}
        raw_metrics = item.get("metrics")
        if isinstance(raw_metrics, dict):
            for key, value in raw_metrics.items():
                if isinstance(key, str) and not isinstance(value, bool) and isinstance(
                    value, (int, float)
                ):
                    metrics[key] = value

        media: list[dict[str, Any]] = []
        raw_media = item.get("media")
        if isinstance(raw_media, list):
            media = [entry for entry in raw_media if isinstance(entry, dict)]

        return RawSignal(
            platform=platform,
            external_id=str(external_id),
            url=url,
            canonical_url=item.get("canonical_url")
            if isinstance(item.get("canonical_url"), str)
            else None,
            title=item.get("title") if isinstance(item.get("title"), str) else None,
            text=item.get("text") if isinstance(item.get("text"), str) else None,
            author_id=item.get("author_id")
            if isinstance(item.get("author_id"), str)
            else None,
            author_name=item.get("author_name")
            if isinstance(item.get("author_name"), str)
            else None,
            published_at=published_at,
            metrics=metrics,
            media=media,
            raw_payload=item,
            language=item.get("language") if isinstance(item.get("language"), str) else None,
        )

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, str) and item.strip())

    @staticmethod
    def _first_string(value: Any) -> str | None:
        values = MediaCrawlerConnector._string_tuple(value)
        return values[0] if values else None

    @staticmethod
    def _integer_value(value: Any, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        return default

    @staticmethod
    def _safe_external_ref(item: dict[str, Any]) -> str | None:
        value = item.get("external_id")
        if isinstance(value, (str, int)):
            return str(value)[:500]
        return None
