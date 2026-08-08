from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m3c import (
    ClusterBatchRequest,
    ClusterBatchResponse,
    ClusterOutcomeResponse,
    ClusteringPreviewRequest,
    ClusteringPreviewResponse,
    ClusterSignalRequest,
    FingerprintPreviewResponse,
    MatchDecisionResponse,
)
from packages.clustering.services import (
    ClusteringBatchProcessor,
    EventClusteringService,
    SignalMatchService,
)
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/clustering",
    tags=["admin-clustering"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("/preview", response_model=ClusteringPreviewResponse)
async def preview_clustering(
    payload: ClusteringPreviewRequest,
    session: Session,
) -> ClusteringPreviewResponse:
    preview = await SignalMatchService(session).preview(
        signal_id=payload.signal_id,
        embedding_version=payload.embedding_version,
    )
    fingerprint = None
    if preview.fingerprint is not None:
        fingerprint = FingerprintPreviewResponse(
            fingerprint_version=preview.fingerprint.fingerprint_version,
            input_hash=preview.fingerprint.input_hash,
            simhash=preview.fingerprint.simhash,
            token_count=preview.fingerprint.token_count,
        )
    return ClusteringPreviewResponse(
        signal_id=preview.signal_id,
        fingerprint=fingerprint,
        decisions=[
            MatchDecisionResponse(
                candidate_signal_id=item.candidate_signal_id,
                decision=item.decision,
                primary_method=item.primary_method,
                score=item.score,
                components=item.components,
                algorithm_version=item.algorithm_version,
            )
            for item in preview.decisions
        ],
    )


@router.post("/signals/{signal_id}", response_model=ClusterOutcomeResponse)
async def cluster_signal(
    signal_id: UUID,
    payload: ClusterSignalRequest,
    session: Session,
    actor: Actor,
) -> ClusterOutcomeResponse:
    outcome = await EventClusteringService(session).cluster_signal(
        signal_id=signal_id,
        embedding_version=payload.embedding_version,
        actor=actor,
    )
    return ClusterOutcomeResponse(
        signal_id=outcome.signal_id,
        status=outcome.status,
        code=outcome.code,
        event_id=outcome.event_id,
        candidate_event_ids=list(outcome.candidate_event_ids),
    )


@router.post("/batch", response_model=ClusterBatchResponse)
async def cluster_batch(
    payload: ClusterBatchRequest,
    session: Session,
    actor: Actor,
) -> ClusterBatchResponse:
    summary = await ClusteringBatchProcessor(session).process(
        signal_ids=payload.signal_ids,
        embedding_version=payload.embedding_version,
        actor=actor,
        batch_size=payload.batch_size,
    )
    return ClusterBatchResponse(
        requested=summary.requested,
        processed=summary.processed,
        attached=summary.attached,
        created_event=summary.created_event,
        ambiguous=summary.ambiguous,
        skipped=summary.skipped,
        failed=summary.failed,
        outcomes=[
            ClusterOutcomeResponse(
                signal_id=item.signal_id,
                status=item.status,
                code=item.code,
                event_id=item.event_id,
                candidate_event_ids=list(item.candidate_event_ids),
            )
            for item in summary.outcomes
        ],
    )
