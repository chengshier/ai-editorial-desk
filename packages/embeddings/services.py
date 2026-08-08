from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
)
from packages.database.models import RawSignalRecord, SignalEmbeddingRecord
from packages.embeddings.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
    EmbeddingVersionConflictError,
    InvalidEmbeddingResponseError,
)
from packages.embeddings.input_builder import EmbeddingInput, EmbeddingInputBuilder
from packages.embeddings.providers import (
    EmbeddingBatchResult,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingRequestItem,
)
from packages.embeddings.repositories import SimilarityCandidate, SignalEmbeddingRepository
from packages.signals.repositories import RawSignalRepository

logger = logging.getLogger(__name__)


class EmbeddingOutcomeStatus(StrEnum):
    GENERATED = "generated"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EmbeddingBatchOutcome:
    signal_id: UUID
    status: EmbeddingOutcomeStatus
    code: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingBatchSummary:
    requested: int
    generated: int
    skipped: int
    failed: int
    outcomes: tuple[EmbeddingBatchOutcome, ...]


@dataclass(frozen=True, slots=True)
class _PendingEmbedding:
    signal: RawSignalRecord
    input: EmbeddingInput


def _validate_provider_contract(
    provider: EmbeddingProvider,
    embedding_version: str,
) -> None:
    if not provider.provider_key.strip():
        raise BusinessValidationError("Embedding provider_key 不能为空")
    if not provider.model_name.strip():
        raise BusinessValidationError("Embedding model_name 不能为空")
    if not embedding_version.strip():
        raise BusinessValidationError("embedding_version 不能为空")
    if provider.embedding_version != embedding_version:
        raise EmbeddingVersionConflictError(
            "Provider embedding_version 与请求版本不一致"
        )
    if provider.dimensions <= 0:
        raise EmbeddingDimensionMismatchError("Provider dimensions 必须大于 0")


def _validate_vector(vector: tuple[float, ...], dimensions: int) -> list[float]:
    if not vector:
        raise InvalidEmbeddingResponseError("Provider 返回了空向量")
    if len(vector) != dimensions:
        raise EmbeddingDimensionMismatchError(
            "Provider 返回向量长度与 dimensions 不一致"
        )
    normalized = [float(value) for value in vector]
    if any(not math.isfinite(value) for value in normalized):
        raise InvalidEmbeddingResponseError("Embedding 向量包含 NaN 或 Infinity")
    norm = math.sqrt(sum(value * value for value in normalized))
    if not math.isfinite(norm) or norm <= 0:
        raise InvalidEmbeddingResponseError("Cosine recall 不允许零向量或无效向量")
    return normalized


def _artifact_matches(
    artifact: SignalEmbeddingRecord,
    *,
    provider: EmbeddingProvider,
    embedding_input: EmbeddingInput,
) -> bool:
    return (
        artifact.input_hash == embedding_input.input_hash
        and artifact.input_schema_version == embedding_input.input_schema_version
        and artifact.provider_key == provider.provider_key
        and artifact.model_name == provider.model_name
        and artifact.dimensions == provider.dimensions
        and artifact.embedding_version == provider.embedding_version
    )


class EmbeddingBatchProcessor:
    """Generate immutable SignalEmbedding artifacts in bounded provider batches."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        input_builder: EmbeddingInputBuilder | None = None,
    ) -> None:
        self.session = session
        self.input_builder = input_builder or EmbeddingInputBuilder()
        self.raw_signals = RawSignalRepository(session)
        self.embeddings = SignalEmbeddingRepository(session)

    async def process(
        self,
        *,
        signal_ids: list[UUID],
        embedding_version: str,
        provider: EmbeddingProvider,
        batch_size: int = 32,
        max_provider_attempts: int = 1,
    ) -> EmbeddingBatchSummary:
        _validate_provider_contract(provider, embedding_version)
        if batch_size < 1 or batch_size > 1000:
            raise BusinessValidationError("batch_size 必须在 1 到 1000 之间")
        if max_provider_attempts < 1 or max_provider_attempts > 3:
            raise BusinessValidationError("max_provider_attempts 必须在 1 到 3 之间")

        unique_signal_ids = list(dict.fromkeys(signal_ids))
        outcomes: list[EmbeddingBatchOutcome] = []
        for offset in range(0, len(unique_signal_ids), batch_size):
            chunk = unique_signal_ids[offset : offset + batch_size]
            outcomes.extend(
                await self._process_chunk(
                    signal_ids=chunk,
                    embedding_version=embedding_version,
                    provider=provider,
                    max_provider_attempts=max_provider_attempts,
                )
            )

        generated = sum(
            outcome.status is EmbeddingOutcomeStatus.GENERATED for outcome in outcomes
        )
        skipped = sum(
            outcome.status is EmbeddingOutcomeStatus.SKIPPED for outcome in outcomes
        )
        failed = sum(
            outcome.status is EmbeddingOutcomeStatus.FAILED for outcome in outcomes
        )
        summary = EmbeddingBatchSummary(
            requested=len(unique_signal_ids),
            generated=generated,
            skipped=skipped,
            failed=failed,
            outcomes=tuple(outcomes),
        )
        logger.info(
            "embedding_batch_complete",
            extra={
                "embedding_provider_key": provider.provider_key,
                "embedding_model_name": provider.model_name,
                "embedding_version": embedding_version,
                "embedding_dimensions": provider.dimensions,
                "embedding_batch_size": batch_size,
                "embedding_requested": summary.requested,
                "embedding_generated": summary.generated,
                "embedding_skipped": summary.skipped,
                "embedding_failed": summary.failed,
            },
        )
        return summary

    async def _process_chunk(
        self,
        *,
        signal_ids: list[UUID],
        embedding_version: str,
        provider: EmbeddingProvider,
        max_provider_attempts: int,
    ) -> list[EmbeddingBatchOutcome]:
        outcomes: list[EmbeddingBatchOutcome] = []
        pending: list[_PendingEmbedding] = []

        async with self.session.begin():
            existing = await self.embeddings.get_many(signal_ids, embedding_version)
            signals: dict[UUID, RawSignalRecord] = {}
            for signal_id in signal_ids:
                signal = await self.raw_signals.get(signal_id)
                if signal is not None:
                    signals[signal_id] = signal

            for signal_id in signal_ids:
                signal = signals.get(signal_id)
                if signal is None:
                    outcomes.append(
                        EmbeddingBatchOutcome(
                            signal_id=signal_id,
                            status=EmbeddingOutcomeStatus.FAILED,
                            code="RAW_SIGNAL_NOT_FOUND",
                        )
                    )
                    continue
                embedding_input = self.input_builder.build(signal)
                if embedding_input is None:
                    outcomes.append(
                        EmbeddingBatchOutcome(
                            signal_id=signal_id,
                            status=EmbeddingOutcomeStatus.SKIPPED,
                            code="NO_EMBEDDABLE_TEXT",
                        )
                    )
                    continue
                artifact = existing.get(signal_id)
                if artifact is not None:
                    if _artifact_matches(
                        artifact,
                        provider=provider,
                        embedding_input=embedding_input,
                    ):
                        outcomes.append(
                            EmbeddingBatchOutcome(
                                signal_id=signal_id,
                                status=EmbeddingOutcomeStatus.SKIPPED,
                                code="ALREADY_EMBEDDED",
                            )
                        )
                    else:
                        outcomes.append(
                            EmbeddingBatchOutcome(
                                signal_id=signal_id,
                                status=EmbeddingOutcomeStatus.FAILED,
                                code="EMBEDDING_VERSION_CONFLICT",
                            )
                        )
                    continue
                pending.append(_PendingEmbedding(signal=signal, input=embedding_input))

        if not pending:
            return outcomes

        request = EmbeddingRequest(
            embedding_version=embedding_version,
            input_schema_version=self.input_builder.input_schema_version,
            items=tuple(
                EmbeddingRequestItem(
                    signal_id=item.signal.id,
                    text=item.input.text,
                    input_hash=item.input.input_hash,
                )
                for item in pending
            ),
        )
        started = perf_counter()
        try:
            result = await self._call_provider(
                provider=provider,
                request=request,
                max_attempts=max_provider_attempts,
            )
            vectors = self._validate_result(
                provider=provider,
                request=request,
                result=result,
            )
        except EmbeddingProviderError as exc:
            outcomes.extend(
                EmbeddingBatchOutcome(
                    signal_id=item.signal.id,
                    status=EmbeddingOutcomeStatus.FAILED,
                    code="RETRYABLE_PROVIDER_FAILURE"
                    if exc.retryable
                    else "PROVIDER_FAILURE",
                    retryable=exc.retryable,
                )
                for item in pending
            )
            return outcomes
        except EmbeddingDimensionMismatchError:
            outcomes.extend(
                EmbeddingBatchOutcome(
                    signal_id=item.signal.id,
                    status=EmbeddingOutcomeStatus.FAILED,
                    code="DIMENSION_MISMATCH",
                )
                for item in pending
            )
            return outcomes
        except InvalidEmbeddingResponseError:
            outcomes.extend(
                EmbeddingBatchOutcome(
                    signal_id=item.signal.id,
                    status=EmbeddingOutcomeStatus.FAILED,
                    code="INVALID_PROVIDER_RESPONSE",
                )
                for item in pending
            )
            return outcomes
        finally:
            logger.info(
                "embedding_provider_call_complete",
                extra={
                    "embedding_provider_key": provider.provider_key,
                    "embedding_model_name": provider.model_name,
                    "embedding_version": embedding_version,
                    "embedding_dimensions": provider.dimensions,
                    "embedding_provider_batch_size": len(pending),
                    "embedding_latency_ms": round((perf_counter() - started) * 1000, 3),
                },
            )

        async with self.session.begin():
            for item, vector in zip(pending, vectors, strict=True):
                artifact, created = await self.embeddings.insert_idempotently(
                    signal_id=item.signal.id,
                    provider_key=provider.provider_key,
                    model_name=provider.model_name,
                    dimensions=provider.dimensions,
                    embedding_version=embedding_version,
                    input_schema_version=item.input.input_schema_version,
                    input_hash=item.input.input_hash,
                    embedding=vector,
                )
                if created:
                    outcomes.append(
                        EmbeddingBatchOutcome(
                            signal_id=item.signal.id,
                            status=EmbeddingOutcomeStatus.GENERATED,
                            code="GENERATED",
                        )
                    )
                elif _artifact_matches(
                    artifact,
                    provider=provider,
                    embedding_input=item.input,
                ):
                    outcomes.append(
                        EmbeddingBatchOutcome(
                            signal_id=item.signal.id,
                            status=EmbeddingOutcomeStatus.SKIPPED,
                            code="CONCURRENTLY_GENERATED",
                        )
                    )
                else:
                    outcomes.append(
                        EmbeddingBatchOutcome(
                            signal_id=item.signal.id,
                            status=EmbeddingOutcomeStatus.FAILED,
                            code="EMBEDDING_VERSION_CONFLICT",
                        )
                    )
        return outcomes

    async def _call_provider(
        self,
        *,
        provider: EmbeddingProvider,
        request: EmbeddingRequest,
        max_attempts: int,
    ) -> EmbeddingBatchResult:
        for attempt in range(1, max_attempts + 1):
            try:
                return await provider.embed(request)
            except EmbeddingProviderError as exc:
                if not exc.retryable or attempt >= max_attempts:
                    raise
            except (OSError, TimeoutError) as exc:
                if attempt >= max_attempts:
                    raise EmbeddingProviderError(
                        "Embedding Provider 网络调用失败",
                        retryable=True,
                    ) from exc
            except Exception as exc:
                raise EmbeddingProviderError(
                    "Embedding Provider 执行失败",
                    retryable=False,
                ) from exc
        raise RuntimeError("Embedding Provider 重试边界异常")

    @staticmethod
    def _validate_result(
        *,
        provider: EmbeddingProvider,
        request: EmbeddingRequest,
        result: EmbeddingBatchResult,
    ) -> list[list[float]]:
        if (
            result.provider_key != provider.provider_key
            or result.model_name != provider.model_name
            or result.embedding_version != request.embedding_version
        ):
            raise InvalidEmbeddingResponseError("Provider 返回元数据与请求不一致")
        if result.dimensions != provider.dimensions:
            raise EmbeddingDimensionMismatchError("Provider 返回 dimensions 与契约不一致")
        if len(result.vectors) != len(request.items):
            raise InvalidEmbeddingResponseError("Provider 返回向量数量与输入数量不一致")
        return [
            _validate_vector(vector, result.dimensions)
            for vector in result.vectors
        ]


class EmbeddingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.embeddings = SignalEmbeddingRepository(session)

    async def list_versions(self, signal_id: UUID) -> list[SignalEmbeddingRecord]:
        signal = await RawSignalRepository(self.session).get(signal_id)
        if signal is None:
            raise ResourceNotFoundError("原始信号不存在")
        return await self.embeddings.list_versions(signal_id)

    async def process_signals(
        self,
        *,
        signal_ids: list[UUID],
        embedding_version: str,
        provider: EmbeddingProvider,
        batch_size: int = 32,
        max_provider_attempts: int = 1,
    ) -> EmbeddingBatchSummary:
        return await EmbeddingBatchProcessor(self.session).process(
            signal_ids=signal_ids,
            embedding_version=embedding_version,
            provider=provider,
            batch_size=batch_size,
            max_provider_attempts=max_provider_attempts,
        )


class SignalSimilarityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.embeddings = SignalEmbeddingRepository(session)

    async def recall(
        self,
        *,
        signal_id: UUID,
        embedding_version: str,
        top_k: int,
        min_similarity: float | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> list[SimilarityCandidate]:
        if top_k < 1 or top_k > 100:
            raise BusinessValidationError("top_k 必须在 1 到 100 之间")
        if min_similarity is not None and (
            not math.isfinite(min_similarity) or not -1 <= min_similarity <= 1
        ):
            raise BusinessValidationError("min_similarity 必须是 -1 到 1 之间的有限数值")
        for value in (time_from, time_to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise BusinessValidationError("Recall 时间范围必须使用 timezone-aware 时间")
        if time_from is not None and time_to is not None and time_from > time_to:
            raise BusinessValidationError("time_from 不能晚于 time_to")

        target = await self.embeddings.get(signal_id, embedding_version)
        if target is None:
            raise ResourceNotFoundError("指定 Signal 的 embedding_version 不存在")
        _validate_vector(tuple(float(value) for value in target.embedding), target.dimensions)
        return await self.embeddings.exact_cosine_recall(
            target=target,
            top_k=top_k,
            min_similarity=min_similarity,
            time_from=time_from,
            time_to=time_to,
        )
