import httpx
import pytest

from packages.connectors.base import CollectRequest
from packages.connectors.http import SafeHTTPFetcher
from packages.connectors.manual import ManualImportError, ManualURLConnector
from packages.signals.urls import UnsafeURLError

HTML = b"""<!doctype html><html lang="zh-CN"><head>
<title>Page title</title>
<link rel="canonical" href="/canonical"/>
<meta name="description" content="Description"/>
<meta property="og:title" content="OG title"/>
</head><body><article>Hello world</article><script>secret()</script></body></html>"""


async def _public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    del hostname, port
    return ("93.184.216.34",)


def _connector(  # type: ignore[no-untyped-def]
    handler,
    *,
    resolver=_public_resolver,
    max_bytes=2 * 1024 * 1024,
):
    transport = httpx.MockTransport(handler)
    fetcher = SafeHTTPFetcher(
        resolver=resolver,
        client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        ),
        max_response_bytes=max_bytes,
    )
    return ManualURLConnector(fetcher)


async def test_manual_connector_extracts_html_and_canonical() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=HTML,
            request=request,
        )

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="manual_import",
            query="https://example.com/original?utm_source=x",
            limit=1,
        )
    )
    signal = result.signals[0]
    assert signal.url == "https://example.com/original"
    assert signal.canonical_url == "https://example.com/canonical"
    assert signal.title == "Page title"
    assert "Hello world" in (signal.text or "")
    assert "secret()" not in (signal.text or "")
    assert signal.language == "zh-CN"
    assert signal.raw_payload["fetch_status"] == "fetched"


async def test_manual_connector_uses_user_content_without_fetch() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="manual_import",
            query="https://example.com/a",
            limit=1,
            parameters={
                "title": "用户标题",
                "text": "用户正文",
                "fetch_metadata": False,
            },
        )
    )
    assert called is False
    assert result.signals[0].title == "用户标题"
    assert result.signals[0].raw_payload["content_origin"] == "user_provided"


async def test_manual_connector_saves_user_content_after_fetch_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    result = await _connector(handler).collect(
        CollectRequest(
            source_id="source",
            mode="manual_import",
            query="https://example.com/a",
            limit=1,
            parameters={"text": "仍可保存的正文", "fetch_metadata": True},
        )
    )
    signal = result.signals[0]
    assert signal.text == "仍可保存的正文"
    assert signal.raw_payload["fetch_status"] == "failed"
    assert signal.raw_payload["fetch_error_code"] == "http_404"


async def test_manual_connector_fails_without_fallback_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    with pytest.raises(ManualImportError):
        await _connector(handler).collect(
            CollectRequest(
                source_id="source",
                mode="manual_import",
                query="https://example.com/a",
                limit=1,
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a",
        "ftp://example.com/a",
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://[::1]/a",
    ],
)
async def test_manual_connector_rejects_non_public_targets(url: str) -> None:
    called = False

    async def resolver(hostname: str, port: int) -> tuple[str, ...]:
        del port
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            return ("127.0.0.1",)
        return ("93.184.216.34",)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, request=request)

    with pytest.raises((UnsafeURLError, ManualImportError)):
        await _connector(handler, resolver=resolver).collect(
            CollectRequest(
                source_id="source",
                mode="manual_import",
                query=url,
                limit=1,
            )
        )
    assert called is False


async def test_manual_redirect_to_private_address_is_rejected() -> None:
    requested: list[str] = []

    async def resolver(hostname: str, port: int) -> tuple[str, ...]:
        del port
        return ("93.184.216.34",) if hostname == "example.com" else ("10.0.0.1",)

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://private.example/a"},
            request=request,
        )

    with pytest.raises(UnsafeURLError):
        await _connector(handler, resolver=resolver).collect(
            CollectRequest(
                source_id="source",
                mode="manual_import",
                query="https://example.com/a",
                limit=1,
            )
        )
    assert requested == ["https://example.com/a"]


async def test_manual_response_size_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=HTML,
            request=request,
        )

    with pytest.raises(ManualImportError):
        await _connector(handler, max_bytes=10).collect(
            CollectRequest(
                source_id="source",
                mode="manual_import",
                query="https://example.com/a",
                limit=1,
            )
        )
