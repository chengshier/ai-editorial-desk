from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import RawSignalRecord, SignalEmbeddingRecord


@dataclass(frozen=True, slots=True)
class SimilarityCandidate:
    candidate_signal_id: UUID
    similarity: float
    embedding_version: str
    published_at: datetime | None
    collected_at: datetime
    platform: str
    source_id: UUID


class SignalEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, signal_id: UUID, embedding_version: str
    ) -> SignalEmbeddingRecord | None:
        statement = select(SignalEmbeddingRecord).where(
            SignalEmbeddingRecord.signal_id == signal_id,
            SignalEmbeddingRecord.embedding_version == embedding_version,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_many(
        self,
        signal_ids: list[UUID],
        embedding_version: str,
    ) -> dict[UUID, SignalEmbeddingRecord]:
        if not signal_ids:
            return {}
        statement = select(SignalEmbeddingRecord).where(
            SignalEmbeddingRecord.signal_id.in_(signal_ids),
            SignalEmbeddingRecord.embedding_version == embedding_version,
        )
        records = list((await self.session.scalars(statement)).all())
        return {record.signal_id: record for record in records}

    async def list_versions(self, signal_id: UUID) -> list[SignalEmbeddingRecord]:
        statement = (
            select(SignalEmbeddingRecord)
            .where(SignalEmbeddingRecord.signal_id == signal_id)
            .order_by(
                SignalEmbeddingRecord.created_at.desc(),
                SignalEmbeddingRecord.embedding_version.asc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def missing_signal_ids(
        self,
        signal_ids: list[UUID],
        embedding_version: str,
    ) -> list[UUID]:
        existing = await self.get_many(signal_ids, embedding_version)
        return [signal_id for signal_id in signal_ids if signal_id not in existing]

    async def insert_idempotently(
        self,
        *,
        signal_id: UUID,
        provider_key: str,
        model_name: str,
        dimensions: int,
        embedding_version: str,
        input_schema_version: str,
        input_hash: str,
        embedding: list[float],
    ) -> tuple[SignalEmbeddingRecord, bool]:
        statement = (
            insert(SignalEmbeddingRecord)
            .values(
                signal_id=signal_id,
                provider_key=provider_key,
                model_name=model_name,
                dimensions=dimensions,
                embedding_version=embedding_version,
                input_schema_version=input_schema_version,
                input_hash=input_hash,
                embedding=embedding,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SignalEmbeddingRecord.signal_id,
                    SignalEmbeddingRecord.embedding_version,
                ]
            )
            .returning(SignalEmbeddingRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(SignalEmbeddingRecord, created_id)
            if created is None:
                raise RuntimeError("SignalEmbedding 写入成功后未找到记录")
            return created, True

        existing = await self.get(signal_id, embedding_version)
        if existing is None:
            raise RuntimeError("SignalEmbedding 幂等冲突后未找到既有记录")
        return existing, False

    async def exact_cosine_recall(
        self,
        *,
        target: SignalEmbeddingRecord,
        top_k: int,
        min_similarity: float | None,
        time_from: datetime | None,
        time_to: datetime | None,
    ) -> list[SimilarityCandidate]:
        embedding_column = cast(Any, SignalEmbeddingRecord.embedding)
        distance = embedding_column.cosine_distance(list(target.embedding)).label(
            "cosine_distance"
        )
        effective_time = func.coalesce(
            RawSignalRecord.published_at,
            RawSignalRecord.collected_at,
        )
        filters = [
            SignalEmbeddingRecord.embedding_version == target.embedding_version,
            SignalEmbeddingRecord.dimensions == target.dimensions,
            SignalEmbeddingRecord.signal_id != target.signal_id,
        ]
        if min_similarity is not None:
            filters.append(distance <= 1.0 - min_similarity)
        if time_from is not None:
            filters.append(effective_time >= time_from)
        if time_to is not None:
            filters.append(effective_time <= time_to)

        statement = (
            select(
                SignalEmbeddingRecord.signal_id,
                RawSignalRecord.published_at,
                RawSignalRecord.collected_at,
                RawSignalRecord.platform,
                RawSignalRecord.source_id,
                distance,
            )
            .select_from(SignalEmbeddingRecord)
            .join(
                RawSignalRecord,
                RawSignalRecord.id == SignalEmbeddingRecord.signal_id,
            )
            .where(*filters)
            .order_by(distance.asc(), SignalEmbeddingRecord.signal_id.asc())
            .limit(top_k)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            SimilarityCandidate(
                candidate_signal_id=row[0],
                similarity=1.0 - float(row[5]),
                embedding_version=target.embedding_version,
                published_at=row[1],
                collected_at=row[2],
                platform=row[3],
                source_id=row[4],
            )
            for row in rows
        ]
