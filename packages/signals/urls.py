from __future__ import annotations

import ipaddress
import posixpath
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
CLOUD_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


class UnsafeURLError(ValueError):
    """A public URL failed scheme, host, or network-address validation."""


def normalize_http_url(url: str) -> str:
    """Return a stable HTTP(S) URL without fragments or known tracking parameters."""

    stripped = url.strip()
    parts = urlsplit(stripped)
    scheme = parts.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError("只允许 HTTP 或 HTTPS URL")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("URL 不允许包含用户名或密码")
    hostname = parts.hostname
    if not hostname:
        raise UnsafeURLError("URL 缺少有效主机名")
    normalized_host = hostname.rstrip(".").casefold()
    if not normalized_host:
        raise UnsafeURLError("URL 缺少有效主机名")
    try:
        normalized_host = normalized_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeURLError("URL 主机名无效") from exc

    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("URL 端口无效") from exc
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    host_for_netloc = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    netloc = host_for_netloc if port is None else f"{host_for_netloc}:{port}"

    decoded_path = unquote(parts.path or "/")
    normalized_path = posixpath.normpath(decoded_path)
    if decoded_path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    if normalized_path == "/.":
        normalized_path = "/"
    encoded_path = quote(normalized_path, safe="/:@!$&'()*+,;=-._~")

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS
    ]
    normalized_query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, encoded_path, normalized_query, ""))


def resolve_redirect_url(current_url: str, location: str) -> str:
    return normalize_http_url(urljoin(current_url, location))


def validate_public_ip(address: str) -> None:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UnsafeURLError("目标地址解析失败") from exc
    if parsed in CLOUD_METADATA_ADDRESSES:
        raise UnsafeURLError("不允许访问云元数据地址")
    if (
        parsed.is_loopback
        or parsed.is_private
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    ):
        raise UnsafeURLError("目标地址不是公开网络地址")


def validate_public_host(hostname: str, addresses: Iterable[str]) -> None:
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise UnsafeURLError("不允许访问本机地址")
    resolved = tuple(addresses)
    if not resolved:
        raise UnsafeURLError("目标域名没有可用地址")
    for address in resolved:
        validate_public_ip(address)


Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]
