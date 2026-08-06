from datetime import UTC, datetime

import httpx
import pytest

from packages.connectors.base import CollectRequest
from packages.connectors.http import ConnectorFetchError, SafeHTTPFetcher
from packages.connectors.rss import RSSConnector, RSSParseError, parse_feed

RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>First</title><link>https://example.com/a</link>
<guid>entry-1</guid><description><![CDATA[<p>Hello</p>]]></description>
<author>Alice</author><pubDate>Thu, 06 Aug 2026 08:00:00 GMT</pubDate></item>
<item><title>No guid</title><link>https://example.com/b</link></item>
</channel></rss>"""

ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Atom</title>
<entry><id>atom-1</id><title>Atom title</title>
<link rel="alternate" href="https://example.com/atom"/>
<summary>Atom text</summary><updated>2026-08-06T08:00:00Z</updated>
<author><name>Bob</name></author></entry>
</feed>"""


async def _resolver(hostname: str, port: int) -> tuple[str, ...]:
    del hostname, port
    return ("93.184.216.34",)


def _connector(handler, *, max_bytes: int = 2 * 1024 * 1024):  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    fetcher = SafeHTTPFetcher(
        resolver=_resolver,
        client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        ),
        max_response_bytes=max_bytes,
    )
    return RSSConnector(fetcher)


def test_parse_rss2_atom_missing_guid_and_missing_time() -> None:
    rss_signals, rss_errors = parse_feed(
        RSS_XML,
        feed_url="https://example.com/feed.xml",
        limit=10,
    )
    atom_signals, atom_errors = parse_feed(
        ATOM_XML,
        feed_url="https://example.com/atom.xml",
        limit=10,
    )
    assert not rss_errors
    assert not atom_errors
    assert rss_signals[0].external_id == "entry-1"
    assert rss_signals[0].text == "Hello"
    assert rss_signals[0].published_at == datetime(2026, 8, 6, 8, tzinfo=UTC)
    assert rss_signals[1].external_id is None
    assert rss_signals[1].published_at is None
    assert atom_signals[0].external_id == "atom-1"
    assert atom_signals[0].author_name == "Bob"


def test_parse_feed_rejects_invalid_xml() -> None:
    with pytest.raises(RSSParseError):
        parse_feed(b"<rss>", feed_url="https://example.com/feed.xml", limit=10)


async def test_rss_connector_uses_conditional_headers_and_checkpoint() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/rss+xml",
                "ETag": '"new"',
                "Last-Modified": "Thu, 06 Aug 2026 08:00:00 GMT",
            },
            content=RSS_XML,
            request=request,
        )

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="feed",
            query="https://example.com/feed.xml",
            limit=10,
            checkpoint={
                "etag": '"old"',
                "last_modified": "Wed, 05 Aug 2026 08:00:00 GMT",
            },
        )
    )
    assert seen["if-none-match"] == '"old"'
    assert "if-modified-since" in seen
    assert len(result.signals) == 2
    assert result.checkpoint is not None
    assert result.checkpoint["etag"] == '"new"'
    assert result.checkpoint["last_modified"].startswith("Thu")


async def test_rss_connector_handles_304_without_checkpoint_advance() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, request=request)

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="feed",
            query="https://example.com/feed.xml",
            limit=10,
            checkpoint={"etag": '"same"'},
        )
    )
    assert result.not_modified is True
    assert result.signals == ()
    assert result.checkpoint is None


@pytest.mark.parametrize("content_type", ["text/html", "application/json"])
async def test_rss_connector_rejects_content_type(content_type: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": content_type},
            content=RSS_XML,
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as caught:
        await _connector(handler).collect(
            CollectRequest(
                source_id="source",
                mode="feed",
                query="https://example.com/feed.xml",
                limit=10,
            )
        )
    assert caught.value.code == "content_type_not_allowed"


async def test_rss_connector_rejects_oversized_and_timeout() -> None:
    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/rss+xml"},
            content=RSS_XML,
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as too_large:
        await _connector(oversized, max_bytes=10).collect(
            CollectRequest(
                source_id="source",
                mode="feed",
                query="https://example.com/feed.xml",
                limit=10,
            )
        )
    assert too_large.value.code == "response_too_large"

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(ConnectorFetchError) as timed_out:
        await _connector(timeout).collect(
            CollectRequest(
                source_id="source",
                mode="feed",
                query="https://example.com/feed.xml",
                limit=10,
            )
        )
    assert timed_out.value.code == "request_timeout"
