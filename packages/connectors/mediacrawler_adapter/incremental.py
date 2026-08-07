from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from packages.connectors.mediacrawler_adapter.platforms.base import parse_datetime
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerCheckpoint,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
)


class IncrementalOrdering(StrEnum):
    UNKNOWN = "unknown"
    TIME_DESC = "time_desc"


@dataclass(slots=True, frozen=True)
class PlatformIncrementalSpec:
    platform: MediaCrawlerPlatform
    search_incremental: bool
    detail_incremental: bool
    creator_incremental: bool
    page_size: int
    ordering: IncrementalOrdering
    search_strategy: str
    upstream_creator_cursor: str | None = None
    replays_prefix_pages: bool = False


_INCREMENTAL_SPECS = {
    MediaCrawlerPlatform.WEIBO: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.WEIBO,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=10,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
        upstream_creator_cursor="since_id",
    ),
    MediaCrawlerPlatform.BILIBILI: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.BILIBILI,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=20,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
        upstream_creator_cursor="offset",
    ),
    MediaCrawlerPlatform.ZHIHU: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.ZHIHU,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=20,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
        upstream_creator_cursor="offset",
    ),
    MediaCrawlerPlatform.DOUYIN: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.DOUYIN,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=10,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
        upstream_creator_cursor="max_cursor",
    ),
    MediaCrawlerPlatform.XIAOHONGSHU: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.XIAOHONGSHU,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=20,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
    ),
    MediaCrawlerPlatform.KUAISHOU: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.KUAISHOU,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=20,
        ordering=IncrementalOrdering.UNKNOWN,
        search_strategy="page_resume_replay_window",
        upstream_creator_cursor="pcursor",
        replays_prefix_pages=True,
    ),
    MediaCrawlerPlatform.BAIDU_TIEBA: PlatformIncrementalSpec(
        platform=MediaCrawlerPlatform.BAIDU_TIEBA,
        search_incremental=True,
        detail_incremental=False,
        creator_incremental=False,
        page_size=50,
        ordering=IncrementalOrdering.TIME_DESC,
        search_strategy="page_resume_time_desc_watermark",
        upstream_creator_cursor="pn",
    ),
}


def get_incremental_spec(platform: MediaCrawlerPlatform | str) -> PlatformIncrementalSpec:
    normalized = MediaCrawlerPlatform(platform)
    try:
        return _INCREMENTAL_SPECS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported incremental platform: {normalized.value}") from exc


def supported_incremental_specs() -> tuple[PlatformIncrementalSpec, ...]:
    return tuple(_INCREMENTAL_SPECS.values())


def resume_page(checkpoint: MediaCrawlerCheckpoint | None) -> int:
    if checkpoint is None or checkpoint.page is None:
        return 1
    return checkpoint.page


def build_search_checkpoint(
    *,
    platform: MediaCrawlerPlatform,
    next_page: int,
    last_external_id: str | None,
    latest_published_at: datetime | None,
    last_completed_page: int,
    cycle_complete: bool,
    stopped_by_watermark: bool = False,
) -> MediaCrawlerCheckpoint:
    spec = get_incremental_spec(platform)
    return MediaCrawlerCheckpoint(
        platform=platform,
        mode=MediaCrawlerMode.SEARCH,
        page=1 if cycle_complete else max(1, next_page),
        last_external_id=last_external_id,
        latest_published_at=latest_published_at,
        last_completed_scope=f"search:page:{last_completed_page}",
        metadata={
            "strategy": spec.search_strategy,
            "ordering": spec.ordering.value,
            "cycle_complete": cycle_complete,
            "stopped_by_watermark": stopped_by_watermark,
            "replays_prefix_pages": spec.replays_prefix_pages,
        },
    )


def latest_item_timestamp(
    platform: MediaCrawlerPlatform,
    items: list[dict[str, Any]],
) -> datetime | None:
    timestamp_fields = {
        MediaCrawlerPlatform.WEIBO: "create_time",
        MediaCrawlerPlatform.BILIBILI: "create_time",
        MediaCrawlerPlatform.ZHIHU: "created_time",
        MediaCrawlerPlatform.DOUYIN: "create_time",
        MediaCrawlerPlatform.XIAOHONGSHU: "time",
        MediaCrawlerPlatform.KUAISHOU: "create_time",
        MediaCrawlerPlatform.BAIDU_TIEBA: "publish_time",
    }
    field = timestamp_fields[platform]
    values = [parse_datetime(item.get(field)) for item in items]
    parsed = [value for value in values if value is not None]
    return max(parsed) if parsed else None


def last_item_external_id(
    platform: MediaCrawlerPlatform,
    items: list[dict[str, Any]],
) -> str | None:
    id_fields = {
        MediaCrawlerPlatform.WEIBO: "note_id",
        MediaCrawlerPlatform.BILIBILI: "video_id",
        MediaCrawlerPlatform.ZHIHU: "content_id",
        MediaCrawlerPlatform.DOUYIN: "aweme_id",
        MediaCrawlerPlatform.XIAOHONGSHU: "note_id",
        MediaCrawlerPlatform.KUAISHOU: "video_id",
        MediaCrawlerPlatform.BAIDU_TIEBA: "note_id",
    }
    field = id_fields[platform]
    for item in reversed(items):
        value = item.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def tieba_watermark_reached(
    *,
    items: list[dict[str, Any]],
    checkpoint: MediaCrawlerCheckpoint | None,
) -> bool:
    """Only Tieba search has a verified time-desc ordering in the pinned source."""

    if checkpoint is None:
        return False
    known_id = checkpoint.last_external_id
    watermark = checkpoint.latest_published_at
    if known_id is None and watermark is None:
        return False

    for item in items:
        external_id = item.get("note_id")
        if known_id is not None and external_id is not None:
            if str(external_id).strip() == known_id:
                return True
        if watermark is not None:
            published = parse_datetime(item.get("publish_time"))
            if published is not None and published <= watermark:
                return True
    return False


def filter_tieba_new_items(
    *,
    items: list[dict[str, Any]],
    checkpoint: MediaCrawlerCheckpoint | None,
) -> list[dict[str, Any]]:
    """Drop the known/older suffix only where pinned source guarantees time-desc ordering."""

    if checkpoint is None:
        return items
    known_id = checkpoint.last_external_id
    watermark = checkpoint.latest_published_at
    if known_id is None and watermark is None:
        return items

    fresh: list[dict[str, Any]] = []
    for item in items:
        external_id = item.get("note_id")
        if known_id is not None and external_id is not None:
            if str(external_id).strip() == known_id:
                break
        if watermark is not None:
            published = parse_datetime(item.get("publish_time"))
            if published is not None and published <= watermark:
                break
        fresh.append(item)
    return fresh
