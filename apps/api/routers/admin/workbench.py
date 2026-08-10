from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from apps.api.auth import require_admin_token
from apps.api.schemas.workbench import (
    WorkbenchEventDetailResponse,
    WorkbenchEventPageResponse,
    WorkbenchOverviewResponse,
    WorkbenchSignalPageResponse,
)
from packages.database.models import (
    EditorialDecisionType,
    EditorialRiskLevel,
    EventStatus,
)
from packages.workbench.m5b import M5BEditorialWorkbenchQueryService

router = APIRouter(
    prefix="/workbench",
    tags=["admin-workbench"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/overview", response_model=WorkbenchOverviewResponse)
async def get_workbench_overview() -> WorkbenchOverviewResponse:
    payload = await M5BEditorialWorkbenchQueryService().overview()
    return WorkbenchOverviewResponse.model_validate(payload)


@router.get("/events", response_model=WorkbenchEventPageResponse)
async def list_workbench_events(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: EventStatus | None = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    include_merged: bool = False,
    risk: EditorialRiskLevel | None = None,
    has_evidence: bool | None = None,
    has_score: bool | None = None,
    has_draft: bool | None = None,
    decision: EditorialDecisionType | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    q: Annotated[str | None, Query(max_length=500)] = None,
    sort_by: Literal["last_updated_at", "first_seen_at", "traffic_total"] = "last_updated_at",
    sort_direction: Literal["asc", "desc"] = "desc",
) -> WorkbenchEventPageResponse:
    result = await M5BEditorialWorkbenchQueryService().list_events(
        page=page,
        page_size=page_size,
        status=status,
        category=category,
        include_merged=include_merged,
        risk=risk,
        has_evidence=has_evidence,
        has_score=has_score,
        has_draft=has_draft,
        decision=decision,
        updated_from=updated_from,
        updated_to=updated_to,
        q=q,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    return WorkbenchEventPageResponse.model_validate(
        {
            "items": list(result.items),
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "has_next": result.has_next,
        }
    )


@router.get("/events/{event_id}", response_model=WorkbenchEventDetailResponse)
async def get_workbench_event(event_id: UUID) -> WorkbenchEventDetailResponse:
    payload = await M5BEditorialWorkbenchQueryService().event_detail(event_id)
    return WorkbenchEventDetailResponse.model_validate(payload)


@router.get("/events/{event_id}/signals", response_model=WorkbenchSignalPageResponse)
async def list_workbench_event_signals(
    event_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkbenchSignalPageResponse:
    result = await M5BEditorialWorkbenchQueryService().list_event_signals(
        event_id,
        page=page,
        page_size=page_size,
    )
    return WorkbenchSignalPageResponse.model_validate(
        {
            "items": list(result.items),
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "has_next": result.has_next,
        }
    )
