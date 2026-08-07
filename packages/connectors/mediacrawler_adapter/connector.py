from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from packages.common.config import get_settings
from packages.connectors.base import (
    BaseConnector,
    CollectionItemError,
    CollectionResult,
    CollectionRiskSignal,
    CollectRequest,
)
from packages.connectors.mediacrawler_adapter.account_profile import (
    BrowserProfileResolver,
    MediaCrawlerAccountContext,
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
    LoginState,
    MediaCrawlerCheckpoint,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerProfileContext,
    MediaCrawlerResultEnvelope,
)
from packages.risk_guard.models import AccountStatus


class ConnectorCapabilityError(ValueError):
    """Requested mode is outside the platform's effective capability."""


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
                f"{platform.value} does not support MediaCrawler mode {mode.value} "
                "in the current implementation"
            )

        account_context = self._account_context(request)
        profile_context = MediaCrawlerProfileContext(
            account_configured=account_context is not None,
            browser_profile_configured=bool(
                account_context and account_context.browser_profile_ref
            ),
            login_state=(
                account_context.login_state
                if account_context is not None
                else LoginState.UNKNOWN
            ),
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
        checkpoint = self._checkpoint(
            request.checkpoint,
            platform=platform,
            mode=mode,
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
                checkpoint=checkpoint,
                account_ref=request.account_ref or request.account_id,
                browser_profile_ref=request.browser_profile_ref,
                profile_context=profile_context,
                timeout_seconds=timeout_seconds,
            )
        )
        return self._to_collection_result(
            envelope,
            allow_comments=include_comments,
        )

    def _account_context(
        self,
        request: CollectRequest,
    ) -> MediaCrawlerAccountContext | None:
        if isinstance(request.runtime_context, MediaCrawlerAccountContext):
            context = request.runtime_context
        elif request.account_ref or request.account_id:
            account_value = request.account_ref or request.account_id
            assert account_value is not None
            context = MediaCrawlerAccountContext(
                platform_account_id=UUID(account_value),
                account_identifier=account_value,
                credential_ref=None,
                browser_profile_ref=request.browser_profile_ref,
                account_status=AccountStatus.HEALTHY,
                cooldown_until=None,
                manual_review_required=False,
                login_state=LoginState.UNKNOWN,
            )
        else:
            return None
        context.ensure_runnable()
        if context.browser_profile_ref is not None:
            settings = get_settings()
            BrowserProfileResolver(
                Path(settings.mediacrawler_profile_root)
            ).resolve(context)
        return context

    @staticmethod
    def _checkpoint(
        raw: dict[str, Any] | None,
        *,
        platform: MediaCrawlerPlatform,
        mode: MediaCrawlerMode,
    ) -> MediaCrawlerCheckpoint | None:
        if raw is None:
            return None
        try:
            return MediaCrawlerCheckpoint.model_validate(raw)
        except ValidationError:
            cursor = (
                raw.get("cursor")
                if isinstance(raw.get("cursor"), dict)
                else None
            )
            page_value = raw.get("page")
            if page_value is None and cursor is not None:
                page_value = cursor.get("page")
            metadata = (
                raw.get("metadata")
                if isinstance(raw.get("metadata"), dict)
                else {}
            )
            return MediaCrawlerCheckpoint(
                platform=platform,
                mode=mode,
                cursor=cursor,
                page=(
                    page_value
                    if isinstance(page_value, int) and page_value >= 1
                    else None
                ),
                last_external_id=_string_or_none(raw.get("last_external_id")),
                latest_published_at=raw.get("latest_published_at"),
                metadata=metadata,
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
            CollectionItemError(error.code, error.message, error.external_ref)
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
                f"{envelope.platform.value} mapper could not recognize the result format",
            )

        if envelope.comments and not allow_comments:
            failed_comments = len(envelope.comments)
            errors.append(
                CollectionItemError(
                    "mediacrawler_unexpected_comments",
                    "MediaCrawler returned comments although comment collection was disabled",
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

        risk_signals = tuple(
            CollectionRiskSignal(
                platform=event.platform.value,
                source_error_code=event.source_error_code,
                standard_error_code=event.standard_error_code,
                severity=event.severity.value,
                retryable=event.retryable,
                action_hint=event.action_hint,
                requires_manual_review=event.requires_manual_review,
                message=event.message,
                checkpoint_safe_to_commit=event.checkpoint_safe_to_commit,
                metadata=dict(event.metadata),
            )
            for event in envelope.risk_events
        )
        return CollectionResult(
            signals=tuple(signals),
            checkpoint=(
                envelope.checkpoint.model_dump(mode="json")
                if envelope.checkpoint is not None
                else None
            ),
            errors=tuple(errors[:100]),
            metadata={
                "mediacrawler_protocol_version": envelope.protocol_version,
                "mediacrawler_status": envelope.status.value,
                "mediacrawler_counters": envelope.counters.model_dump(mode="json"),
                "mediacrawler_features": envelope.feature_metadata.model_dump(
                    mode="json"
                ),
                "mapped_count": len(signals),
                "failed_map_count": failed_items,
                "mapped_comment_count": len(comments),
                "failed_comment_map_count": failed_comments,
                "mediacrawler_warning_count": len(envelope.warnings),
                "mediacrawler_risk_signal_count": len(risk_signals),
            },
            comments=tuple(comments),
            risk_signals=risk_signals,
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
            resolved = default
        else:
            resolved = int(value)
        return max(minimum, min(maximum, resolved))


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
