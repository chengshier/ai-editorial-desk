from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class CollectRequest:
    source_id: str
    mode: str
    query: str | None = None
    target_ids: tuple[str, ...] = ()
    cursor: str | None = None
    since: datetime | None = None
    limit: int = 100
    account_id: str | None = None
    risk_policy_id: str | None = None
    checkpoint: dict[str, Any] | None = None


@dataclass(slots=True)
class RawSignal:
    platform: str
    external_id: str
    url: str
    title: str | None = None
    text: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None
    metrics: dict[str, int | float] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Stable boundary between platform collectors and the editorial system."""

    connector_type: str

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def collect(self, request: CollectRequest) -> AsyncIterator[RawSignal]:
        raise NotImplementedError

    async def fetch_detail(self, external_id: str) -> RawSignal:
        raise NotImplementedError(f"{self.connector_type} does not implement detail collection")
