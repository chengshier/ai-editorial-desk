from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
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
    parameters: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    platform: str | None = None
    account_ref: str | None = None
    browser_profile_ref: str | None = None


@dataclass(slots=True)
class RawSignal:
    """Connector-owned domain output with no ORM or transaction behavior."""

    platform: str
    external_id: str | None
    url: str
    canonical_url: str | None = None
    title: str | None = None
    text: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None
    metrics: dict[str, int | float] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    language: str | None = None

    def __post_init__(self) -> None:
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("published_at 必须包含时区")
        for key, value in self.metrics.items():
            if not isinstance(key, str):
                raise TypeError("metrics 键必须是字符串")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("metrics 值必须是可序列化数值")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("metrics 浮点值必须是有限数值")
        try:
            json.dumps(self.media, ensure_ascii=False, allow_nan=False)
            json.dumps(self.raw_payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise TypeError("media 和 raw_payload 必须可 JSON 序列化") from exc


@dataclass(slots=True, frozen=True)
class CollectionItemError:
    code: str
    message: str
    external_ref: str | None = None


@dataclass(slots=True, frozen=True)
class CollectionResult:
    signals: tuple[RawSignal, ...]
    checkpoint: dict[str, Any] | None = None
    not_modified: bool = False
    errors: tuple[CollectionItemError, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Stable boundary between platform collectors and the editorial system."""

    connector_type: str

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def collect(self, request: CollectRequest) -> CollectionResult:
        raise NotImplementedError

    async def fetch_detail(self, external_id: str) -> RawSignal:
        raise NotImplementedError(f"{self.connector_type} does not implement detail collection")
