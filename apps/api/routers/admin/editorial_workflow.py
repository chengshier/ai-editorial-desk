from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m5b import (
    CandidateApplyRequestBody,
    CandidateApplyResponse,
    CandidateGenerationRequestBody,
    CandidateListItemResponse,
    CandidateListResponse,
    CandidatePoolPreviewResponse,
    CandidateRunResponse,
    CandidateSnapshotResponse,
    EditorialDecisionApplyResponse,
    EditorialDecisionHistoryItemResponse,
    EditorialDecisionRequestBody,
    EditorialDecisionResponse,
    EventWorkflowSummaryResponse,
)
from packages.database.models import (
    CandidateGroup,
    EditorialDecisionType,
    EditorialRiskLevel,
)
from packages.editorial.candidates import CandidateGenerationRequest, DailyCandidateService
from packages.editorial.decisions import EditorialDecisionService
from packages.editorial.workflow_queries import EditorialWorkflowQueryService

router = APIRouter(
    prefix="/editorial",
    tags=["admin-editorial-workflow"],
    dependencies=[Depends(require_admin_token)],
)
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("/candidate-runs/preview", response_model=CandidatePoolPreviewResponse)
async def preview_candidate_run(
    payload: CandidateGenerationRequestBody,
) -> CandidatePoolPreviewResponse:
    preview = await DailyCandidateService().preview(_request(payload))
    return CandidatePoolPreviewResponse(
        business_date=preview.business_date,
        timezone=preview.timezone,
        as_of_at=preview.as_of_at,
        window_start_at=preview.window_start_at,
        window_end_at=preview.window_end_at,
        ranking_version=preview.ranking_version,
        requested_limit=preview.requested_limit,
        input_hash=preview.input_hash,
        scanned_event_count=preview.scanned_event_count,
        eligible_event_count=preview.eligible_event_count,
        candidate_count=preview.candidate_count,
        skipped_event_count=preview.skipped_event_count,
        skip_summary=preview.skip_summary,
        candidates=[CandidateSnapshotResponse.model_validate(item) for item in preview.candidates],
    )


@router.post("/candidate-runs", response_model=CandidateApplyResponse, status_code=201)
async def apply_candidate_run(
    payload: CandidateApplyRequestBody,
    actor: Actor,
) -> CandidateApplyResponse:
    outcome = await DailyCandidateService().apply(
        _request(payload),
        actor=actor,
        confirmed=payload.confirmation,
    )
    return CandidateApplyResponse(
        run=CandidateRunResponse.model_validate(outcome.run),
        candidates=[CandidateSnapshotResponse.model_validate(item) for item in outcome.candidates],
        reused=outcome.reused,
    )


@router.get("/candidate-runs", response_model=list[CandidateRunResponse])
async def list_candidate_runs(
    business_date: date | None = None,
    timezone: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[CandidateRunResponse]:
    rows = await EditorialWorkflowQueryService().list_runs(
        business_date=business_date,
        timezone=timezone,
        limit=limit,
    )
    return [CandidateRunResponse.model_validate(item) for item in rows]


@router.get("/candidate-runs/{run_id}", response_model=CandidateRunResponse)
async def get_candidate_run(run_id: UUID) -> CandidateRunResponse:
    row = await EditorialWorkflowQueryService().get_run(run_id)
    return CandidateRunResponse.model_validate(row)


@router.get("/candidate-runs/{run_id}/candidates", response_model=CandidateListResponse)
async def list_run_candidates(
    run_id: UUID,
    top_n: int = Query(default=20, ge=1, le=100),
    candidate_group: CandidateGroup | None = None,
    decision: EditorialDecisionType | None = None,
    risk: EditorialRiskLevel | None = None,
    category: str | None = None,
) -> CandidateListResponse:
    return await _candidate_list_response(
        run_id=run_id,
        top_n=top_n,
        candidate_group=candidate_group,
        decision=decision,
        risk=risk,
        category=category,
    )


@router.get("/candidates", response_model=CandidateListResponse)
async def list_latest_candidates(
    business_date: date | None = None,
    timezone: str | None = None,
    top_n: int = Query(default=20, ge=1, le=100),
    candidate_group: CandidateGroup | None = None,
    decision: EditorialDecisionType | None = None,
    risk: EditorialRiskLevel | None = None,
    category: str | None = None,
) -> CandidateListResponse:
    return await _candidate_list_response(
        business_date=business_date,
        timezone=timezone,
        top_n=top_n,
        candidate_group=candidate_group,
        decision=decision,
        risk=risk,
        category=category,
    )


@router.get(
    "/events/{event_id}/decisions",
    response_model=list[EditorialDecisionHistoryItemResponse],
)
async def list_event_decisions(event_id: UUID) -> list[EditorialDecisionHistoryItemResponse]:
    rows = await EditorialWorkflowQueryService().decision_history(event_id)
    return [
        EditorialDecisionHistoryItemResponse(
            decision=EditorialDecisionResponse.model_validate(row["decision"]),
            candidate_rank=row["candidate_rank"],  # type: ignore[arg-type]
            candidate_run_id=row["candidate_run_id"],  # type: ignore[arg-type]
            candidate_business_date=row["candidate_business_date"],  # type: ignore[arg-type]
            candidate_as_of_at=row["candidate_as_of_at"],  # type: ignore[arg-type]
        )
        for row in rows
    ]


@router.post(
    "/events/{event_id}/decision",
    response_model=EditorialDecisionApplyResponse,
    status_code=201,
)
async def apply_event_decision(
    event_id: UUID,
    payload: EditorialDecisionRequestBody,
    actor: Actor,
) -> EditorialDecisionApplyResponse:
    outcome = await EditorialDecisionService().decide(
        event_id=event_id,
        candidate_id=payload.candidate_id,
        decision=payload.decision,
        expected_previous_decision_id=payload.expected_previous_decision_id,
        risk_acknowledged=payload.risk_acknowledged,
        reason=payload.reason,
        actor=actor,
        confirmation=payload.confirmation,
    )
    return EditorialDecisionApplyResponse(
        decision=EditorialDecisionResponse.model_validate(outcome.decision),
        reused=outcome.reused,
    )


@router.get(
    "/events/{event_id}/workflow-summary",
    response_model=EventWorkflowSummaryResponse,
)
async def get_event_workflow_summary(event_id: UUID) -> EventWorkflowSummaryResponse:
    result = await EditorialWorkflowQueryService().event_workflow_summary(event_id)
    return EventWorkflowSummaryResponse(
        current_editorial_decision=(
            EditorialDecisionResponse.model_validate(result["current_editorial_decision"])
            if result["current_editorial_decision"] is not None
            else None
        ),
        latest_candidate=(
            CandidateSnapshotResponse.model_validate(result["latest_candidate"])
            if result["latest_candidate"] is not None
            else None
        ),
        latest_candidate_run=(
            CandidateRunResponse.model_validate(result["latest_candidate_run"])
            if result["latest_candidate_run"] is not None
            else None
        ),
    )


async def _candidate_list_response(
    *,
    run_id: UUID | None = None,
    business_date: date | None = None,
    timezone: str | None = None,
    top_n: int,
    candidate_group: CandidateGroup | None,
    decision: EditorialDecisionType | None,
    risk: EditorialRiskLevel | None,
    category: str | None,
) -> CandidateListResponse:
    result = await EditorialWorkflowQueryService().list_candidates(
        run_id=run_id,
        business_date=business_date,
        timezone=timezone,
        top_n=top_n,
        candidate_group=candidate_group,
        decision=decision,
        risk=risk,
        category=category,
    )
    items = [
        CandidateListItemResponse(
            candidate=CandidateSnapshotResponse.model_validate(item["candidate"]),
            current_event_status=item["current_event_status"],  # type: ignore[arg-type]
            merged_into_event_id=item["merged_into_event_id"],  # type: ignore[arg-type]
            current_editorial_decision=(
                EditorialDecisionResponse.model_validate(item["current_editorial_decision"])
                if item["current_editorial_decision"] is not None
                else None
            ),
            stale_indicator=item["stale_indicator"],  # type: ignore[arg-type]
        )
        for item in result.items
    ]
    return CandidateListResponse(
        run=CandidateRunResponse.model_validate(result.run),
        items=items,
        total=result.total,
        top_n=result.top_n,
    )


def _request(payload: CandidateGenerationRequestBody) -> CandidateGenerationRequest:
    return CandidateGenerationRequest(
        business_date=payload.business_date,
        timezone=payload.timezone,
        as_of_at=payload.as_of_at,
        lookback_hours=payload.lookback_hours,
        requested_limit=payload.requested_limit,
        include_resolved=payload.include_resolved,
        include_archived=payload.include_archived,
    )
