import json

import httpx
import pytest

from packages.connectors.base import CollectRequest
from packages.connectors.hotlist import BaiduRealtimeHotlistConnector
from packages.connectors.hotlist.baidu import BaiduRealtimeParser
from packages.connectors.http import ConnectorFetchError, SafeHTTPFetcher
from packages.signals.urls import UnsafeURLError

BAIDU_FIXTURE = json.dumps(
    {
        "success": True,
        "data": {
            "cards": [
                {
                    "content": [
                        {
                            "content": [
                                {
                                    "word": "置顶热点",
                                    "desc": "置顶摘要",
                                    "hotScore": "7904669",
                                    "isTop": True,
                                    "url": "https://www.baidu.com/s?wd=top",
                                    "hotTag": "2",
                                },
                                {
                                    "word": "普通热点一",
                                    "desc": "第一条摘要",
                                    "hotScore": 7808670,
                                    "isTop": False,
                                    "url": "https://www.baidu.com/s?wd=one",
                                    "hotChange": "up",
                                },
                                {
                                    "word": "普通热点二",
                                    "desc": "第二条摘要",
                                    "hotScore": "7712623",
                                    "isTop": False,
                                    "appUrl": "baiduboxapp://unsafe",
                                },
                            ]
                        }
                    ]
                }
            ]
        },
    },
    ensure_ascii=False,
).encode()


async def _public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    del hostname, port
    return ("180.101.50.188",)


def _connector(handler, *, max_bytes: int = 2 * 1024 * 1024):  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    fetcher = SafeHTTPFetcher(
        resolver=_public_resolver,
        client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        ),
        max_response_bytes=max_bytes,
    )
    return BaiduRealtimeHotlistConnector(fetcher)


def test_baidu_hotlist_parser_reads_rank_title_url_and_score() -> None:
    items = BaiduRealtimeParser().parse(BAIDU_FIXTURE, limit=10)
    assert len(items) == 3
    assert items[0].rank == 0
    assert items[0].title == "置顶热点"
    assert items[0].hot_score == 7904669
    assert items[1].rank == 1
    assert items[1].url == "https://www.baidu.com/s?wd=one"
    assert items[2].rank == 2
    assert items[2].url.startswith("https://www.baidu.com/s?wd=")


async def test_hotlist_connector_uses_public_json_without_auth_headers() -> None:
    seen_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update({key.casefold(): value for key, value in request.headers.items()})
        assert str(request.url).startswith("https://top.baidu.com/api/board")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            content=BAIDU_FIXTURE,
            request=request,
        )

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="hotlist",
            limit=2,
            parameters={"sources": ["baidu_realtime"]},
        )
    )
    assert len(result.signals) == 2
    assert result.signals[0].platform == "baidu_hot_search"
    assert result.signals[0].metrics["rank"] == 0
    assert result.signals[1].metrics["hot_score"] == 7808670
    assert result.signals[0].raw_payload["source"] == "baidu_realtime"
    assert result.checkpoint is not None
    assert result.checkpoint["source"] == "baidu_realtime"
    assert "authorization" not in seen_headers
    assert "cookie" not in seen_headers


async def test_hotlist_repeated_parse_generates_stable_external_ids() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=BAIDU_FIXTURE,
            request=request,
        )

    connector = _connector(handler)
    request = CollectRequest(
        source_id="source",
        mode="hotlist",
        limit=3,
        parameters={"sources": ["baidu_realtime"]},
    )
    first = await connector.collect(request)
    second = await connector.collect(request)
    assert [item.external_id for item in first.signals] == [
        item.external_id for item in second.signals
    ]


@pytest.mark.parametrize("content_type", ["text/html", "text/plain"])
async def test_hotlist_rejects_unexpected_content_type(content_type: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": content_type},
            content=BAIDU_FIXTURE,
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as caught:
        await _connector(handler).collect(
            CollectRequest(source_id="source", mode="hotlist", limit=5)
        )
    assert caught.value.code == "content_type_not_allowed"


async def test_hotlist_rejects_timeout_oversize_and_bad_payload() -> None:
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(ConnectorFetchError) as timed_out:
        await _connector(timeout).collect(
            CollectRequest(source_id="source", mode="hotlist", limit=5)
        )
    assert timed_out.value.code == "request_timeout"

    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=BAIDU_FIXTURE,
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as too_large:
        await _connector(oversized, max_bytes=10).collect(
            CollectRequest(source_id="source", mode="hotlist", limit=5)
        )
    assert too_large.value.code == "response_too_large"

    async def bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"not-json",
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as invalid:
        await _connector(bad_json).collect(
            CollectRequest(source_id="source", mode="hotlist", limit=5)
        )
    assert invalid.value.code == "invalid_hotlist_json"


async def test_hotlist_reuses_ssrf_guard() -> None:
    async def private_resolver(hostname: str, port: int) -> tuple[str, ...]:
        del hostname, port
        return ("127.0.0.1",)

    fetcher = SafeHTTPFetcher(
        resolver=private_resolver,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=BAIDU_FIXTURE, request=request)
            )
        ),
    )
    connector = BaiduRealtimeHotlistConnector(fetcher)
    with pytest.raises(UnsafeURLError):
        await connector.collect(
            CollectRequest(source_id="source", mode="hotlist", limit=5)
        )


async def test_hotlist_rejects_unapproved_source_and_mode() -> None:
    connector = BaiduRealtimeHotlistConnector(SafeHTTPFetcher())
    with pytest.raises(ValueError):
        await connector.collect(
            CollectRequest(
                source_id="source",
                mode="hotlist",
                limit=5,
                parameters={"sources": ["other"]},
            )
        )
    with pytest.raises(ValueError):
        await connector.collect(
            CollectRequest(source_id="source", mode="feed", limit=5)
        )
