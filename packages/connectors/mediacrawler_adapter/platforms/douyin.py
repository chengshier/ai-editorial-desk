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
    split_urls,
)


class DouyinMapper(PlatformMapper):
    platform = "douyin"

    def validate_item(self, item: dict[str, Any]) -> None:
        aweme_id = required_id(item.get("aweme_id"), field="aweme_id")
        if safe_url(item.get("aweme_url")) is None:
            raise MapperDataError("aweme_url missing", external_ref=aweme_id)

    def map_item(self, item: dict[str, Any]) -> RawSignal:
        self.validate_item(item)
        aweme_id = required_id(item.get("aweme_id"), field="aweme_id")
        url = safe_url(item.get("aweme_url"))
        assert url is not None
        return RawSignal(
            platform=self.platform,
            external_id=aweme_id,
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
        content_id = required_id(comment.get("aweme_id"), field="aweme_id")
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
                "collect_count": "collected_count",
                "comment_count": "comment_count",
                "share_count": "share_count",
            },
        )

    def normalize_media(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        video = media_entry(
            media_type="video",
            index=0,
            url=item.get("video_download_url"),
            thumbnail_url=item.get("cover_url"),
        )
        if video is not None:
            output.append(video)
        for image_url in split_urls(item.get("note_download_url")):
            output.append({"type": "image", "url": image_url, "index": len(output)})
        audio = media_entry(
            media_type="audio",
            index=len(output),
            url=item.get("music_download_url"),
        )
        if audio is not None:
            output.append(audio)
        return output
