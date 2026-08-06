from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.connectors.base import RawSignal


@dataclass(slots=True, frozen=True)
class NormalizedSignal:
    source_id: UUID
    connector_instance_id: UUID
    connector_run_id: UUID | None
    connector_type: str
    platform: str
    external_id: str | None
    original_url: str
    canonical_url: str
    title: str | None
    text: str | None
    author_id: str | None
    author_name: str | None
    published_at: datetime | None
    metrics: dict[str, int | float] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    language: str | None = None

    @classmethod
    def from_connector_signal(
        cls,
        *,
        source_id: UUID,
        connector_instance_id: UUID,
        connector_run_id: UUID | None,
        connector_type: str,
        signal: RawSignal,
        canonical_url: str,
    ) -> "NormalizedSignal":
        published_at = signal.published_at
        if published_at is not None:
            if published_at.tzinfo is None or published_at.utcoffset() is None:
                raise ValueError("published_at 必须包含时区")
            published_at = published_at.astimezone(UTC)
        return cls(
            source_id=source_id,
            connector_instance_id=connector_instance_id,
            connector_run_id=connector_run_id,
            connector_type=connector_type,
            platform=signal.platform,
            external_id=signal.external_id or None,
            original_url=signal.url,
            canonical_url=canonical_url,
            title=signal.title,
            text=signal.text,
            author_id=signal.author_id,
            author_name=signal.author_name,
            published_at=published_at,
            metrics=dict(signal.metrics),
            media=list(signal.media),
            raw_payload=dict(signal.raw_payload),
            language=signal.language,
        )


@dataclass(slots=True, frozen=True)
class IngestionResult:
    signal_id: UUID
    created: bool
    duplicate: bool
