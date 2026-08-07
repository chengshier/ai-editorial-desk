from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from packages.connectors.mediacrawler_adapter.protocol import MediaCrawlerPlatform


class DiscoveryKind(StrEnum):
    HOMEFEED = "homefeed"
    HOTLIST = "hotlist"


@dataclass(slots=True, frozen=True)
class DiscoveryPolicy:
    enabled_by_default: bool = False
    max_concurrency: int = 1
    max_requested_limit: int = 20


class DiscoveryHook(Protocol):
    platform: MediaCrawlerPlatform
    kind: DiscoveryKind


class DiscoveryHookUnavailable(ValueError):
    pass


class DiscoveryHookRegistry:
    """Explicit opt-in extension point; M2-C intentionally registers no hooks."""

    def __init__(self) -> None:
        self._hooks: dict[tuple[MediaCrawlerPlatform, DiscoveryKind], DiscoveryHook] = {}

    def register(self, hook: DiscoveryHook) -> None:
        key = (hook.platform, hook.kind)
        if key in self._hooks:
            raise ValueError(
                f"discovery hook already registered: {hook.platform.value}/{hook.kind.value}"
            )
        self._hooks[key] = hook

    def is_available(
        self,
        platform: MediaCrawlerPlatform | str,
        kind: DiscoveryKind | str,
    ) -> bool:
        return (MediaCrawlerPlatform(platform), DiscoveryKind(kind)) in self._hooks

    def get(
        self,
        platform: MediaCrawlerPlatform | str,
        kind: DiscoveryKind | str,
    ) -> DiscoveryHook:
        key = (MediaCrawlerPlatform(platform), DiscoveryKind(kind))
        try:
            return self._hooks[key]
        except KeyError as exc:
            raise DiscoveryHookUnavailable(
                f"discovery hook is unavailable: {key[0].value}/{key[1].value}"
            ) from exc


SAFE_DISCOVERY_POLICY = DiscoveryPolicy()
discovery_hook_registry = DiscoveryHookRegistry()
