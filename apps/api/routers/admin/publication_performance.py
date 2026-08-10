from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m5c import (
    ManualPerformanceRequest,
    PerformanceImportApplyRequest,
    PerformanceImportApplyResponse,
    PerformanceImportErrorResponse,
    PerformanceImportPreviewRequest,
    PerformanceImportPreviewResponse,
    PerformanceImportRunResponse,
    PerformanceOverviewResponse,
    PerformanceSnapshotCreateResponse,
    PerformanceSnapshotResponse,
    PerformanceTimelineItemResponse,
    PublicationCorrectionRequest,
    PublicationCreateRequest,
    PublicationCreateResponse,
    PublicationDetailResponse,
    PublicationListResponse,
    PublicationResponse,
)
from packages.database.models import EditorialDecisionType, EditorialRecommendedFormat
from packages.database.models.publication import PublicationMode
from packages.editorial.performance_imports import PerformanceImportService
from packages.editorial.performance_queries import PerformanceFeedbackQueryService
from packages.editorial.publication_domain import (
    PerformanceMetrics,
    PublicationValidationError,
    require_aware_utc,
)
from packages.editorial.publication_services import (
    PublicationPerformanceService,
    PublicationService,
)

router = APIRouter(
    tags=["admin-publication-performance"],
    dependencies=[Depends(require_admin_token)],
)
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("/publications", response_model=PublicationListResponse)
async def list_publications(
    platform_key: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    event_id: UUID | None = None,
    draft_id: UUID | None = None,
    publication_mode: PublicationMode | None = None,
    has_performance: bool | None = None,
    editorial_decision_snapshot: EditorialDecisionType | None = None,
    recommended_format_snapshot: EditorialRecommendedFormat | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PublicationListResponse:
    result = await PerformanceFeedbackQueryService().list_publications(
        platform_key=platform_key,
        published_from=_optional_aware(published_from, "published_from"),
        published_to=_optional_aware(published_to, "published_to"),
        event_id=event_id,
        draft_id=draft_id,
        publication_mode=publication_mode,
        has_performance=has_performance,
        editorial_decision_snapshot=editorial_decision_snapshot,
        recommended_format_snapshot=(
            recommended_format_snapshot.value if recommended_format_snapshot else None
        ),
        page=page,
        page_size=page_size,
    )
    return PublicationListResponse.model_validate(
        {
            "items": list(result.items),
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
        }
    )


@router.post("/publications", response_model=PublicationCreateResponse, status_code=201)
async def record_publication(
    payload: PublicationCreateRequest,
    actor: Actor,
) -> PublicationCreateResponse:
    outcome = await PublicationService().create(
        event_id=payload.event_id,
        publication_mode=payload.publication_mode,
        platform_key=payload.platform_key,
        public_url=payload.public_url,
        published_at=payload.published_at,
        actor=actor,
        draft_id=payload.draft_id,
        account_label=payload.account_label,
        external_post_id=payload.external_post_id,
        title_snapshot=payload.title_snapshot,
        cover_text_snapshot=payload.cover_text_snapshot,
        body_snapshot=payload.body_snapshot,
        backfill_reason=payload.backfill_reason,
    )
    return PublicationCreateResponse(
        publication=PublicationResponse.model_validate(outcome.publication),
        reused=outcome.reused,
    )


@router.get("/publications/{publication_id}", response_model=PublicationDetailResponse)
async def get_publication(publication_id: UUID) -> PublicationDetailResponse:
    item = await PerformanceFeedbackQueryService().get_publication(publication_id)
    return PublicationDetailResponse.model_validate(item)


@router.patch("/publications/{publication_id}", response_model=PublicationResponse)
async def correct_publication(
    publication_id: UUID,
    payload: PublicationCorrectionRequest,
    actor: Actor,
) -> PublicationResponse:
    changes = payload.model_dump(exclude={"reason"}, exclude_unset=True)
    if "public_url" in changes and changes["public_url"] is None:
        raise PublicationValidationError("public_url 不能清空")
    if "published_at" in changes and changes["published_at"] is None:
        raise PublicationValidationError("published_at 不能清空")
    publication = await PublicationService().correct(
        publication_id=publication_id,
        actor=actor,
        reason=payload.reason,
        changes=changes,
    )
    return PublicationResponse.model_validate(publication)


@router.get(
    "/publications/{publication_id}/performance",
    response_model=list[PerformanceTimelineItemResponse],
)
async def publication_performance(
    publication_id: UUID,
) -> list[PerformanceTimelineItemResponse]:
    timeline = await PerformanceFeedbackQueryService().performance_timeline(publication_id)
    return [PerformanceTimelineItemResponse.model_validate(item) for item in timeline]


@router.post(
    "/publications/{publication_id}/performance",
    response_model=PerformanceSnapshotCreateResponse,
    status_code=201,
)
async def record_manual_performance(
    publication_id: UUID,
    payload: ManualPerformanceRequest,
    actor: Actor,
) -> PerformanceSnapshotCreateResponse:
    metrics = PerformanceMetrics(
        views=payload.views,
        completion_rate=(
            payload.completion_rate_percent / 100.0
            if payload.completion_rate_percent is not None
            else None
        ),
        average_watch_seconds=payload.average_watch_seconds,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        favorites=payload.favorites,
        follower_delta=payload.follower_delta,
    )
    outcome = await PublicationPerformanceService().add_manual_snapshot(
        publication_id=publication_id,
        observed_at=payload.observed_at,
        horizon=payload.horizon,
        metrics=metrics,
        actor=actor,
        supersedes_snapshot_id=payload.supersedes_snapshot_id,
        correction_reason=payload.correction_reason,
    )
    return PerformanceSnapshotCreateResponse(
        snapshot=PerformanceSnapshotResponse.model_validate(outcome.snapshot),
        reused=outcome.reused,
    )


@router.post(
    "/performance-imports/preview",
    response_model=PerformanceImportPreviewResponse,
)
async def preview_performance_import(
    payload: PerformanceImportPreviewRequest,
) -> PerformanceImportPreviewResponse:
    preview = await PerformanceImportService().preview(csv_text=payload.csv_text)
    return PerformanceImportPreviewResponse(
        mapping_version=preview.mapping_version,
        file_sha256=preview.file_sha256,
        total_rows=preview.total_rows,
        valid_rows=preview.valid_rows,
        invalid_rows=preview.invalid_rows,
        duplicate_rows=preview.duplicate_rows,
        normalized_rows=list(preview.normalized_rows),
        errors=[
            PerformanceImportErrorResponse(**item.as_dict()) for item in preview.errors
        ],
    )


@router.post(
    "/performance-imports",
    response_model=PerformanceImportApplyResponse,
    status_code=201,
)
async def apply_performance_import(
    payload: PerformanceImportApplyRequest,
    actor: Actor,
) -> PerformanceImportApplyResponse:
    outcome = await PerformanceImportService().apply(
        csv_text=payload.csv_text,
        file_name=payload.file_name,
        actor=actor,
        confirmation=payload.confirmation,
    )
    return PerformanceImportApplyResponse(
        run=PerformanceImportRunResponse.model_validate(outcome.run),
        reused=outcome.reused,
    )


@router.get(
    "/performance-imports",
    response_model=list[PerformanceImportRunResponse],
)
async def list_performance_imports(
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PerformanceImportRunResponse]:
    runs = await PerformanceFeedbackQueryService().list_import_runs(limit=limit)
    return [PerformanceImportRunResponse.model_validate(item) for item in runs]


@router.get(
    "/performance-imports/{run_id}",
    response_model=PerformanceImportRunResponse,
)
async def get_performance_import(run_id: UUID) -> PerformanceImportRunResponse:
    run = await PerformanceFeedbackQueryService().get_import_run(run_id)
    return PerformanceImportRunResponse.model_validate(run)


@router.get("/performance/overview", response_model=PerformanceOverviewResponse)
async def performance_overview(
    platform_key: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
) -> PerformanceOverviewResponse:
    result = await PerformanceFeedbackQueryService().overview(
        platform_key=platform_key,
        published_from=_optional_aware(published_from, "published_from"),
        published_to=_optional_aware(published_to, "published_to"),
    )
    return PerformanceOverviewResponse.model_validate(result)


@router.get("/performance/publications", response_model=PublicationListResponse)
async def feedback_publications(
    platform_key: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PublicationListResponse:
    result = await PerformanceFeedbackQueryService().list_publications(
        platform_key=platform_key,
        published_from=_optional_aware(published_from, "published_from"),
        published_to=_optional_aware(published_to, "published_to"),
        has_performance=None,
        page=page,
        page_size=page_size,
    )
    return PublicationListResponse.model_validate(
        {
            "items": list(result.items),
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
        }
    )


def _optional_aware(value: datetime | None, field: str) -> datetime | None:
    return require_aware_utc(value, field) if value is not None else None
