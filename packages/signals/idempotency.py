from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from packages.connectors.base import CollectedComment

IDEMPOTENCY_VERSION = "v1"
COMMENT_IDEMPOTENCY_VERSION = "comment-v1"


def _stable_text(value: str | None) -> str:
    return " ".join((value or "").split())


def build_content_hash(*, title: str | None, text: str | None) -> str:
    payload = {"text": _stable_text(text), "title": _stable_text(title)}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_idempotency_key(
    *, connector_type: str, platform: str, source_id: UUID,
    external_id: str | None, canonical_url: str | None,
    content_hash: str, published_at: datetime | None,
) -> str:
    if external_id and external_id.strip():
        identity = f"external:{external_id.strip()}"
    elif canonical_url and canonical_url.strip():
        identity = f"url:{canonical_url.strip()}"
    else:
        timestamp = published_at.astimezone(UTC).isoformat() if published_at is not None else "unknown-published-at"
        identity = f"content:{source_id}:{content_hash}:{timestamp}"
    raw = f"{IDEMPOTENCY_VERSION}|{connector_type}|{platform}|{identity}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{IDEMPOTENCY_VERSION}:{digest}"


def build_comment_idempotency_key(comment: CollectedComment) -> str:
    """Centralized stable comment identity with a deterministic no-ID fallback."""

    if comment.external_comment_id:
        identity = f"external:{comment.external_comment_id.strip()}"
    else:
        published = (
            comment.published_at.astimezone(UTC).isoformat()
            if comment.published_at is not None
            else "unknown-published-at"
        )
        text_hash = hashlib.sha256(_stable_text(comment.text).encode("utf-8")).hexdigest()
        identity = f"fallback:{comment.author_id or 'unknown-author'}:{text_hash}:{published}"
    raw = (
        f"{COMMENT_IDEMPOTENCY_VERSION}|{comment.platform}|"
        f"{comment.content_external_id}|{identity}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
