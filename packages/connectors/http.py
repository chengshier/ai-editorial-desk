from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from packages.signals.urls import (
    Resolver,
    UnsafeURLError,
    normalize_http_url,
    resolve_redirect_url,
    validate_public_host,
)

SAFE_REQUEST_HEADER_NAMES = frozenset(
    {"accept", "accept-language", "if-modified-since", "if-none-match", "user-agent"}
)
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class ConnectorFetchError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.status_code = status_code


@dataclass(slots=True, frozen=True)
class SafeHTTPResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes


async def resolve_public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise UnsafeURLError("目标域名解析失败") from exc
    return tuple(sorted({str(result[4][0]) for result in results}))


ClientFactory = Callable[[], httpx.AsyncClient]


class SafeHTTPFetcher:
    """Bounded public HTTP fetcher with per-hop DNS and redirect validation."""

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_public_addresses,
        client_factory: ClientFactory | None = None,
        max_redirects: int = 3,
        max_response_bytes: int = 2 * 1024 * 1024,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 10.0,
    ) -> None:
        self.resolver = resolver
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.client_factory = client_factory or self._default_client

    def _default_client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.read_timeout_seconds,
            pool=self.connect_timeout_seconds,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )

    async def fetch(
        self,
        url: str,
        *,
        allowed_content_types: frozenset[str],
        headers: Mapping[str, str] | None = None,
        allow_not_modified: bool = False,
    ) -> SafeHTTPResponse:
        current_url = normalize_http_url(url)
        safe_headers = self._safe_headers(headers or {})
        async with self.client_factory() as client:
            for redirect_count in range(self.max_redirects + 1):
                await self._validate_target(current_url)
                try:
                    response = await client.send(
                        client.build_request("GET", current_url, headers=safe_headers),
                        stream=True,
                    )
                except httpx.TimeoutException as exc:
                    raise ConnectorFetchError(
                        "request_timeout",
                        "远程请求超时",
                        retryable=True,
                    ) from exc
                except httpx.RequestError as exc:
                    raise ConnectorFetchError(
                        "connection_failed",
                        "无法连接远程公开地址",
                        retryable=True,
                    ) from exc
                try:
                    if response.status_code in REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise ConnectorFetchError(
                                "invalid_redirect",
                                "远程响应包含无效重定向",
                                retryable=False,
                            )
                        if redirect_count >= self.max_redirects:
                            raise ConnectorFetchError(
                                "too_many_redirects",
                                "远程地址重定向次数过多",
                                retryable=False,
                            )
                        current_url = resolve_redirect_url(current_url, location)
                        continue
                    if response.status_code == 304 and allow_not_modified:
                        return SafeHTTPResponse(
                            status_code=304,
                            url=current_url,
                            headers=self._response_headers(response),
                            body=b"",
                        )
                    if response.status_code >= 400:
                        raise ConnectorFetchError(
                            f"http_{response.status_code}",
                            "远程地址返回错误状态",
                            retryable=response.status_code >= 500,
                            status_code=response.status_code,
                        )
                    content_type = response.headers.get("content-type", "")
                    media_type = content_type.split(";", 1)[0].strip().casefold()
                    if media_type not in allowed_content_types:
                        raise ConnectorFetchError(
                            "content_type_not_allowed",
                            "远程响应类型不受支持",
                            retryable=False,
                        )
                    body = await self._read_limited(response)
                    return SafeHTTPResponse(
                        status_code=response.status_code,
                        url=current_url,
                        headers=self._response_headers(response),
                        body=body,
                    )
                finally:
                    await response.aclose()
        raise ConnectorFetchError(
            "too_many_redirects",
            "远程地址重定向次数过多",
            retryable=False,
        )

    async def _validate_target(self, url: str) -> None:
        parts = urlsplit(url)
        hostname = parts.hostname
        if not hostname:
            raise UnsafeURLError("URL 缺少有效主机名")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = await self.resolver(hostname, port)
        validate_public_host(hostname, addresses)

    async def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ConnectorFetchError(
                    "response_too_large",
                    "远程响应超过允许大小",
                    retryable=False,
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, value in headers.items():
            normalized_name = name.casefold()
            if normalized_name not in SAFE_REQUEST_HEADER_NAMES:
                raise ValueError("请求头不在安全允许列表")
            result[name] = value
        return result

    @staticmethod
    def _response_headers(response: httpx.Response) -> dict[str, str]:
        allowed = {"content-type", "etag", "last-modified", "location"}
        return {
            name.casefold(): value
            for name, value in response.headers.items()
            if name.casefold() in allowed
        }
