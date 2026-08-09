from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import EventRecord, EventSignalRecord, RawSignalRecord
from packages.database.session import get_async_sessionmaker
from packages.evidence.domain import (
    DEFAULT_MAX_CHARS_PER_SIGNAL,
    DEFAULT_MAX_SIGNALS,
    DEFAULT_MAX_TOTAL_CHARS,
    MAX_CHARS_PER_SIGNAL_LIMIT,
    MAX_SIGNALS_LIMIT,
    MAX_TOTAL_CHARS_LIMIT,
    EvidenceInputSnapshot,
    EvidenceSignalSnapshot,
    build_input_hash,
)
from packages.evidence.errors import EventMergedError, EvidenceValidationError


class EvidenceInputBuilder:
    """Build a deterministic bounded snapshot from Event membership and safe RawSignal fields."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def build(
        self,
        *,
        event_id: UUID,
        signal_ids: Sequence[UUID] | None = None,
        max_signals: int = DEFAULT_MAX_SIGNALS,
        max_chars_per_signal: int = DEFAULT_MAX_CHARS_PER_SIGNAL,
        max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    ) -> EvidenceInputSnapshot:
        self._validate_limits(
            max_signals=max_signals,
            max_chars_per_signal=max_chars_per_signal,
            max_total_chars=max_total_chars,
        )
        explicit_ids = tuple(signal_ids or ())
        if explicit_ids:
            if len(set(explicit_ids)) != len(explicit_ids):
                raise EvidenceValidationError("signal_ids 不能重复")
            if len(explicit_ids) > max_signals:
                raise EvidenceValidationError(
                    "显式 signal_ids 数量超过 max_signals",
                    details={"signal_count": len(explicit_ids), "max_signals": max_signals},
                )

        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            if event.merged_into_event_id is not None:
                raise EventMergedError(event.merged_into_event_id)

            effective_time = func.coalesce(
                RawSignalRecord.published_at,
                RawSignalRecord.collected_at,
            )
            statement = (
                select(RawSignalRecord)
                .join(
                    EventSignalRecord,
                    EventSignalRecord.signal_id == RawSignalRecord.id,
                )
                .where(EventSignalRecord.event_id == event_id)
                .order_by(effective_time.asc(), RawSignalRecord.id.asc())
            )
            if explicit_ids:
                statement = statement.where(RawSignalRecord.id.in_(explicit_ids))
            else:
                statement = statement.limit(max_signals)
            selected = list((await session.scalars(statement)).all())

            if explicit_ids:
                selected_ids = {item.id for item in selected}
                missing = sorted(set(explicit_ids) - selected_ids, key=str)
                if missing:
                    raise EvidenceValidationError(
                        "存在不属于目标 Event 的 Signal",
                        details={"signal_ids": [str(item) for item in missing]},
                    )

            event_title = event.title

        bounded, character_count, truncated_ids = self._bound_signals(
            selected,
            max_chars_per_signal=max_chars_per_signal,
            max_total_chars=max_total_chars,
        )
        signal_tuple = tuple(bounded)
        return EvidenceInputSnapshot(
            event_id=event_id,
            event_title=event_title,
            signals=signal_tuple,
            character_count=character_count,
            truncated_signal_ids=tuple(truncated_ids),
            input_hash=build_input_hash(event_id, signal_tuple),
        )

    @staticmethod
    def _validate_limits(
        *,
        max_signals: int,
        max_chars_per_signal: int,
        max_total_chars: int,
    ) -> None:
        if not 1 <= max_signals <= MAX_SIGNALS_LIMIT:
            raise EvidenceValidationError(
                f"max_signals 必须在 1..{MAX_SIGNALS_LIMIT} 之间"
            )
        if not 1 <= max_chars_per_signal <= MAX_CHARS_PER_SIGNAL_LIMIT:
            raise EvidenceValidationError(
                f"max_chars_per_signal 必须在 1..{MAX_CHARS_PER_SIGNAL_LIMIT} 之间"
            )
        if not 1 <= max_total_chars <= MAX_TOTAL_CHARS_LIMIT:
            raise EvidenceValidationError(
                f"max_total_chars 必须在 1..{MAX_TOTAL_CHARS_LIMIT} 之间"
            )

    @staticmethod
    def _bound_signals(
        records: Sequence[RawSignalRecord],
        *,
        max_chars_per_signal: int,
        max_total_chars: int,
    ) -> tuple[list[EvidenceSignalSnapshot], int, list[UUID]]:
        remaining_total = max_total_chars
        result: list[EvidenceSignalSnapshot] = []
        truncated_ids: list[UUID] = []
        character_count = 0

        for index, record in enumerate(records):
            if remaining_total <= 0:
                truncated_ids.extend(item.id for item in records[index:])
                break

            title, body, used, truncated = _bounded_text_fields(
                record.title,
                record.text,
                per_signal_limit=max_chars_per_signal,
                total_remaining=remaining_total,
            )
            remaining_total -= used
            character_count += used
            if truncated:
                truncated_ids.append(record.id)

            result.append(
                EvidenceSignalSnapshot(
                    signal_id=record.id,
                    title=title,
                    text=body,
                    author_name=record.author_name,
                    platform=record.platform,
                    published_at=record.published_at,
                    collected_at=record.collected_at,
                    original_url=record.original_url,
                    canonical_url=record.canonical_url,
                    truncated=truncated,
                )
            )

        return result, character_count, truncated_ids


def _bounded_text_fields(
    title: str | None,
    body: str | None,
    *,
    per_signal_limit: int,
    total_remaining: int,
) -> tuple[str | None, str | None, int, bool]:
    allowance = min(per_signal_limit, total_remaining)
    original_title = title or ""
    original_body = body or ""
    original_total = len(original_title) + len(original_body)
    if original_total <= allowance:
        return title, body, original_total, False

    truncated = True
    title_part = original_title[:allowance]
    body_allowance = max(0, allowance - len(title_part))
    body_part = original_body[:body_allowance]
    return (
        title_part or None,
        body_part or None,
        len(title_part) + len(body_part),
        truncated,
    )
