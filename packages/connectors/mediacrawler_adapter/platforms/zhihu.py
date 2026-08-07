from __future__ import annotations

from typing import Any

from packages.connectors.base import CollectedComment, RawSignal
from packages.connectors.mediacrawler_adapter.platforms.base import (
    MapperDataError,
    PlatformMapper,
    metrics_from,
    optional_text,
    parse_datetime,
    parse_like_count,
    required_id,
    safe_url,
    sanitize_payload,
)


class ZhihuMapper(PlatformMapper):
    platform = "zhihu"

    @staticmethod
    def _content_url(item: dict[str, Any]) -> str | None:
        direct = safe_url(item.get("content_url"))
        if direct is not None:
            return direct
        content_id = optional_text(item.get("content_id"))
        content_type = optional_text(item.get("content_type"))
        if content_id is None or content_type is None:
            return None
        if content_type == "answer":
            question_id = optional_text(item.get("question_id"))
            if question_id:
                return f"https://www.zhihu.com/question/{question_id}/answer/{content_id}"
        if content_type == "article":
            return f"https://zhuanlan.zhihu.com/p/{content_id}"
        if content_type == "zvideo":
            return f"https://www.zhihu.com/zvideo/{content_id}"
        return None

    def validate_item(self, item: dict[str, Any]) -> None:
        content_id = required_id(item.get("content_id"), field="content_id")
        if self._content_url(item) is None:
            raise MapperDataError("content_url missing", external_ref=content_id)

    def map_item(self, item: dict[str, Any]) -> RawSignal:
        self.validate_item(item)
        content_id = required_id(item.get("content_id"), field="content_id")
        url = self._content_url(item)
        assert url is not None
        text = optional_text(item.get("content_text")) or optional_text(item.get("desc"))
        return RawSignal(
            platform=self.platform,
            external_id=content_id,
            url=url,
            title=optional_text(item.get("title")),
            text=text,
            author_id=optional_text(item.get("creator_hash")),
            author_name=optional_text(item.get("user_nickname")),
            published_at=parse_datetime(item.get("created_time")),
            metrics=self.normalize_metrics(item),
            media=self.normalize_media(item),
            raw_payload=sanitize_payload(item),
        )

    def map_comment(self, comment: dict[str, Any]) -> CollectedComment:
        content_id = required_id(comment.get("content_id"), field="content_id")
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
            like_count=parse_like_count(comment.get("like_count")),
            parent_comment_id=optional_text(comment.get("parent_comment_id")),
            raw_payload=sanitize_payload(comment),
        )

    def normalize_metrics(self, item: dict[str, Any]) -> dict[str, int | float]:
        return metrics_from(item, {"like_count": "voteup_count", "comment_count": "comment_count"})

    def normalize_media(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        del item
        return []
