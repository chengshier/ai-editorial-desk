from __future__ import annotations

from typing import Any

from packages.connectors.base import CollectedComment, RawSignal
from packages.connectors.mediacrawler_adapter.platforms.base import (
    MapperDataError,
    PlatformMapper,
    metrics_from,
    optional_text,
    parse_datetime,
    required_id,
    safe_url,
    sanitize_payload,
)


class TiebaMapper(PlatformMapper):
    platform = "baidu_tieba"

    def validate_item(self, item: dict[str, Any]) -> None:
        note_id = required_id(item.get("note_id"), field="note_id")
        if safe_url(item.get("note_url")) is None:
            raise MapperDataError("note_url missing", external_ref=note_id)

    def map_item(self, item: dict[str, Any]) -> RawSignal:
        self.validate_item(item)
        note_id = required_id(item.get("note_id"), field="note_id")
        url = safe_url(item.get("note_url"))
        assert url is not None
        return RawSignal(
            platform=self.platform,
            external_id=note_id,
            url=url,
            title=optional_text(item.get("title")),
            text=optional_text(item.get("desc")),
            author_id=optional_text(item.get("creator_hash")),
            author_name=optional_text(item.get("user_nickname")),
            published_at=parse_datetime(item.get("publish_time")),
            metrics=self.normalize_metrics(item),
            media=self.normalize_media(item),
            raw_payload=sanitize_payload(item),
        )

    def map_comment(self, comment: dict[str, Any]) -> CollectedComment:
        content_id = required_id(comment.get("note_id"), field="note_id")
        comment_id = required_id(comment.get("comment_id"), field="comment_id")
        text = optional_text(comment.get("content"))
        if text is None:
            raise MapperDataError("comment content missing", external_ref=comment_id)
        return CollectedComment(
            platform=self.platform,
            content_external_id=content_id,
            external_comment_id=comment_id,
            author_id=optional_text(comment.get("creator_hash")),
            author_name=optional_text(comment.get("user_nickname")),
            text=text,
            published_at=parse_datetime(comment.get("publish_time")),
            like_count=None,
            parent_comment_id=optional_text(comment.get("parent_comment_id")),
            raw_payload=sanitize_payload(comment),
        )

    def normalize_metrics(self, item: dict[str, Any]) -> dict[str, int | float]:
        return metrics_from(item, {"comment_count": "total_replay_num"})

    def normalize_media(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        del item
        return []
