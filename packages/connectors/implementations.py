from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from packages.common.config import get_settings
from packages.connectors.hotlist import BaiduRealtimeHotlistConnector
from packages.connectors.http import SafeHTTPFetcher
from packages.connectors.manual import ManualURLConnector
from packages.connectors.mediacrawler_adapter import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.resilience import (
    MediaCrawlerResilienceRunner,
    ResumePageRunner,
)
from packages.connectors.mediacrawler_adapter.resilient_adapter import (
    MediaCrawlerResilienceAdapter,
)
from packages.connectors.registry import ConnectorRegistry
from packages.connectors.rss import RSSConnector

FetcherFactory = Callable[[], SafeHTTPFetcher]


def _build_mediacrawler_connector() -> MediaCrawlerConnector:
    settings = get_settings()
    page_runner = ResumePageRunner(
        home=Path(settings.mediacrawler_home),
        python_executable=settings.mediacrawler_python,
    )
    resilience_runner = MediaCrawlerResilienceRunner(
        page_runner,
        max_technical_attempts=3,
    )
    return MediaCrawlerConnector(
        MediaCrawlerResilienceAdapter(resilience_runner, settings=settings)
    )


def build_implementation_registry(
    fetcher_factory: FetcherFactory | None = None,
) -> ConnectorRegistry:
    """Register implementations that are runnable through the main CollectorRuntime."""

    create_fetcher = fetcher_factory or SafeHTTPFetcher
    registry = ConnectorRegistry()
    registry.register("rss", lambda: RSSConnector(create_fetcher()))
    registry.register("manual", lambda: ManualURLConnector(create_fetcher()))
    registry.register("hotlist", lambda: BaiduRealtimeHotlistConnector(create_fetcher()))
    registry.register("mediacrawler", _build_mediacrawler_connector)
    return registry


implementation_registry = build_implementation_registry()

__all__ = ["build_implementation_registry", "implementation_registry"]
