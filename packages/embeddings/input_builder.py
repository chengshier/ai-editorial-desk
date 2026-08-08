from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from packages.database.models import RawSignalRecord

SIGNAL_TEXT_INPUT_SCHEMA_VERSION = "signal-text-v1"


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    signal_id: UUID
    input_schema_version: str
    text: str
    input_hash: str


class EmbeddingInputBuilder:
    """Build deterministic semantic text from RawSignal title/text only."""

    input_schema_version = SIGNAL_TEXT_INPUT_SCHEMA_VERSION

    @staticmethod
    def _normalize(value: str | None) -> str:
        if value is None:
            return ""
        return " ".join(value.split())

    def build(self, signal: RawSignalRecord) -> EmbeddingInput | None:
        title = self._normalize(signal.title)
        text = self._normalize(signal.text)
        if not title and not text:
            return None

        parts: list[str] = []
        if title:
            parts.append(f"title: {title}")
        if text:
            parts.append(f"text: {text}")
        provider_text = "\n".join(parts)
        return EmbeddingInput(
            signal_id=signal.id,
            input_schema_version=self.input_schema_version,
            text=provider_text,
            input_hash=sha256(provider_text.encode("utf-8")).hexdigest(),
        )
