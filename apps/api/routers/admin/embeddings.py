from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_admin_token
from apps.api.schemas.m3b import (
    SignalEmbeddingMetadataList,
    SignalEmbeddingMetadataResponse,
    SignalSimilarityCandidateResponse,
    SignalSimilarityRecallRequest,
    SignalSimilarityRecallResponse,
)
from packages.database.session import get_database_session
from packages.embeddings.services import EmbeddingService, SignalSimilarityService

router = APIRouter(
    prefix="/embeddings",
    tags=["admin-embeddings"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get(
    "/signals/{signal_id}",
    response_model=SignalEmbeddingMetadataList,
)
async def list_signal_embeddings(
    signal_id: UUID,
    session: Session,
) -> SignalEmbeddingMetadataList:
    records = await EmbeddingService(session).list_versions(signal_id)
    return SignalEmbeddingMetadataList(
        signal_id=signal_id,
        items=[
            SignalEmbeddingMetadataResponse.model_validate(record)
            for record in records
        ],
    )


@router.post("/recall", response_model=SignalSimilarityRecallResponse)
async def recall_similar_signals(
    payload: SignalSimilarityRecallRequest,
    session: Session,
) -> SignalSimilarityRecallResponse:
    candidates = await SignalSimilarityService(session).recall(
        signal_id=payload.signal_id,
        embedding_version=payload.embedding_version,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
        time_from=payload.time_from,
        time_to=payload.time_to,
    )
    return SignalSimilarityRecallResponse(
        signal_id=payload.signal_id,
        embedding_version=payload.embedding_version,
        candidates=[
            SignalSimilarityCandidateResponse(
                candidate_signal_id=item.candidate_signal_id,
                similarity=item.similarity,
                embedding_version=item.embedding_version,
                published_at=item.published_at,
                collected_at=item.collected_at,
                platform=item.platform,
                source_id=item.source_id,
            )
            for item in candidates
        ],
    )
