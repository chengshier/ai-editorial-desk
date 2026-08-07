import httpx
import pytest

from packages.connectors.http import ConnectorFetchError, SafeHTTPFetcher
from packages.signals.urls import UnsafeURLError


async def _public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    del hostname, port
    return ("93.184.216.34",)


def _factory(handler):  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport, follow_redirects=False)


async def test_safe_fetcher_reads_allowed_public_response() -> None:
    seen_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            content=b"ok",
            request=request,
        )

    response = await SafeHTTPFetcher(
        resolver=_public_resolver,
        client_factory=_factory(handler),
    ).fetch(
        "https://example.com/a",
        allowed_content_types=frozenset({"text/plain"}),
        headers={"Accept": "text/plain"},
    )
    assert response.body == b"ok"
    assert "authorization" not in seen_headers
    assert "cookie" not in seen_headers


async def test_safe_fetcher_revalidates_redirect_target() -> None:
    requested: list[str] = []

    async def resolver(hostname: str, port: int) -> tuple[str, ...]:
        del port
        return ("93.184.216.34",) if hostname == "example.com" else ("127.0.0.1",)

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://internal.example/secret"},
            request=request,
        )

    with pytest.raises(UnsafeURLError):
        await SafeHTTPFetcher(
            resolver=resolver,
            client_factory=_factory(handler),
        ).fetch(
            "https://example.com/start",
            allowed_content_types=frozenset({"text/plain"}),
        )
    assert requested == ["https://example.com/start"]


async def test_safe_fetcher_rejects_localhost_before_network() -> None:
    called = False

    async def resolver(hostname: str, port: int) -> tuple[str, ...]:
        del hostname, port
        return ("127.0.0.1",)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, request=request)

    with pytest.raises(UnsafeURLError):
        await SafeHTTPFetcher(
            resolver=resolver,
            client_factory=_factory(handler),
        ).fetch(
            "http://localhost/a",
            allowed_content_types=frozenset({"text/plain"}),
        )
    assert called is False


async def test_safe_fetcher_limits_response_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            content=b"12345",
            request=request,
        )

    with pytest.raises(ConnectorFetchError) as caught:
        await SafeHTTPFetcher(
            resolver=_public_resolver,
            client_factory=_factory(handler),
            max_response_bytes=4,
        ).fetch(
            "https://example.com/a",
            allowed_content_types=frozenset({"text/plain"}),
        )
    assert caught.value.code == "response_too_large"


async def test_safe_fetcher_converts_timeout_to_safe_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=request)

    with pytest.raises(ConnectorFetchError) as caught:
        await SafeHTTPFetcher(
            resolver=_public_resolver,
            client_factory=_factory(handler),
        ).fetch(
            "https://example.com/a",
            allowed_content_types=frozenset({"text/plain"}),
        )
    assert caught.value.code == "request_timeout"
    assert caught.value.retryable is True
    assert "private" not in caught.value.safe_message
