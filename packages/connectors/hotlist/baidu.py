from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

from packages.connectors.base import BaseConnector, CollectionResult, CollectRequest, RawSignal
from packages.connectors.hotlist.protocol import HotlistItem
from packages.connectors.http import ConnectorFetchError, SafeHTTPFetcher

BAIDU_REALTIME_SOURCE = "baidu_realtime"
BAIDU_REALTIME_API = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
BAIDU_HOTLIST_USER_AGENT = "AI-Editorial-Desk/0.5 (+low-frequency-public-hotlist)"
JSON_CONTENT_TYPES = frozenset({"application/json", "text/json"})
MAX_HOTLIST_ITEMS = 50


class BaiduRealtimeParser:
    """Parse the two currently observed public Baidu board JSON nesting shapes."""

    def parse(self, payload: bytes, *, limit: int) -> tuple[HotlistItem, ...]:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorFetchError(
                "invalid_hotlist_json",
                "百度热榜返回了无法解析的 JSON",
                retryable=False,
            ) from exc
        if not isinstance(document, dict):
            raise ConnectorFetchError(
                "invalid_hotlist_payload",
                "百度热榜返回结构无效",
                retryable=False,
            )
        entries = self._extract_entries(document)
        if not entries:
            raise ConnectorFetchError(
                "empty_hotlist_payload",
                "百度热榜未返回可用榜单条目",
                retryable=False,
            )

        items: list[HotlistItem] = []
        normal_rank = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("word") or entry.get("query") or "").strip()
            if not title:
                continue
            is_top = bool(entry.get("isTop"))
            if is_top:
                rank = 0
            else:
                normal_rank += 1
                rank = normal_rank
            score = self._score(entry.get("hotScore"))
            url = self._url(entry, title)
            description = str(entry.get("desc") or "").strip() or None
            category = str(entry.get("category") or entry.get("typeName") or "").strip() or None
            safe_raw = {
                "rank": rank,
                "word": title,
                "hot_score": score,
                "category": category,
                "is_top": is_top,
                "hot_change": entry.get("hotChange"),
                "hot_tag": entry.get("newHotName") or entry.get("hotTag"),
            }
            items.append(
                HotlistItem(
                    rank=rank,
                    title=title,
                    url=url,
                    hot_score=score,
                    category=category,
                    source=BAIDU_REALTIME_SOURCE,
                    description=description,
                    raw_payload=safe_raw,
                )
            )
            if len(items) >= limit:
                break
        if not items:
            raise ConnectorFetchError(
                "empty_hotlist_payload",
                "百度热榜未返回可用榜单条目",
                retryable=False,
            )
        return tuple(items)

    @staticmethod
    def _extract_entries(document: dict[str, Any]) -> list[Any]:
        data = document.get("data")
        if not isinstance(data, dict):
            return []
        cards = data.get("cards")
        if not isinstance(cards, list) or not cards or not isinstance(cards[0], dict):
            return []
        content = cards[0].get("content")
        if not isinstance(content, list):
            return []
        if (
            content
            and isinstance(content[0], dict)
            and "word" not in content[0]
            and isinstance(content[0].get("content"), list)
        ):
            nested = content[0].get("content")
            assert isinstance(nested, list)
            return nested
        return content

    @staticmethod
    def _score(value: Any) -> int | float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            normalized = value.replace(",", "").strip()
            if not normalized:
                return None
            try:
                return int(normalized)
            except ValueError:
                try:
                    return float(normalized)
                except ValueError:
                    return None
        return None

    @staticmethod
    def _url(entry: dict[str, Any], title: str) -> str:
        for key in ("rawUrl", "url", "indexUrl", "appUrl"):
            candidate = entry.get(key)
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            parts = urlsplit(candidate)
            if parts.scheme in {"http", "https"} and parts.hostname:
                return candidate
        return f"https://www.baidu.com/s?wd={quote(title)}"


class BaiduRealtimeHotlistConnector(BaseConnector):
    connector_type = "hotlist"

    def __init__(
        self,
        fetcher: SafeHTTPFetcher,
        parser: BaiduRealtimeParser | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.parser = parser or BaiduRealtimeParser()

    async def health_check(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "source": BAIDU_REALTIME_SOURCE,
            "status": "configured",
            "requires_login": False,
        }

    async def collect(self, request: CollectRequest) -> CollectionResult:
        if request.mode != "hotlist":
            raise ValueError("百度热榜连接器仅支持 hotlist 模式")
        configured_sources = request.parameters.get("sources", [BAIDU_REALTIME_SOURCE])
        if (
            not isinstance(configured_sources, list)
            or configured_sources != [BAIDU_REALTIME_SOURCE]
        ):
            raise ValueError("M1-D 热榜仅允许固定 baidu_realtime 来源")
        effective_limit = min(max(request.limit, 1), MAX_HOTLIST_ITEMS)
        response = await self.fetcher.fetch(
            BAIDU_REALTIME_API,
            allowed_content_types=JSON_CONTENT_TYPES,
            headers={
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "User-Agent": BAIDU_HOTLIST_USER_AGENT,
            },
        )
        items = self.parser.parse(response.body, limit=effective_limit)
        collected_at = datetime.now(UTC)
        signals = tuple(self._to_signal(item) for item in items)
        return CollectionResult(
            signals=signals,
            checkpoint={
                "source": BAIDU_REALTIME_SOURCE,
                "fetched_at": collected_at.isoformat(),
                "top_external_ids": [signal.external_id for signal in signals[:10]],
            },
            metadata={
                "fetch_status": "success",
                "source": BAIDU_REALTIME_SOURCE,
                "item_count": len(signals),
            },
        )

    @staticmethod
    def _to_signal(item: HotlistItem) -> RawSignal:
        digest = hashlib.sha256(item.title.strip().casefold().encode("utf-8")).hexdigest()
        metrics: dict[str, int | float] = {"rank": item.rank}
        if item.hot_score is not None:
            metrics["hot_score"] = item.hot_score
        return RawSignal(
            platform="baidu_hot_search",
            external_id=f"baidu-realtime:{digest}",
            url=item.url,
            canonical_url=item.url,
            title=item.title,
            text=item.description,
            published_at=item.published_at,
            metrics=metrics,
            raw_payload={
                **item.raw_payload,
                "source": item.source,
            },
            language="zh-CN",
        )
