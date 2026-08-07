from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.connectors.base import (
    BaseConnector,
    CollectionItemError,
    CollectionResult,
    CollectRequest,
)
from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.platforms.base import MapperDataError
from packages.connectors.mediacrawler_adapter.platforms.registry import (
    mediacrawler_mapper_registry,
)
from packages.connectors.mediacrawler_adapter.platforms.specs import get_platform_spec
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
)


class ConnectorCapabilityError(ValueError):
    """Requested mode is outside the platform's effective M2-B capability."""


class MediaCrawlerConnector(BaseConnector):
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
            run_id = UUID(request.run_id)
            source_id = UUID(request.source_id)
        except ValueError as exc:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RESULT_MALFORMED,
                "MediaCrawler collection request is outside the versioned protocol",
            ) from exc

        spec = get_platform_spec(platform.value)
        if mode.value not in spec.allowed_modes:
            raise ConnectorCapabilityError(
                f"{platform.value} does not support MediaCrawler mode "
                f"{mode.value} in M2-B"
            )

        parameters = dict(request.parameters)
        keyword: str | None = None
        creator_id: str | None = None
        content_ids: tuple[str, ...] = ()
        if mode is MediaCrawlerMode.SEARCH:
            keyword = (
                request.query
                or self._string_value(parameters.get("keyword"))
                or self._first_string(parameters.get("keywords"))
            )
            if keyword is None:
                raise ConnectorCapabilityError("search mode requires keyword")
        elif mode is MediaCrawlerMode.ACCOUNT:
            creator_id = request.query or self._string_value(
                parameters.get("creator_id")
            )
            if creator_id is None:
                raise ConnectorCapabilityError("account mode requires creator_id")
        elif mode in {MediaCrawlerMode.DETAIL, MediaCrawlerMode.COMMENTS}:
            content_ids = (
                request.target_ids
                or self._string_tuple(parameters.get("content_ids"))
                or self._string_tuple(parameters.get("target_ids"))
            )
            if not content_ids and request.query:
                content_ids = (request.query,)
            if not content_ids:
                raise ConnectorCapabilityError(
                    f"{mode.value} mode requires content_ids"
                )

        include_comments = (
            bool(parameters.get("include_comments", False))
            or mode is MediaCrawlerMode.COMMENTS
        )
        if include_comments and not spec.comments:
            raise ConnectorCapabilityError(
                f"{platform.value} does not support comments"
            )
        include_subcomments = bool(parameters.get("include_subcomments", False))
        if include_subcomments and not include_comments:
            raise ConnectorCapabilityError(
                "include_subcomments requires include_comments"
            )
        comment_limit = self._bounded_integer(
            parameters.get("comment_limit"),
            default=20 if include_comments else 0,
            minimum=0,
            maximum=50,
        )
        if not include_comments:
            comment_limit = 0
            include_subcomments = False
        timeout_seconds = self._bounded_integer(
            parameters.get("timeout_seconds"),
            default=self.adapter.settings.mediacrawler_timeout_seconds,
            minimum=30,
            maximum=1800,
        )

        envelope = await self.adapter.invoke(
            MediaCrawlerInvocation(
                run_id=run_id,
                platform=platform,
                mode=mode,
                source_id=source_id,
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
                timeout_seconds=timeout_seconds,
            )
        )
        return self._to_collection_result(
            envelope,
            allow_comments=include_comments,
        )

    def _to_collection_result(
        self,
        envelope: MediaCrawlerResultEnvelope,
        *,
        allow_comments: bool,
    ) -> CollectionResult:
        mapper = mediacrawler_mapper_registry.get(envelope.platform.value)
        signals = []
        comments = []
        errors = [
            CollectionItemError(
                error.code,
                error.message,
                error.external_ref,
            )
            for error in envelope.errors
        ]
        failed_items = 0
        failed_comments = 0

        for item in envelope.items:
            try:
                signals.append(mapper.map_item(item))
            except (MapperDataError, TypeError, ValueError) as exc:
                failed_items += 1
                errors.append(
                    CollectionItemError(
                        "mediacrawler_item_unmapped",
                        "MediaCrawler item failed platform mapping",
                        getattr(exc, "external_ref", None),
                    )
                )
        if envelope.items and not signals:
            raise MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.PARSE_ERROR,
                f"{envelope.platform.value} mapper could not recognize "
                "the result format",
            )

        if envelope.comments and not allow_comments:
            failed_comments = len(envelope.comments)
            errors.append(
                CollectionItemError(
                    "mediacrawler_unexpected_comments",
                    "MediaCrawler returned comments although comment collection "
                    "was disabled",
                    None,
                )
            )
        else:
            for comment in envelope.comments:
                try:
                    comments.append(mapper.map_comment(comment))
                except (MapperDataError, TypeError, ValueError) as exc:
                    failed_comments += 1
                    errors.append(
                        CollectionItemError(
                            "mediacrawler_comment_unmapped",
                            "MediaCrawler comment failed platform mapping",
                            getattr(exc, "external_ref", None),
                        )
                    )

        return CollectionResult(
            signals=tuple(signals),
            checkpoint=envelope.checkpoint,
            errors=tuple(errors[:100]),
            metadata={
                "mediacrawler_protocol_version": envelope.protocol_version,
                "mediacrawler_status": envelope.status.value,
                "mediacrawler_counters": envelope.counters.model_dump(mode="json"),
                "mapped_count": len(signals),
                "failed_map_count": failed_items,
                "mapped_comment_count": len(comments),
                "failed_comment_map_count": failed_comments,
                "mediacrawler_warning_count": len(envelope.warnings),
            },
            comments=tuple(comments),
        )

    @staticmethod
    def _string_value(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )

    @classmethod
    def _first_string(cls, value: Any) -> str | None:
        values = cls._string_tuple(value)
        return values[0] if values else None

    @staticmethod
    def _bounded_integer(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return max(minimum, min(maximum, default))
        return max(minimum, min(maximum, value))
