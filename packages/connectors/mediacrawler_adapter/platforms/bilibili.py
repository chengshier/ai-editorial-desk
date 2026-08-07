from __future__ import annotations

from typing import Any

from packages.connectors.base import CollectedComment, RawSignal
from packages.connectors.mediacrawler_adapter.platforms.base import (
    MapperDataError,
    PlatformMapper,
    media_entry,
    metrics_from,
    optional_text,
    parse_datetime,
    parse_like_count,
    required_id,
    safe_url,
    sanitize_payload,
)


class BilibiliMapper(PlatformMapper):
    platform = "bilibili"

    def validate_item(self, item: dict[str, Any]) -> None:
        video_id = required_id(item.get("video_id"), field="video_id")
        if safe_url(item.get("video_url")) is None:
            raise MapperDataError("video_url missing", external_ref=video_id)

    def map_item(self, item: dict[str, Any]) -> RawSignal:
        self.validate_item(item)
        video_id = required_id(item.get("video_id"), field="video_id")
        url = safe_url(item.get("video_url"))
        assert url is not None
        return RawSignal(
            platform=self.platform,
            external_id=video_id,
            url=url,
            title=optional_text(item.get("title")),
            text=optional_text(item.get("desc")),
            author_id=optional_text(item.get("creator_hash")),
            author_name=optional_text(item.get("nickname")),
            published_at=parse_datetime(item.get("create_time")),
            metrics=self.normalize_metrics(item),
            media=self.normalize_media(item),
            raw_payload=sanitize_payload(item),
        )

    def map_comment(self, comment: dict[str, Any]) -> CollectedComment:
        content_id = required_id(comment.get("video_id"), field="video_id")
        comment_id = required_id(comment.get("comment_id"), field="comment_id")
        text = optional_text(comment.get("content"))
        if text is None:
            raise MapperDataError("comment content missing", external_ref=comment_id)
        parent = optional_text(comment.get("parent_comment_id"))
        if parent == "0":
            parent = None
        return CollectedComment(
            platform=self.platform,
            content_external_id=content_id,
            external_comment_id=comment_id,
            author_id=optional_text(comment.get("creator_hash")),
            author_name=optional_text(comment.get("nickname")),
            text=text,
            published_at=parse_datetime(comment.get("create_time")),
            like_count=parse_like_count(comment.get("like_count")),
            parent_comment_id=parent,
            raw_payload=sanitize_payload(comment),
        )

    def normalize_metrics(self, item: dict[str, Any]) -> dict[str, int | float]:
        return metrics_from(
            item,
            {
                "like_count": "liked_count",
                "dislike_count": "disliked_count",
                "view_count": "video_play_count",
                "favorite_count": "video_favorite_count",
                "share_count": "video_share_count",
                "coin_count": "video_coin_count",
                "danmaku_count": "video_danmaku",
                "comment_count": "video_comment",
            },
        )

    def normalize_media(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        entry = media_entry(
            media_type="video",
            index=0,
            thumbnail_url=item.get("video_cover_url"),
        )
        return [entry] if entry is not None else []
