from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

IDEMPOTENCY_VERSION = "v1"


def _stable_text(value: str | None) -> str:
    return " ".join((value or "").split())


def build_content_hash(*, title: str | None, text: str | None) -> str:
    payload = {
        "text": _stable_text(text),
        "title": _stable_text(title),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_idempotency_key(
    *,
    connector_type: str,
    platform: str,
    source_id: UUID,
    external_id: str | None,
    canonical_url: str | None,
    content_hash: str,
    published_at: datetime | None,
) -> str:
    if external_id and external_id.strip():
        identity = f"external:{external_id.strip()}"
    elif canonical_url and canonical_url.strip():
        identity = f"url:{canonical_url.strip()}"
    else:
        timestamp = (
            published_at.astimezone(UTC).isoformat()
            if published_at is not None
            else "unknown-published-at"
        )
        identity = f"content:{source_id}:{content_hash}:{timestamp}"
    raw = f"{IDEMPOTENCY_VERSION}|{connector_type}|{platform}|{identity}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{IDEMPOTENCY_VERSION}:{digest}"
