from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from packages.connectors.base import (
    BaseConnector,
    CollectionItemError,
    CollectionResult,
    CollectRequest,
    RawSignal,
)
from packages.connectors.http import SafeHTTPFetcher

RSS_CONTENT_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/rss+xml",
        "application/xml",
        "text/xml",
    }
)
RSS_PARSER_VERSION = "rss-atom-v1"


class RSSParseError(ValueError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = " ".join(parser.parts).strip()
    return text or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    expected = name.casefold()
    return [child for child in element if _local_name(child.tag) == expected]


def _first_child(
    element: ElementTree.Element,
    *names: str,
) -> ElementTree.Element | None:
    expected = {name.casefold() for name in names}
    return next(
        (child for child in element if _local_name(child.tag) in expected),
        None,
    )


def _text(element: ElementTree.Element, *names: str) -> str | None:
    child = _first_child(element, *names)
    if child is None:
        return None
    value = "".join(child.itertext()).strip()
    return value or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    stripped = value.strip()
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _atom_link(entry: ElementTree.Element) -> str | None:
    links = _children(entry, "link")
    for link in links:
        relation = (link.attrib.get("rel") or "alternate").casefold()
        href = link.attrib.get("href")
        if relation == "alternate" and href:
            return href.strip()
    for link in links:
        href = link.attrib.get("href")
        if href:
            return href.strip()
    return None


def _rss_signal(item: ElementTree.Element, feed_url: str) -> RawSignal:
    url = _text(item, "link")
    if not url:
        raise RSSParseError("RSS 条目缺少链接")
    guid = _text(item, "guid")
    author = _text(item, "author", "creator")
    description = _text(item, "encoded", "description")
    return RawSignal(
        platform="rss",
        external_id=guid,
        url=url,
        canonical_url=url,
        title=_plain_text(_text(item, "title")),
        text=_plain_text(description),
        author_name=author,
        published_at=_parse_datetime(_text(item, "pubdate", "date")),
        raw_payload={
            "feed_url": feed_url,
            "guid": guid,
            "entry_type": "rss2",
        },
    )


def _atom_signal(entry: ElementTree.Element, feed_url: str) -> RawSignal:
    url = _atom_link(entry)
    if not url:
        raise RSSParseError("Atom 条目缺少链接")
    entry_id = _text(entry, "id")
    author_element = _first_child(entry, "author")
    author_name = _text(author_element, "name") if author_element is not None else None
    content = _text(entry, "content", "summary")
    return RawSignal(
        platform="rss",
        external_id=entry_id,
        url=url,
        canonical_url=url,
        title=_plain_text(_text(entry, "title")),
        text=_plain_text(content),
        author_name=author_name,
        published_at=_parse_datetime(_text(entry, "published", "updated")),
        raw_payload={
            "feed_url": feed_url,
            "entry_id": entry_id,
            "entry_type": "atom",
        },
    )


def parse_feed(
    payload: bytes,
    *,
    feed_url: str,
    limit: int,
) -> tuple[tuple[RawSignal, ...], tuple[CollectionItemError, ...]]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise RSSParseError("Feed XML 无法解析") from exc

    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = _first_child(root, "channel")
        if channel is None:
            raise RSSParseError("RSS 缺少 channel")
        entries = _children(channel, "item")
        parser = _rss_signal
    elif root_name == "feed":
        entries = _children(root, "entry")
        parser = _atom_signal
    else:
        raise RSSParseError("不支持的 Feed 格式")

    signals: list[RawSignal] = []
    errors: list[CollectionItemError] = []
    for index, entry in enumerate(entries[:limit]):
        try:
            signals.append(parser(entry, feed_url))
        except (RSSParseError, TypeError, ValueError) as exc:
            errors.append(
                CollectionItemError(
                    code="entry_parse_failed",
                    message=str(exc),
                    external_ref=str(index),
                )
            )
    return tuple(signals), tuple(errors)


class RSSConnector(BaseConnector):
    connector_type = "rss"

    def __init__(self, fetcher: SafeHTTPFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeHTTPFetcher()

    async def health_check(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "implemented": True,
            "validated": False,
            "parser_version": RSS_PARSER_VERSION,
        }

    async def collect(self, request: CollectRequest) -> CollectionResult:
        feed_url = request.query or str(request.parameters.get("feed_url") or "")
        if not feed_url:
            raise RSSParseError("RSS 任务缺少 feed_url")
        if request.limit < 1:
            raise ValueError("RSS limit 必须大于等于 1")

        checkpoint = request.checkpoint or {}
        headers = {
            "Accept": ", ".join(sorted(RSS_CONTENT_TYPES)),
            "User-Agent": "AI-Editorial-Desk/0.4 RSS",
        }
        etag = checkpoint.get("etag")
        last_modified = checkpoint.get("last_modified")
        if isinstance(etag, str) and etag:
            headers["If-None-Match"] = etag
        if isinstance(last_modified, str) and last_modified:
            headers["If-Modified-Since"] = last_modified

        response = await self.fetcher.fetch(
            feed_url,
            allowed_content_types=RSS_CONTENT_TYPES,
            headers=headers,
            allow_not_modified=True,
        )
        if response.status_code == 304:
            return CollectionResult(
                signals=(),
                checkpoint=None,
                not_modified=True,
                metadata={"fetch_status": "not_modified"},
            )

        signals, errors = parse_feed(
            response.body,
            feed_url=response.url,
            limit=request.limit,
        )
        latest_signal = max(
            signals,
            key=lambda signal: signal.published_at or datetime.min.replace(tzinfo=UTC),
            default=None,
        )
        latest_entry_id = next(
            (
                signal.external_id
                for signal in reversed(signals)
                if signal.external_id is not None
            ),
            checkpoint.get("latest_entry_id"),
        )
        checkpoint_after = {
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "latest_entry_id": latest_entry_id,
            "latest_published_at": (
                latest_signal.published_at.isoformat()
                if latest_signal is not None and latest_signal.published_at is not None
                else checkpoint.get("latest_published_at")
            ),
            "feed_url": response.url,
            "parser_version": RSS_PARSER_VERSION,
        }
        return CollectionResult(
            signals=signals,
            checkpoint=checkpoint_after,
            errors=errors,
            metadata={
                "fetch_status": "fetched",
                "parser_version": RSS_PARSER_VERSION,
            },
        )


__all__ = [
    "RSSConnector",
    "RSSParseError",
    "RSS_PARSER_VERSION",
    "parse_feed",
]
