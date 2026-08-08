from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from packages.database.models import RawSignalRecord

FINGERPRINT_INPUT_SCHEMA_VERSION = "fingerprint-text-v1"
SIMHASH_ALGORITHM_VERSION = "simhash64-v1"
SIGNAL_FINGERPRINT_VERSION = "signal-fingerprint-v1"
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class FingerprintInput:
    signal_id: UUID
    input_schema_version: str
    fingerprint_version: str
    text: str
    input_hash: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SignalFingerprint:
    signal_id: UUID
    fingerprint_version: str
    input_hash: str
    simhash: str
    token_count: int


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _tokenize(text: str) -> tuple[str, ...]:
    latin_words = _WORD_RE.findall(text)
    tokens: list[str] = [f"w:{word}" for word in latin_words]
    tokens.extend(
        f"wb:{left}_{right}" for left, right in zip(latin_words, latin_words[1:])
    )

    cjk_runs: list[str] = []
    current: list[str] = []
    for character in text:
        if _is_cjk(character):
            current.append(character)
        elif current:
            cjk_runs.append("".join(current))
            current = []
    if current:
        cjk_runs.append("".join(current))

    for run in cjk_runs:
        if len(run) == 1:
            tokens.append(f"c:{run}")
            continue
        tokens.extend(f"c2:{run[index:index + 2]}" for index in range(len(run) - 1))
        if len(run) >= 3:
            tokens.extend(
                f"c3:{run[index:index + 3]}" for index in range(len(run) - 2)
            )
    return tuple(tokens)


def simhash64(tokens: tuple[str, ...]) -> str:
    if not tokens:
        raise ValueError("SimHash requires at least one token")
    weights = [0] * 64
    for token, frequency in Counter(tokens).items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], byteorder="big", signed=False)
        for bit in range(64):
            if value & (1 << bit):
                weights[bit] += frequency
            else:
                weights[bit] -= frequency
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return f"{result:016x}"


def hamming_distance(left: str, right: str) -> int:
    if len(left) != 16 or len(right) != 16:
        raise ValueError("SimHash must be a 16-character hexadecimal value")
    try:
        left_value = int(left, 16)
        right_value = int(right, 16)
    except ValueError as exc:
        raise ValueError("SimHash must be hexadecimal") from exc
    return (left_value ^ right_value).bit_count()


class FingerprintInputBuilder:
    input_schema_version = FINGERPRINT_INPUT_SCHEMA_VERSION
    fingerprint_version = SIGNAL_FINGERPRINT_VERSION
    simhash_algorithm_version = SIMHASH_ALGORITHM_VERSION

    def build(self, signal: RawSignalRecord) -> FingerprintInput | None:
        title = _normalize(signal.title)
        body = _normalize(signal.text)
        if not title and not body:
            return None

        parts: list[str] = []
        if title:
            parts.append(f"title: {title}")
        if body:
            parts.append(f"text: {body}")
        normalized_text = "\n".join(parts)
        tokens = _tokenize(normalized_text)
        if not tokens:
            return None
        return FingerprintInput(
            signal_id=signal.id,
            input_schema_version=self.input_schema_version,
            fingerprint_version=self.fingerprint_version,
            text=normalized_text,
            input_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
            tokens=tokens,
        )

    def fingerprint(self, signal: RawSignalRecord) -> SignalFingerprint | None:
        fingerprint_input = self.build(signal)
        if fingerprint_input is None:
            return None
        return SignalFingerprint(
            signal_id=signal.id,
            fingerprint_version=fingerprint_input.fingerprint_version,
            input_hash=fingerprint_input.input_hash,
            simhash=simhash64(fingerprint_input.tokens),
            token_count=len(fingerprint_input.tokens),
        )
