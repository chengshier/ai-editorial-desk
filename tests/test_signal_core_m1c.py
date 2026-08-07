from datetime import UTC, datetime
from uuid import uuid4

import pytest

from packages.connectors.base import RawSignal
from packages.signals.idempotency import build_content_hash, build_idempotency_key
from packages.signals.urls import UnsafeURLError, normalize_http_url, validate_public_ip


def test_url_normalization_is_stable_and_conservative() -> None:
    assert normalize_http_url(
        "HTTPS://Example.COM:443/a/../news/?utm_source=x&id=42#section"
    ) == "https://example.com/news/?id=42"
    assert normalize_http_url("http://example.com:80") == "http://example.com/"


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/a", "ftp://example.com/a", "https://user:pass@example.com/a"],
)
def test_url_normalization_rejects_unsafe_forms(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        normalize_http_url(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1", "224.0.0.1"],
)
def test_public_ip_validation_rejects_non_public_ranges(address: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_ip(address)


def test_content_hash_and_idempotency_rules_are_stable() -> None:
    source_a = uuid4()
    source_b = uuid4()
    content_hash = build_content_hash(title="  标题 ", text="正文\n内容")
    assert content_hash == build_content_hash(title="标题", text="正文 内容")

    external_a = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_a,
        external_id="entry-1",
        canonical_url="https://example.com/a",
        content_hash=content_hash,
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    external_b = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_b,
        external_id="entry-1",
        canonical_url="https://different.example/a",
        content_hash=content_hash,
        published_at=None,
    )
    assert external_a == external_b

    url_a = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_a,
        external_id=None,
        canonical_url="https://example.com/a",
        content_hash=content_hash,
        published_at=None,
    )
    url_b = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_b,
        external_id=None,
        canonical_url="https://example.com/a",
        content_hash=content_hash,
        published_at=None,
    )
    assert url_a == url_b

    fallback_a = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_a,
        external_id=None,
        canonical_url=None,
        content_hash=content_hash,
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    fallback_b = build_idempotency_key(
        connector_type="rss",
        platform="rss",
        source_id=source_b,
        external_id=None,
        canonical_url=None,
        content_hash=content_hash,
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert fallback_a != fallback_b


def test_raw_signal_requires_aware_time_and_numeric_metrics() -> None:
    with pytest.raises(ValueError):
        RawSignal(
            platform="rss",
            external_id=None,
            url="https://example.com/a",
            published_at=datetime(2026, 8, 6),
        )
    with pytest.raises(TypeError):
        RawSignal(
            platform="rss",
            external_id=None,
            url="https://example.com/a",
            metrics={"views": True},
        )
