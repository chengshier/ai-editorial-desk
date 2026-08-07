from __future__ import annotations

from collections.abc import Callable

from packages.connectors.hotlist import BaiduRealtimeHotlistConnector
from packages.connectors.http import SafeHTTPFetcher
from packages.connectors.manual import ManualURLConnector
from packages.connectors.registry import ConnectorRegistry
from packages.connectors.rss import RSSConnector

FetcherFactory = Callable[[], SafeHTTPFetcher]


def build_implementation_registry(
    fetcher_factory: FetcherFactory | None = None,
) -> ConnectorRegistry:
    """Register only implementations that are genuinely runnable in M1."""

    create_fetcher = fetcher_factory or SafeHTTPFetcher
    registry = ConnectorRegistry()
    registry.register("rss", lambda: RSSConnector(create_fetcher()))
    registry.register("manual", lambda: ManualURLConnector(create_fetcher()))
    registry.register("hotlist", lambda: BaiduRealtimeHotlistConnector(create_fetcher()))
    return registry


implementation_registry = build_implementation_registry()

__all__ = ["build_implementation_registry", "implementation_registry"]
