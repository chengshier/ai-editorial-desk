from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m3c import (
    ClusterBatchRequest,
    ClusterBatchResponse,
    ClusteringPreviewRequest,
    ClusteringPreviewResponse,
    ClusterOutcomeResponse,
    ClusterSignalRequest,
    FingerprintPreviewResponse,
    MatchDecisionResponse,
)
from apps.api.schemas.m3d import (
    ClusteringEvaluationRequest,
    ClusteringEvaluationResponse,
    ClusteringReprocessApplyRequest,
    ClusteringReprocessBaseRequest,
    ClusteringReprocessResponse,
    ReprocessOutcomeResponse,
)
from packages.clustering.evaluation import (
    M3_EVALUATION_DATASET_VERSION,
    ClusteringEvaluationService,
    load_evaluation_dataset,
    threshold_sweep,
)
from packages.clustering.policy import DEFAULT_CLUSTER_POLICY
from packages.clustering.provenance import ClusteringProcessingRunRepository
from packages.clustering.reprocessing import ClusteringReprocessService, ReprocessSummary
from packages.clustering.services import (
    ClusteringBatchProcessor,
    EventClusteringService,
    SignalMatchService,
)
from packages.connector_management.exceptions import BusinessValidationError
from packages.database.models import ClusteringProcessingMode, ClusteringProcessingStatus
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/clustering",
    tags=["admin-clustering"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]
EVALUATION_DATASETS = {
    M3_EVALUATION_DATASET_VERSION: Path("tests/evaluation/m3_clustering_eval_v1.jsonl")
}


def _reprocess_response(summary: ReprocessSummary) -> ClusteringReprocessResponse:
    return ClusteringReprocessResponse(
        processing_run_id=summary.processing_run_id,
        algorithm_version=summary.algorithm_version,
        dry_run=summary.dry_run,
        scanned=summary.scanned,
        would_attach=summary.would_attach,
        would_create_event=summary.would_create_event,
        would_move=summary.would_move,
        would_detach=summary.would_detach,
        ambiguous=summary.ambiguous,
        skipped_human=summary.skipped_human,
        suppressed=summary.suppressed,
        unchanged=summary.unchanged,
        failed=summary.failed,
        outcomes=[
            ReprocessOutcomeResponse(
                signal_id=item.signal_id,
                action=item.action,
                code=item.code,
                current_event_id=item.current_event_id,
                target_event_id=item.target_event_id,
                candidate_signal_id=item.candidate_signal_id,
                decision=item.decision.value if item.decision else None,
                score=item.score,
                attached_by=item.attached_by.value if item.attached_by else None,
            )
            for item in summary.outcomes
        ],
    )


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


@router.post("/evaluate", response_model=ClusteringEvaluationResponse)
async def evaluate_clustering(
    payload: ClusteringEvaluationRequest,
    session: Session,
) -> ClusteringEvaluationResponse:
    if payload.algorithm_version != DEFAULT_CLUSTER_POLICY.algorithm_version:
        raise BusinessValidationError("algorithm_version 未注册")
    dataset = EVALUATION_DATASETS.get(payload.dataset_version)
    if dataset is None:
        raise BusinessValidationError("dataset_version 未注册")
    signals = load_evaluation_dataset(dataset)
    result = ClusteringEvaluationService().evaluate(signals)
    sweep = threshold_sweep(signals) if payload.threshold_sweep else ()
    pair_metrics = asdict(result.pair_metrics)
    cluster_metrics = asdict(result.cluster_metrics)
    async with session.begin():
        runs = ClusteringProcessingRunRepository(session)
        run = await runs.create(
            mode=ClusteringProcessingMode.EVALUATE,
            algorithm_version=result.algorithm_version,
            dataset_version=result.dataset_version,
            actor=None,
            requested_count=len(signals),
            config_snapshot={
                "threshold_sweep": payload.threshold_sweep,
                "threshold_sweep_read_only": True,
                "production_policy_modified": False,
            },
        )
        await runs.finish(
            run,
            status=ClusteringProcessingStatus.SUCCEEDED,
            processed_count=len(signals),
            counters={
                "pair_metrics": pair_metrics,
                "cluster_metrics": cluster_metrics,
                "human_override_respect_rate": result.human_override_respect_rate,
            },
        )
    return ClusteringEvaluationResponse(
        evaluation_kind="OFFLINE ENGINEERING EVALUATION",
        dataset_version=result.dataset_version,
        algorithm_version=result.algorithm_version,
        fingerprint_version=result.fingerprint_version,
        pair_metrics=pair_metrics,
        cluster_metrics=cluster_metrics,
        human_override_respected_count=result.human_override_respected_count,
        human_override_total=result.human_override_total,
        human_override_respect_rate=result.human_override_respect_rate,
        performance=asdict(result.performance),
        threshold_sweep=[asdict(item) for item in sweep],
        threshold_sweep_read_only=True,
        production_policy_modified=False,
    )


@router.post("/reprocess/preview", response_model=ClusteringReprocessResponse)
async def preview_reprocess(
    payload: ClusteringReprocessBaseRequest,
    session: Session,
) -> ClusteringReprocessResponse:
    summary = await ClusteringReprocessService(session).reprocess(
        signal_ids=payload.signal_ids,
        time_from=payload.time_from,
        time_to=payload.time_to,
        algorithm_version=payload.algorithm_version,
        embedding_version=payload.embedding_version,
        max_items=payload.max_items,
        actor=None,
        apply=False,
        confirmed=False,
    )
    return _reprocess_response(summary)


@router.post("/reprocess", response_model=ClusteringReprocessResponse)
async def apply_reprocess(
    payload: ClusteringReprocessApplyRequest,
    session: Session,
    actor: Actor,
) -> ClusteringReprocessResponse:
    summary = await ClusteringReprocessService(session).reprocess(
        signal_ids=payload.signal_ids,
        time_from=payload.time_from,
        time_to=payload.time_to,
        algorithm_version=payload.algorithm_version,
        embedding_version=payload.embedding_version,
        max_items=payload.max_items,
        actor=actor,
        apply=True,
        confirmed=payload.confirmation,
    )
    return _reprocess_response(summary)
