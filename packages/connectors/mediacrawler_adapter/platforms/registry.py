from __future__ import annotations

from packages.connectors.mediacrawler_adapter.platforms.base import PlatformMapper
from packages.connectors.mediacrawler_adapter.platforms.bilibili import BilibiliMapper
from packages.connectors.mediacrawler_adapter.platforms.douyin import DouyinMapper
from packages.connectors.mediacrawler_adapter.platforms.kuaishou import KuaishouMapper
from packages.connectors.mediacrawler_adapter.platforms.tieba import TiebaMapper
from packages.connectors.mediacrawler_adapter.platforms.weibo import WeiboMapper
from packages.connectors.mediacrawler_adapter.platforms.xiaohongshu import XiaohongshuMapper
from packages.connectors.mediacrawler_adapter.platforms.zhihu import ZhihuMapper


class MediaCrawlerMapperRegistry:
    """Explicit seven-platform mapper registry; unknown platforms never fall back."""

    def __init__(self) -> None:
        self._mappers: dict[str, PlatformMapper] = {}

    def register(self, mapper: PlatformMapper) -> None:
        if mapper.platform in self._mappers:
            raise ValueError(f"duplicate MediaCrawler mapper: {mapper.platform}")
        self._mappers[mapper.platform] = mapper

    def get(self, platform: str) -> PlatformMapper:
        try:
            return self._mappers[platform]
        except KeyError as exc:
            raise ValueError(f"unsupported MediaCrawler mapper platform: {platform}") from exc

    def platforms(self) -> frozenset[str]:
        return frozenset(self._mappers)


def build_mapper_registry() -> MediaCrawlerMapperRegistry:
    registry = MediaCrawlerMapperRegistry()
    for mapper in (
        WeiboMapper(),
        BilibiliMapper(),
        ZhihuMapper(),
        DouyinMapper(),
        XiaohongshuMapper(),
        KuaishouMapper(),
        TiebaMapper(),
    ):
        registry.register(mapper)
    return registry


mediacrawler_mapper_registry = build_mapper_registry()
