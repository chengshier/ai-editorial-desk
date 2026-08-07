"""Stable main-system boundary for the vendored MediaCrawler collector."""

from packages.connectors.mediacrawler_adapter.adapter import MediaCrawlerAdapter
from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerInvocation,
    MediaCrawlerResultEnvelope,
)
from packages.connectors.mediacrawler_adapter.runner import MediaCrawlerSubprocessRunner

__all__ = [
    "MEDIACRAWLER_PROTOCOL_VERSION",
    "MediaCrawlerAdapter",
    "MediaCrawlerAdapterError",
    "MediaCrawlerConnector",
    "MediaCrawlerErrorCode",
    "MediaCrawlerInvocation",
    "MediaCrawlerResultEnvelope",
    "MediaCrawlerSubprocessRunner",
]
