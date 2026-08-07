from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class HotlistItem:
    rank: int
    title: str
    url: str
    hot_score: int | float | None = None
    category: str | None = None
    published_at: datetime | None = None
    source: str = ""
    description: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class HotlistParser(Protocol):
    def parse(self, payload: bytes, *, limit: int) -> tuple[HotlistItem, ...]: ...
