"""M3-B versioned Signal Embedding and exact similarity recall."""

from packages.embeddings.input_builder import (
    SIGNAL_TEXT_INPUT_SCHEMA_VERSION,
    EmbeddingInput,
    EmbeddingInputBuilder,
)
from packages.embeddings.providers import (
    EmbeddingBatchResult,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingRequestItem,
)
from packages.embeddings.repositories import SignalEmbeddingRepository, SimilarityCandidate
from packages.embeddings.services import (
    EmbeddingBatchOutcome,
    EmbeddingBatchProcessor,
    EmbeddingBatchSummary,
    EmbeddingOutcomeStatus,
    EmbeddingService,
    SignalSimilarityService,
)

__all__ = [
    "SIGNAL_TEXT_INPUT_SCHEMA_VERSION",
    "EmbeddingBatchOutcome",
    "EmbeddingBatchProcessor",
    "EmbeddingBatchResult",
    "EmbeddingBatchSummary",
    "EmbeddingInput",
    "EmbeddingInputBuilder",
    "EmbeddingOutcomeStatus",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingRequestItem",
    "EmbeddingService",
    "SignalEmbeddingRepository",
    "SignalSimilarityService",
    "SimilarityCandidate",
]
