from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m4c import (
    EditorialOverrideRequest,
    EditorialOverrideResponse,
    EditorialScoreRequest,
    EditorialScoreResponse,
    EditorialScoreRunResponse,
    EffectiveEditorialResponse,
    ManualEditorialScoreRequest,
    TrendCalculateRequest,
    TrendCalculateResponse,
    TrendSnapshotResponse,
)
from packages.ai_gateway.errors import AIGatewayError
from packages.editorial.errors import EditorialAIError
from packages.editorial.services import (
    EditorialScoringOutcome,
    EditorialScoringService,
    TrendService,
)

router = APIRouter(
    prefix="/events",
    tags=["admin-editorial"],
    dependencies=[Depends(require_admin_token)],
)
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("/{event_id}/trend", response_model=TrendSnapshotResponse | None)
async def get_event_trend(event_id: UUID) -> TrendSnapshotResponse | None:
    snapshot = await TrendService().latest(event_id)
    return TrendSnapshotResponse.model_validate(snapshot) if snapshot is not None else None


@router.post(
    "/{event_id}/trend/calculate",
    response_model=TrendCalculateResponse,
)
async def calculate_event_trend(
    event_id: UUID,
    payload: TrendCalculateRequest,
    actor: Actor,
) -> TrendCalculateResponse:
    del actor
    outcome = await TrendService().calculate(
        event_id=event_id,
        window_start_at=payload.window_start_at,
        window_end_at=payload.window_end_at,
    )
    return TrendCalculateResponse(
        snapshot=TrendSnapshotResponse.model_validate(outcome.snapshot),
        created=outcome.created,
    )


@router.get(
    "/{event_id}/editorial-scores",
    response_model=list[EditorialScoreResponse],
)
async def list_editorial_scores(event_id: UUID) -> list[EditorialScoreResponse]:
    scores = await EditorialScoringService().list_scores(event_id)
    return [EditorialScoreResponse.model_validate(item) for item in scores]


@router.get(
    "/{event_id}/editorial-scores/effective",
    response_model=EffectiveEditorialResponse,
)
async def get_effective_editorial_score(event_id: UUID) -> EffectiveEditorialResponse:
    outcome = await EditorialScoringService().effective(event_id)
    return EffectiveEditorialResponse(
        event_id=outcome.event_id,
        latest_ai_score=(
            EditorialScoreResponse.model_validate(outcome.latest_ai_score)
            if outcome.latest_ai_score is not None
            else None
        ),
        latest_human_score=(
            EditorialScoreResponse.model_validate(outcome.latest_human_score)
            if outcome.latest_human_score is not None
            else None
        ),
        effective_base_score_id=outcome.effective_base_score_id,
        effective_values=outcome.effective_values,
        applied_overrides=[
            EditorialOverrideResponse.model_validate(item)
            for item in outcome.applied_overrides
        ],
    )


@router.post(
    "/{event_id}/editorial-scores/preview",
    response_model=EditorialScoreRunResponse,
)
async def preview_editorial_score(
    event_id: UUID,
    payload: EditorialScoreRequest,
    actor: Actor,
) -> EditorialScoreRunResponse:
    return await _run_ai_score(
        event_id,
        payload.trend_snapshot_id,
        actor,
        apply=False,
    )


@router.post(
    "/{event_id}/editorial-scores",
    response_model=EditorialScoreRunResponse,
)
async def apply_editorial_score(
    event_id: UUID,
    payload: EditorialScoreRequest,
    actor: Actor,
) -> EditorialScoreRunResponse:
    return await _run_ai_score(
        event_id,
        payload.trend_snapshot_id,
        actor,
        apply=True,
    )


@router.post(
    "/{event_id}/editorial-scores/manual",
    response_model=EditorialScoreResponse,
    status_code=201,
)
async def create_manual_editorial_score(
    event_id: UUID,
    payload: ManualEditorialScoreRequest,
    actor: Actor,
) -> EditorialScoreResponse:
    score = await EditorialScoringService().create_manual_score(
        event_id=event_id,
        trend_snapshot_id=payload.trend_snapshot_id,
        actor=actor,
        reason=payload.reason,
        dimensions={
            "emotion": payload.emotion,
            "information_gap": payload.information_gap,
            "visual_value": payload.visual_value,
            "user_relevance": payload.user_relevance,
            "discussion": payload.discussion,
            "novelty": payload.novelty,
            "extendability": payload.extendability,
        },
        risk_level=payload.risk_level,
        recommended_format=payload.recommended_format,
        model_reason=payload.model_reason,
    )
    return EditorialScoreResponse.model_validate(score)


@router.post(
    "/{event_id}/editorial-scores/{score_id}/override",
    response_model=EditorialOverrideResponse,
    status_code=201,
)
async def override_editorial_score(
    event_id: UUID,
    score_id: UUID,
    payload: EditorialOverrideRequest,
    actor: Actor,
) -> EditorialOverrideResponse:
    fields = payload.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"reason"},
    )
    override = await EditorialScoringService().override_score(
        event_id=event_id,
        score_id=score_id,
        actor=actor,
        reason=payload.reason,
        overridden_fields=fields,
    )
    return EditorialOverrideResponse.model_validate(override)


async def _run_ai_score(
    event_id: UUID,
    trend_snapshot_id: UUID,
    actor: str,
    *,
    apply: bool,
) -> EditorialScoreRunResponse:
    try:
        outcome = await EditorialScoringService().score(
            event_id=event_id,
            trend_snapshot_id=trend_snapshot_id,
            actor=actor,
            apply=apply,
        )
    except AIGatewayError as exc:
        raise EditorialAIError(exc.code.value, exc.message) from exc
    return _outcome_response(outcome)


def _outcome_response(outcome: EditorialScoringOutcome) -> EditorialScoreRunResponse:
    dimensions = outcome.candidate.dimensions
    return EditorialScoreRunResponse(
        run_id=outcome.run_id,
        ai_invocation_id=outcome.ai_invocation_id,
        mode=outcome.mode,
        status=outcome.status,
        score=(
            EditorialScoreResponse.model_validate(outcome.score)
            if outcome.score is not None
            else None
        ),
        emotion=dimensions.emotion,
        information_gap=dimensions.information_gap,
        visual_value=dimensions.visual_value,
        user_relevance=dimensions.user_relevance,
        discussion=dimensions.discussion,
        novelty=dimensions.novelty,
        extendability=dimensions.extendability,
        traffic_total=outcome.traffic_total,
        risk_level=outcome.candidate.risk_level,
        recommended_format=outcome.candidate.recommended_format,
        model_reason=outcome.candidate.model_reason,
        reused=outcome.reused,
    )
