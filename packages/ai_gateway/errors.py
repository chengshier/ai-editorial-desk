from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from packages.ai_gateway.domain import AIUsage


class AIErrorCode(StrEnum):
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"
    CREDENTIAL_NOT_CONFIGURED = "CREDENTIAL_NOT_CONFIGURED"
    ROUTE_NOT_CONFIGURED = "ROUTE_NOT_CONFIGURED"
    CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    MODEL_DISABLED = "MODEL_DISABLED"
    USAGE_UNKNOWN = "USAGE_UNKNOWN"


class AIGatewayError(RuntimeError):
    def __init__(
        self,
        code: AIErrorCode,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        provider_error_detail: Mapping[str, str] | None = None,
        provider_response_detail: Mapping[str, object] | None = None,
        provider_usage: AIUsage | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.provider_error_detail = (
            dict(provider_error_detail) if provider_error_detail is not None else None
        )
        self.provider_response_detail = (
            dict(provider_response_detail) if provider_response_detail is not None else None
        )
        self.provider_usage = provider_usage
        self.provider_request_id = provider_request_id


def provider_error_metadata(error: AIGatewayError) -> dict[str, object]:
    """Return already-sanitized provider diagnostic fields for invocation audit metadata."""

    metadata: dict[str, object] = {}
    if error.provider_error_detail is not None:
        metadata["provider_error_detail"] = dict(error.provider_error_detail)
    if error.provider_response_detail is not None:
        metadata["provider_response_detail"] = dict(error.provider_response_detail)
    return metadata


class AIProviderError(AIGatewayError):
    """Normalized provider error safe for routing and audit decisions."""


class AIBudgetExceededError(AIGatewayError):
    def __init__(self, message: str) -> None:
        super().__init__(AIErrorCode.BUDGET_EXCEEDED, message)


class AICredentialError(AIGatewayError):
    def __init__(self, message: str = "Provider credential 未配置") -> None:
        super().__init__(AIErrorCode.CREDENTIAL_NOT_CONFIGURED, message)
