from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from packages.connector_management.exceptions import ResourceNotFoundError
from packages.database.models import (
    CandidateRunStatus,
    ConfigurationChangeLog,
    DailyCandidateRunRecord,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialRecommendedFormat,
    EventRecord,
)
from packages.database.models.publication import (
    PerformanceImportRunRecord,
    PublicationMode,
    PublicationPerformanceSnapshotRecord,
    PublicationRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.publication_domain import (
    PerformanceMetrics,
    engagement_rate,
    metric_delta,
)


@dataclass(frozen=True, slots=True)
class PublicationListResult:
    items: tuple[dict[str, object], ...]
    total: int
    page: int
    page_size: int


class PerformanceFeedbackQueryService:
    """Read-only M5-C projection; never updates editorial artifacts or calls AI."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def list_publications(
        self,
        *,
        platform_key: str | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
        event_id: UUID | None = None,
        draft_id: UUID | None = None,
        publication_mode: PublicationMode | None = None,
        has_performance: bool | None = None,
        editorial_decision_snapshot: EditorialDecisionType | None = None,
        recommended_format_snapshot: EditorialRecommendedFormat | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PublicationListResult:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        filters = _publication_filters(
            platform_key=platform_key,
            published_from=published_from,
            published_to=published_to,
            event_id=event_id,
            draft_id=draft_id,
            publication_mode=publication_mode,
            has_performance=has_performance,
            editorial_decision_snapshot=editorial_decision_snapshot,
            recommended_format_snapshot=recommended_format_snapshot,
        )
        latest = _latest_effective_snapshot_ids()
        async with self.session_factory() as session:
            total = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PublicationRecord)
                    .where(*filters)
                )
                or 0
            )
            rows = (
                await session.execute(
                    select(
                        PublicationRecord,
                        EventRecord.title.label("event_title"),
                        PublicationPerformanceSnapshotRecord,
                    )
                    .join(EventRecord, EventRecord.id == PublicationRecord.event_id)
                    .outerjoin(latest, latest.c.publication_id == PublicationRecord.id)
                    .outerjoin(
                        PublicationPerformanceSnapshotRecord,
                        PublicationPerformanceSnapshotRecord.id == latest.c.snapshot_id,
                    )
                    .where(*filters)
                    .order_by(
                        PublicationRecord.published_at.desc(),
                        PublicationRecord.created_at.desc(),
                        PublicationRecord.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            return PublicationListResult(
                items=tuple(
                    _publication_projection(
                        publication,
                        str(event_title),
                        latest_snapshot,
                    )
                    for publication, event_title, latest_snapshot in rows
                ),
                total=total,
                page=page,
                page_size=page_size,
            )

    async def get_publication(self, publication_id: UUID) -> dict[str, object]:
        latest = _latest_effective_snapshot_ids()
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(
                        PublicationRecord,
                        EventRecord.title.label("event_title"),
                        PublicationPerformanceSnapshotRecord,
                    )
                    .join(EventRecord, EventRecord.id == PublicationRecord.event_id)
                    .outerjoin(latest, latest.c.publication_id == PublicationRecord.id)
                    .outerjoin(
                        PublicationPerformanceSnapshotRecord,
                        PublicationPerformanceSnapshotRecord.id == latest.c.snapshot_id,
                    )
                    .where(PublicationRecord.id == publication_id)
                )
            ).first()
            if row is None:
                raise ResourceNotFoundError("Publication 不存在")
            audit = tuple(
                (
                    await session.scalars(
                        select(ConfigurationChangeLog)
                        .where(
                            ConfigurationChangeLog.entity_type == "publication",
                            ConfigurationChangeLog.entity_id == publication_id,
                        )
                        .order_by(
                            ConfigurationChangeLog.created_at.asc(),
                            ConfigurationChangeLog.id.asc(),
                        )
                    )
                ).all()
            )
            projection = _publication_projection(row[0], str(row[1]), row[2])
            projection["audit_entries"] = audit
            return projection

    async def performance_timeline(
        self,
        publication_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        async with self.session_factory() as session:
            if await session.get(PublicationRecord, publication_id) is None:
                raise ResourceNotFoundError("Publication 不存在")
            snapshots = list(
                (
                    await session.scalars(
                        select(PublicationPerformanceSnapshotRecord)
                        .where(
                            PublicationPerformanceSnapshotRecord.publication_id
                            == publication_id
                        )
                        .order_by(
                            PublicationPerformanceSnapshotRecord.observed_at.asc(),
                            PublicationPerformanceSnapshotRecord.created_at.asc(),
                            PublicationPerformanceSnapshotRecord.id.asc(),
                        )
                    )
                ).all()
            )
            superseded_ids = {
                item.supersedes_snapshot_id
                for item in snapshots
                if item.supersedes_snapshot_id is not None
            }
            result: list[dict[str, object]] = []
            previous_effective: PublicationPerformanceSnapshotRecord | None = None
            for snapshot in snapshots:
                is_effective = snapshot.id not in superseded_ids
                rate, unavailable_reason = engagement_rate(_metrics(snapshot))
                deltas: dict[str, int | float | None] = {
                    "views": None,
                    "likes": None,
                    "comments": None,
                    "shares": None,
                    "follower_delta": None,
                }
                if is_effective and previous_effective is not None:
                    deltas = {
                        "views": metric_delta(
                            snapshot.views,
                            previous_effective.views,
                        ),
                        "likes": metric_delta(
                            snapshot.likes,
                            previous_effective.likes,
                        ),
                        "comments": metric_delta(
                            snapshot.comments,
                            previous_effective.comments,
                        ),
                        "shares": metric_delta(
                            snapshot.shares,
                            previous_effective.shares,
                        ),
                        "follower_delta": metric_delta(
                            snapshot.follower_delta,
                            previous_effective.follower_delta,
                        ),
                    }
                result.append(
                    {
                        "snapshot": snapshot,
                        "is_effective": is_effective,
                        "engagement_rate": rate,
                        "engagement_rate_unavailable_reason": unavailable_reason,
                        "deltas": deltas,
                    }
                )
                if is_effective:
                    previous_effective = snapshot
            return tuple(result)

    async def overview(
        self,
        *,
        platform_key: str | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
    ) -> dict[str, object]:
        filters = _publication_filters(
            platform_key=platform_key,
            published_from=published_from,
            published_to=published_to,
            event_id=None,
            draft_id=None,
            publication_mode=None,
            has_performance=None,
            editorial_decision_snapshot=None,
            recommended_format_snapshot=None,
        )
        async with self.session_factory() as session:
            latest_run = (
                await session.scalars(
                    select(DailyCandidateRunRecord)
                    .where(DailyCandidateRunRecord.status == CandidateRunStatus.SUCCEEDED)
                    .order_by(
                        DailyCandidateRunRecord.business_date.desc(),
                        DailyCandidateRunRecord.as_of_at.desc(),
                        DailyCandidateRunRecord.created_at.desc(),
                        DailyCandidateRunRecord.id.desc(),
                    )
                    .limit(1)
                )
            ).first()
            adopted_count = await _current_adopted_count(session)
            publication_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PublicationRecord)
                    .where(*filters)
                )
                or 0
            )
            with_performance = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PublicationRecord)
                    .where(
                        *filters,
                        exists(
                            select(1).where(
                                PublicationPerformanceSnapshotRecord.publication_id
                                == PublicationRecord.id
                            )
                        ),
                    )
                )
                or 0
            )
            publication_ids = select(PublicationRecord.id).where(*filters)
            latest_observed = await session.scalar(
                select(
                    func.max(PublicationPerformanceSnapshotRecord.observed_at)
                ).where(
                    PublicationPerformanceSnapshotRecord.publication_id.in_(
                        publication_ids
                    )
                )
            )
            platform_rows = (
                await session.execute(
                    select(PublicationRecord.platform_key, func.count())
                    .where(*filters)
                    .group_by(PublicationRecord.platform_key)
                    .order_by(PublicationRecord.platform_key.asc())
                )
            ).all()
            return {
                "candidate_count": latest_run.candidate_count if latest_run else 0,
                "candidate_run_id": str(latest_run.id) if latest_run else None,
                "adopted_count": adopted_count,
                "published_count": publication_count,
                "with_performance_count": with_performance,
                "latest_observed_at": latest_observed,
                "platform_counts": {
                    str(key): int(count) for key, count in platform_rows
                },
                "note": (
                    "observational funnel only; no causal or cross-platform "
                    "winner score"
                ),
            }

    async def list_import_runs(
        self,
        *,
        limit: int = 50,
    ) -> tuple[PerformanceImportRunRecord, ...]:
        limit = max(1, min(limit, 100))
        async with self.session_factory() as session:
            return tuple(
                (
                    await session.scalars(
                        select(PerformanceImportRunRecord)
                        .order_by(
                            PerformanceImportRunRecord.created_at.desc(),
                            PerformanceImportRunRecord.id.desc(),
                        )
                        .limit(limit)
                    )
                ).all()
            )

    async def get_import_run(self, run_id: UUID) -> PerformanceImportRunRecord:
        async with self.session_factory() as session:
            run = await session.get(PerformanceImportRunRecord, run_id)
            if run is None:
                raise ResourceNotFoundError("Performance ImportRun 不存在")
            return run


async def _current_adopted_count(session: AsyncSession) -> int:
    latest_decision = (
        select(
            EditorialDecisionRecord.event_id.label("event_id"),
            EditorialDecisionRecord.decision.label("decision"),
            func.row_number()
            .over(
                partition_by=EditorialDecisionRecord.event_id,
                order_by=(
                    EditorialDecisionRecord.created_at.desc(),
                    EditorialDecisionRecord.id.desc(),
                ),
            )
            .label("rn"),
        )
    ).subquery()
    return int(
        await session.scalar(
            select(func.count())
            .select_from(latest_decision)
            .where(
                latest_decision.c.rn == 1,
                latest_decision.c.decision == EditorialDecisionType.ADOPT,
            )
        )
        or 0
    )


def _publication_filters(
    *,
    platform_key: str | None,
    published_from: datetime | None,
    published_to: datetime | None,
    event_id: UUID | None,
    draft_id: UUID | None,
    publication_mode: PublicationMode | None,
    has_performance: bool | None,
    editorial_decision_snapshot: EditorialDecisionType | None,
    recommended_format_snapshot: EditorialRecommendedFormat | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if platform_key and platform_key.strip():
        filters.append(
            PublicationRecord.platform_key == platform_key.strip().casefold()
        )
    if published_from is not None:
        filters.append(PublicationRecord.published_at >= published_from)
    if published_to is not None:
        filters.append(PublicationRecord.published_at <= published_to)
    if event_id is not None:
        filters.append(PublicationRecord.event_id == event_id)
    if draft_id is not None:
        filters.append(PublicationRecord.draft_id == draft_id)
    if publication_mode is not None:
        filters.append(PublicationRecord.publication_mode == publication_mode)
    if editorial_decision_snapshot is not None:
        filters.append(
            PublicationRecord.editorial_decision_snapshot
            == editorial_decision_snapshot
        )
    if recommended_format_snapshot is not None:
        filters.append(
            PublicationRecord.recommended_format_snapshot
            == recommended_format_snapshot
        )
    if has_performance is not None:
        predicate = exists(
            select(1).where(
                PublicationPerformanceSnapshotRecord.publication_id
                == PublicationRecord.id
            )
        )
        filters.append(predicate if has_performance else ~predicate)
    return filters


def _latest_effective_snapshot_ids() -> Subquery:
    child = aliased(PublicationPerformanceSnapshotRecord)
    effective = (
        select(
            PublicationPerformanceSnapshotRecord.id.label("snapshot_id"),
            PublicationPerformanceSnapshotRecord.publication_id.label(
                "publication_id"
            ),
            func.row_number()
            .over(
                partition_by=(
                    PublicationPerformanceSnapshotRecord.publication_id
                ),
                order_by=(
                    PublicationPerformanceSnapshotRecord.observed_at.desc(),
                    PublicationPerformanceSnapshotRecord.created_at.desc(),
                    PublicationPerformanceSnapshotRecord.id.desc(),
                ),
            )
            .label("rn"),
        )
        .where(
            ~exists(
                select(1).where(
                    child.supersedes_snapshot_id
                    == PublicationPerformanceSnapshotRecord.id
                )
            )
        )
        .subquery()
    )
    return (
        select(effective.c.snapshot_id, effective.c.publication_id)
        .where(effective.c.rn == 1)
        .subquery()
    )


def _publication_projection(
    publication: PublicationRecord,
    event_title: str,
    latest_snapshot: PublicationPerformanceSnapshotRecord | None,
) -> dict[str, object]:
    latest: dict[str, object] | None = None
    if latest_snapshot is not None:
        rate, reason = engagement_rate(_metrics(latest_snapshot))
        latest = {
            "snapshot": latest_snapshot,
            "engagement_rate": rate,
            "engagement_rate_unavailable_reason": reason,
        }
    return {
        "publication": publication,
        "event_title": event_title,
        "latest_performance": latest,
    }


def _metrics(
    snapshot: PublicationPerformanceSnapshotRecord,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        views=snapshot.views,
        completion_rate=snapshot.completion_rate,
        average_watch_seconds=snapshot.average_watch_seconds,
        likes=snapshot.likes,
        comments=snapshot.comments,
        shares=snapshot.shares,
        favorites=snapshot.favorites,
        follower_delta=snapshot.follower_delta,
    )
