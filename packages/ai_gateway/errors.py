from __future__ import annotations

from enum import StrEnum


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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class AIProviderError(AIGatewayError):
    """Normalized provider error safe for routing and audit decisions."""


class AIBudgetExceededError(AIGatewayError):
    def __init__(self, message: str) -> None:
        super().__init__(AIErrorCode.BUDGET_EXCEEDED, message)


class AICredentialError(AIGatewayError):
    def __init__(self, message: str = "Provider credential 未配置") -> None:
        super().__init__(AIErrorCode.CREDENTIAL_NOT_CONFIGURED, message)
