from __future__ import annotations

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ConnectorManagementError,
)


class EmbeddingError(ConnectorManagementError):
    code = "embedding_error"


class NoEmbeddableTextError(BusinessValidationError):
    code = "no_embeddable_text"


class EmbeddingVersionConflictError(ConflictError):
    code = "embedding_version_conflict"


class InvalidEmbeddingResponseError(BusinessValidationError):
    code = "invalid_embedding_response"


class EmbeddingDimensionMismatchError(InvalidEmbeddingResponseError):
    code = "embedding_dimension_mismatch"


class EmbeddingProviderError(EmbeddingError):
    code = "embedding_provider_error"
    status_code = 503

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message, details={"retryable": retryable})
        self.retryable = retryable
