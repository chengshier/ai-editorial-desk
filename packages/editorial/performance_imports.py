from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.connector_management.repositories import AuditLogRepository
from packages.database.models.publication import (
    PerformanceHorizon,
    PerformanceImportRunRecord,
    PerformanceImportStatus,
    PerformanceSourceType,
    PublicationPerformanceSnapshotRecord,
    PublicationRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.editorial.publication_domain import (
    CANONICAL_PERFORMANCE_CSV_FIELDS,
    MAX_PERFORMANCE_CSV_BYTES,
    MAX_PERFORMANCE_CSV_ROWS,
    PERFORMANCE_CSV_VERSION,
    PERFORMANCE_SNAPSHOT_VERSION,
    PerformanceImportConfirmationRequiredError,
    PerformanceImportValidationError,
    PerformanceMetrics,
    PerformanceValidationError,
    PublicationValidationError,
    normalize_public_url,
    normalize_required_text,
    performance_snapshot_hash,
)

_PLATFORM_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


@dataclass(frozen=True, slots=True)
class PerformanceImportError:
    row_number: int
    field: str
    code: str
    message: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "row_number": self.row_number,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class NormalizedPerformanceImportRow:
    row_number: int
    publication_id: UUID
    platform_key: str
    external_post_id: str | None
    public_url: str
    observed_at: datetime
    horizon: PerformanceHorizon
    metrics: PerformanceMetrics
    snapshot_hash: str

    def summary(self, *, duplicate: bool) -> dict[str, object]:
        return {
            "row_number": self.row_number,
            "publication_id": str(self.publication_id),
            "platform_key": self.platform_key,
            "external_post_id": self.external_post_id,
            "public_url": self.public_url,
            "observed_at": self.observed_at.isoformat(),
            "horizon": self.horizon.value,
            "metrics": self.metrics.as_dict(),
            "duplicate": duplicate,
        }


@dataclass(frozen=True, slots=True)
class PerformanceImportPreview:
    mapping_version: str
    file_sha256: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    normalized_rows: tuple[dict[str, object], ...]
    errors: tuple[PerformanceImportError, ...]


@dataclass(frozen=True, slots=True)
class PerformanceImportApplyOutcome:
    run: PerformanceImportRunRecord
    reused: bool


@dataclass(frozen=True, slots=True)
class _ParsedRow:
    row_number: int
    publication_id: UUID | None
    platform_key: str | None
    external_post_id: str | None
    public_url: str | None
    observed_at: datetime
    horizon: PerformanceHorizon
    metrics: PerformanceMetrics


class _RowError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message


class PerformanceImportService:
    """Canonical performance-csv-v1 preview/apply without multipart."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def preview(self, *, csv_text: str) -> PerformanceImportPreview:
        _validate_text_size(csv_text)
        async with self.session_factory() as session:
            return await _analyze(session, csv_text)

    async def apply(
        self,
        *,
        csv_text: str,
        file_name: str | None,
        actor: str,
        confirmation: bool,
    ) -> PerformanceImportApplyOutcome:
        if not confirmation:
            raise PerformanceImportConfirmationRequiredError(
                "CSV Apply 必须显式 confirmation=true"
            )
        normalized_actor = normalize_required_text(actor, "actor", max_length=255)
        _validate_text_size(csv_text)
        normalized_file_name = (
            file_name.strip() if file_name is not None and file_name.strip() else None
        )
        if normalized_file_name is not None and len(normalized_file_name) > 500:
            raise PerformanceImportValidationError("file_name 超过 500 字符")

        async with self.session_factory() as session:
            async with session.begin():
                analysis = await _analyze(session, csv_text)
                if analysis.errors:
                    raise PerformanceImportValidationError(
                        "CSV 存在 validation errors；Apply 已取消",
                        details=[item.as_dict() for item in analysis.errors[:100]],
                    )

                run = PerformanceImportRunRecord(
                    source_type=PerformanceSourceType.CSV,
                    mapping_version=PERFORMANCE_CSV_VERSION,
                    file_name=normalized_file_name,
                    file_sha256=analysis.file_sha256,
                    status=PerformanceImportStatus.RUNNING,
                    row_count=analysis.total_rows,
                    valid_count=analysis.valid_rows,
                    inserted_count=0,
                    duplicate_count=analysis.duplicate_rows,
                    error_count=0,
                    error_summary=[],
                    actor=normalized_actor,
                    finished_at=None,
                )
                try:
                    async with session.begin_nested():
                        session.add(run)
                        await session.flush()
                except IntegrityError:
                    existing = await _successful_run(
                        session,
                        file_sha256=analysis.file_sha256,
                    )
                    if existing is not None:
                        return PerformanceImportApplyOutcome(run=existing, reused=True)
                    raise PerformanceImportValidationError(
                        "相同 CSV 文件正在处理或已存在冲突 ImportRun"
                    ) from None

                rows = await _normalized_rows(session, csv_text)
                publications = await _lock_publications(session, rows)
                for row in rows:
                    publication = publications.get(row.publication_id)
                    if publication is None:
                        raise PerformanceImportValidationError(
                            "Apply 时 Publication 已不存在"
                        )
                    if row.observed_at < publication.published_at:
                        raise PerformanceImportValidationError(
                            "Apply 时 observed_at 早于 published_at"
                        )

                unique_by_hash: dict[str, NormalizedPerformanceImportRow] = {}
                duplicate_count = 0
                for row in rows:
                    if row.snapshot_hash in unique_by_hash:
                        duplicate_count += 1
                    else:
                        unique_by_hash[row.snapshot_hash] = row

                hashes = list(unique_by_hash)
                existing_hashes = await _existing_hashes(session, hashes)
                duplicate_count += len(existing_hashes)
                inserted = 0
                for snapshot_hash, row in unique_by_hash.items():
                    if snapshot_hash in existing_hashes:
                        continue
                    session.add(
                        PublicationPerformanceSnapshotRecord(
                            publication_id=row.publication_id,
                            observed_at=row.observed_at,
                            horizon=row.horizon,
                            source=PerformanceSourceType.CSV,
                            **row.metrics.as_dict(),
                            snapshot_hash=snapshot_hash,
                            supersedes_snapshot_id=None,
                            correction_reason=None,
                            actor=normalized_actor,
                            import_run_id=run.id,
                            snapshot_version=PERFORMANCE_SNAPSHOT_VERSION,
                        )
                    )
                    inserted += 1

                run.inserted_count = inserted
                run.duplicate_count = duplicate_count
                run.status = PerformanceImportStatus.SUCCEEDED
                run.finished_at = utc_now()
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="performance_import_run",
                    entity_id=run.id,
                    action="apply",
                    actor=normalized_actor,
                    before_data={},
                    after_data={
                        "mapping_version": PERFORMANCE_CSV_VERSION,
                        "file_sha256": analysis.file_sha256,
                        "row_count": run.row_count,
                        "inserted_count": inserted,
                        "duplicate_count": duplicate_count,
                    },
                )
                return PerformanceImportApplyOutcome(run=run, reused=False)


async def _successful_run(
    session: AsyncSession, *, file_sha256: str
) -> PerformanceImportRunRecord | None:
    return (
        await session.scalars(
            select(PerformanceImportRunRecord).where(
                PerformanceImportRunRecord.file_sha256 == file_sha256,
                PerformanceImportRunRecord.mapping_version == PERFORMANCE_CSV_VERSION,
                PerformanceImportRunRecord.status == PerformanceImportStatus.SUCCEEDED,
            )
        )
    ).first()


async def _lock_publications(
    session: AsyncSession,
    rows: tuple[NormalizedPerformanceImportRow, ...],
) -> dict[UUID, PublicationRecord]:
    publication_ids = sorted({row.publication_id for row in rows}, key=str)
    if not publication_ids:
        return {}
    records = (
        await session.scalars(
            select(PublicationRecord)
            .where(PublicationRecord.id.in_(publication_ids))
            .order_by(PublicationRecord.id.asc())
            .with_for_update()
        )
    ).all()
    return {item.id: item for item in records}


async def _analyze(
    session: AsyncSession, csv_text: str
) -> PerformanceImportPreview:
    parsed, parse_errors, total_rows = _parse_csv(csv_text)
    file_hash = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    if parse_errors:
        return PerformanceImportPreview(
            mapping_version=PERFORMANCE_CSV_VERSION,
            file_sha256=file_hash,
            total_rows=total_rows,
            valid_rows=0 if not parsed else len(parsed),
            invalid_rows=max(1, total_rows - len(parsed)),
            duplicate_rows=0,
            normalized_rows=(),
            errors=tuple(parse_errors),
        )

    rows, resolve_errors = await _resolve_rows(session, parsed)
    hashes = [row.snapshot_hash for row in rows]
    existing_hashes = await _existing_hashes(session, hashes)
    seen: set[str] = set()
    duplicate_rows = 0
    summaries: list[dict[str, object]] = []
    for row in rows:
        duplicate = row.snapshot_hash in seen or row.snapshot_hash in existing_hashes
        if duplicate:
            duplicate_rows += 1
        seen.add(row.snapshot_hash)
        if len(summaries) < 50:
            summaries.append(row.summary(duplicate=duplicate))

    return PerformanceImportPreview(
        mapping_version=PERFORMANCE_CSV_VERSION,
        file_sha256=file_hash,
        total_rows=total_rows,
        valid_rows=len(rows),
        invalid_rows=max(0, total_rows - len(rows)),
        duplicate_rows=duplicate_rows,
        normalized_rows=tuple(summaries),
        errors=tuple(resolve_errors),
    )


async def _existing_hashes(
    session: AsyncSession, hashes: list[str]
) -> set[str]:
    if not hashes:
        return set()
    return set(
        (
            await session.scalars(
                select(PublicationPerformanceSnapshotRecord.snapshot_hash).where(
                    PublicationPerformanceSnapshotRecord.snapshot_hash.in_(hashes)
                )
            )
        ).all()
    )


async def _normalized_rows(
    session: AsyncSession, csv_text: str
) -> tuple[NormalizedPerformanceImportRow, ...]:
    parsed, parse_errors, _total_rows = _parse_csv(csv_text)
    if parse_errors:
        raise PerformanceImportValidationError(
            "CSV Apply revalidation 失败",
            details=[item.as_dict() for item in parse_errors[:100]],
        )
    rows, resolve_errors = await _resolve_rows(session, parsed)
    if resolve_errors:
        raise PerformanceImportValidationError(
            "CSV Apply revalidation 失败",
            details=[item.as_dict() for item in resolve_errors[:100]],
        )
    return tuple(rows)


def _validate_text_size(csv_text: str) -> None:
    if not csv_text.strip():
        raise PerformanceImportValidationError("csv_text 不能为空")
    size = len(csv_text.encode("utf-8"))
    if size > MAX_PERFORMANCE_CSV_BYTES:
        raise PerformanceImportValidationError(
            f"CSV 最大允许 {MAX_PERFORMANCE_CSV_BYTES} bytes"
        )


def _parse_csv(
    csv_text: str,
) -> tuple[list[_ParsedRow], list[PerformanceImportError], int]:
    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    fieldnames = tuple(reader.fieldnames or ())
    required = set(CANONICAL_PERFORMANCE_CSV_FIELDS)
    missing = sorted(required - set(fieldnames))
    extra = sorted(set(fieldnames) - required)
    errors: list[PerformanceImportError] = []
    if missing:
        errors.append(
            PerformanceImportError(
                1,
                "header",
                "MISSING_COLUMNS",
                f"missing: {', '.join(missing)}",
            )
        )
    if extra:
        errors.append(
            PerformanceImportError(
                1,
                "header",
                "UNKNOWN_COLUMNS",
                f"unknown: {', '.join(extra)}",
            )
        )
    if errors:
        return [], errors, sum(1 for _ in reader)

    parsed: list[_ParsedRow] = []
    total_rows = 0
    for row_number, raw in enumerate(reader, start=2):
        total_rows += 1
        if total_rows > MAX_PERFORMANCE_CSV_ROWS:
            errors.append(
                PerformanceImportError(
                    row_number,
                    "file",
                    "ROW_LIMIT_EXCEEDED",
                    f"最多允许 {MAX_PERFORMANCE_CSV_ROWS} 行",
                )
            )
            break
        try:
            parsed.append(_parse_row(raw, row_number))
        except _RowError as exc:
            errors.append(
                PerformanceImportError(
                    row_number,
                    exc.field,
                    exc.code,
                    exc.message,
                )
            )
        except (PerformanceValidationError, PublicationValidationError) as exc:
            errors.append(
                PerformanceImportError(
                    row_number,
                    "metrics",
                    "INVALID_VALUE",
                    str(exc),
                )
            )
    if total_rows > MAX_PERFORMANCE_CSV_ROWS:
        return [], errors, total_rows
    return parsed, errors, total_rows


def _parse_row(raw: dict[str, str | None], row_number: int) -> _ParsedRow:
    publication_id = _optional_uuid(raw.get("publication_id"), row_number)
    platform_key = _optional_platform(raw.get("platform_key"), row_number)
    external_post_id = _blank_to_none(raw.get("external_post_id"))
    public_url = _optional_url(raw.get("public_url"), row_number)
    if (
        publication_id is None
        and not (platform_key and external_post_id)
        and public_url is None
    ):
        raise _RowError(
            "publication_id",
            "PUBLICATION_IDENTITY_REQUIRED",
            "缺少 Publication 唯一匹配字段",
        )
    observed_at = _parse_time(raw.get("observed_at"))
    horizon_raw = (raw.get("horizon") or "").strip()
    try:
        horizon = PerformanceHorizon(horizon_raw)
    except ValueError as exc:
        raise _RowError(
            "horizon",
            "INVALID_HORIZON",
            "horizon 必须是 h1/h24/d7/custom",
        ) from exc
    metrics = PerformanceMetrics(
        views=_parse_int(raw.get("views"), "views", signed=False),
        completion_rate=_parse_percent(raw.get("completion_rate_percent")),
        average_watch_seconds=_parse_float(
            raw.get("average_watch_seconds"),
            "average_watch_seconds",
            nonnegative=True,
        ),
        likes=_parse_int(raw.get("likes"), "likes", signed=False),
        comments=_parse_int(raw.get("comments"), "comments", signed=False),
        shares=_parse_int(raw.get("shares"), "shares", signed=False),
        favorites=_parse_int(raw.get("favorites"), "favorites", signed=False),
        follower_delta=_parse_int(
            raw.get("follower_delta"),
            "follower_delta",
            signed=True,
        ),
    ).validate()
    return _ParsedRow(
        row_number=row_number,
        publication_id=publication_id,
        platform_key=platform_key,
        external_post_id=external_post_id,
        public_url=public_url,
        observed_at=observed_at,
        horizon=horizon,
        metrics=metrics,
    )


async def _resolve_rows(
    session: AsyncSession,
    parsed: list[_ParsedRow],
) -> tuple[list[NormalizedPerformanceImportRow], list[PerformanceImportError]]:
    errors: list[PerformanceImportError] = []
    ids = {row.publication_id for row in parsed if row.publication_id is not None}
    external_keys = {
        (row.platform_key, row.external_post_id)
        for row in parsed
        if row.publication_id is None and row.platform_key and row.external_post_id
    }
    urls = {
        row.public_url
        for row in parsed
        if row.publication_id is None
        and not (row.platform_key and row.external_post_id)
        and row.public_url is not None
    }

    by_id = await _publications_by_id(session, ids)
    by_external = await _publications_by_external(session, external_keys)
    by_url = await _publications_by_url(session, urls)

    rows: list[NormalizedPerformanceImportRow] = []
    for row in parsed:
        publication, error = _match_publication(row, by_id, by_external, by_url)
        if error is not None:
            errors.append(error)
            continue
        assert publication is not None
        mismatch = _identity_mismatch(row, publication)
        if mismatch is not None:
            errors.append(mismatch)
            continue
        if row.observed_at < publication.published_at:
            errors.append(
                _error(
                    row,
                    "observed_at",
                    "OBSERVED_BEFORE_PUBLISHED",
                    "observed_at 不能早于 published_at",
                )
            )
            continue
        snapshot_hash = performance_snapshot_hash(
            publication_id=publication.id,
            observed_at=row.observed_at,
            horizon=row.horizon,
            metrics=row.metrics,
            source=PerformanceSourceType.CSV,
        )
        rows.append(
            NormalizedPerformanceImportRow(
                row_number=row.row_number,
                publication_id=publication.id,
                platform_key=publication.platform_key,
                external_post_id=publication.external_post_id,
                public_url=publication.public_url,
                observed_at=row.observed_at,
                horizon=row.horizon,
                metrics=row.metrics,
                snapshot_hash=snapshot_hash,
            )
        )
    return rows, errors


async def _publications_by_id(
    session: AsyncSession,
    ids: set[UUID | None],
) -> dict[UUID, PublicationRecord]:
    concrete = {item for item in ids if item is not None}
    if not concrete:
        return {}
    records = (
        await session.scalars(
            select(PublicationRecord).where(PublicationRecord.id.in_(concrete))
        )
    ).all()
    return {item.id: item for item in records}


async def _publications_by_external(
    session: AsyncSession,
    keys: set[tuple[str | None, str | None]],
) -> dict[tuple[str, str], PublicationRecord]:
    concrete = {
        (platform, external)
        for platform, external in keys
        if platform is not None and external is not None
    }
    if not concrete:
        return {}
    records = (
        await session.scalars(
            select(PublicationRecord).where(
                tuple_(
                    PublicationRecord.platform_key,
                    PublicationRecord.external_post_id,
                ).in_(concrete)
            )
        )
    ).all()
    return {
        (item.platform_key, item.external_post_id): item
        for item in records
        if item.external_post_id is not None
    }


async def _publications_by_url(
    session: AsyncSession,
    urls: set[str | None],
) -> dict[str, list[PublicationRecord]]:
    concrete = {item for item in urls if item is not None}
    result: dict[str, list[PublicationRecord]] = {}
    if not concrete:
        return result
    records = (
        await session.scalars(
            select(PublicationRecord).where(PublicationRecord.public_url.in_(concrete))
        )
    ).all()
    for item in records:
        result.setdefault(item.public_url, []).append(item)
    return result


def _match_publication(
    row: _ParsedRow,
    by_id: dict[UUID, PublicationRecord],
    by_external: dict[tuple[str, str], PublicationRecord],
    by_url: dict[str, list[PublicationRecord]],
) -> tuple[PublicationRecord | None, PerformanceImportError | None]:
    if row.publication_id is not None:
        publication = by_id.get(row.publication_id)
        if publication is None:
            return None, _error(
                row,
                "publication_id",
                "PUBLICATION_NOT_FOUND",
                "publication_id 不存在",
            )
        return publication, None
    if row.platform_key and row.external_post_id:
        publication = by_external.get((row.platform_key, row.external_post_id))
        if publication is None:
            return None, _error(
                row,
                "external_post_id",
                "PUBLICATION_NOT_FOUND",
                "platform_key + external_post_id 未匹配 Publication",
            )
        return publication, None
    if row.public_url is not None:
        matches = by_url.get(row.public_url, [])
        if row.platform_key is not None:
            matches = [
                item for item in matches if item.platform_key == row.platform_key
            ]
        if len(matches) != 1:
            code = "PUBLICATION_NOT_FOUND" if not matches else "AMBIGUOUS_PUBLICATION"
            return None, _error(
                row,
                "public_url",
                code,
                "public_url 必须唯一匹配一条 Publication",
            )
        return matches[0], None
    return None, _error(
        row,
        "publication_id",
        "PUBLICATION_NOT_FOUND",
        "无法匹配 Publication",
    )


def _identity_mismatch(
    row: _ParsedRow,
    publication: PublicationRecord,
) -> PerformanceImportError | None:
    if row.platform_key is not None and row.platform_key != publication.platform_key:
        return _error(
            row,
            "platform_key",
            "IDENTITY_MISMATCH",
            "platform_key 与匹配 Publication 不一致",
        )
    if (
        row.external_post_id is not None
        and row.external_post_id != publication.external_post_id
    ):
        return _error(
            row,
            "external_post_id",
            "IDENTITY_MISMATCH",
            "external_post_id 与匹配 Publication 不一致",
        )
    if row.public_url is not None and row.public_url != publication.public_url:
        return _error(
            row,
            "public_url",
            "IDENTITY_MISMATCH",
            "public_url 与匹配 Publication 不一致",
        )
    return None


def _optional_uuid(value: str | None, row_number: int) -> UUID | None:
    normalized = _blank_to_none(value)
    if normalized is None:
        return None
    try:
        return UUID(normalized)
    except ValueError as exc:
        raise _RowError(
            "publication_id",
            "INVALID_UUID",
            f"row {row_number}: publication_id 不是 UUID",
        ) from exc


def _optional_platform(value: str | None, row_number: int) -> str | None:
    normalized = _blank_to_none(value)
    if normalized is None:
        return None
    normalized = normalized.casefold()
    if not _PLATFORM_KEY.fullmatch(normalized):
        raise _RowError(
            "platform_key",
            "INVALID_PLATFORM_KEY",
            f"row {row_number}: platform_key 格式无效",
        )
    return normalized


def _optional_url(value: str | None, row_number: int) -> str | None:
    normalized = _blank_to_none(value)
    if normalized is None:
        return None
    try:
        return normalize_public_url(normalized)
    except PublicationValidationError as exc:
        raise _RowError(
            "public_url",
            "INVALID_URL",
            f"row {row_number}: {exc}",
        ) from exc


def _parse_time(value: str | None) -> datetime:
    normalized = _blank_to_none(value)
    if normalized is None:
        raise _RowError("observed_at", "REQUIRED", "observed_at 必填")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _RowError(
            "observed_at",
            "INVALID_DATETIME",
            "observed_at 必须是 ISO 8601",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _RowError(
            "observed_at",
            "TIMEZONE_REQUIRED",
            "observed_at 必须包含 timezone",
        )
    return parsed.astimezone(UTC)


def _parse_int(value: str | None, field: str, *, signed: bool) -> int | None:
    normalized = _blank_to_none(value)
    if normalized is None:
        return None
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise _RowError(field, "INVALID_INTEGER", f"{field} 必须是整数") from exc
    if not signed and parsed < 0:
        raise _RowError(
            field,
            "NEGATIVE_NOT_ALLOWED",
            f"{field} 不能小于 0",
        )
    return parsed


def _parse_float(
    value: str | None,
    field: str,
    *,
    nonnegative: bool,
) -> float | None:
    normalized = _blank_to_none(value)
    if normalized is None:
        return None
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise _RowError(field, "INVALID_NUMBER", f"{field} 必须是数字") from exc
    if not math.isfinite(parsed):
        raise _RowError(field, "INVALID_NUMBER", f"{field} 必须是有限数字")
    if nonnegative and parsed < 0:
        raise _RowError(
            field,
            "NEGATIVE_NOT_ALLOWED",
            f"{field} 不能小于 0",
        )
    return parsed


def _parse_percent(value: str | None) -> float | None:
    parsed = _parse_float(
        value,
        "completion_rate_percent",
        nonnegative=True,
    )
    if parsed is None:
        return None
    if parsed > 100:
        raise _RowError(
            "completion_rate_percent",
            "PERCENT_OUT_OF_RANGE",
            "completion_rate_percent 必须在 0..100",
        )
    return parsed / 100.0


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _error(
    row: _ParsedRow,
    field: str,
    code: str,
    message: str,
) -> PerformanceImportError:
    return PerformanceImportError(row.row_number, field, code, message)
