from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SignalEmbeddingMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signal_id: UUID
    provider_key: str
    model_name: str
    dimensions: int
    embedding_version: str
    input_schema_version: str
    input_hash: str
    created_at: datetime


class SignalEmbeddingMetadataList(BaseModel):
    signal_id: UUID
    items: list[SignalEmbeddingMetadataResponse]


class SignalSimilarityRecallRequest(BaseModel):
    signal_id: UUID
    embedding_version: str = Field(min_length=1, max_length=100)
    top_k: int = Field(default=10, ge=1, le=100)
    min_similarity: float | None = Field(
        default=None,
        ge=-1,
        le=1,
        allow_inf_nan=False,
    )
    time_from: datetime | None = None
    time_to: datetime | None = None


class SignalSimilarityCandidateResponse(BaseModel):
    candidate_signal_id: UUID
    similarity: float
    embedding_version: str
    published_at: datetime | None
    collected_at: datetime
    platform: str
    source_id: UUID


class SignalSimilarityRecallResponse(BaseModel):
    signal_id: UUID
    embedding_version: str
    candidates: list[SignalSimilarityCandidateResponse]
