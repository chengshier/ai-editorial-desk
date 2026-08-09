from __future__ import annotations

from uuid import UUID

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ConnectorManagementError,
)


class TrendValidationError(BusinessValidationError):
    code = "TREND_VALIDATION_ERROR"


class EditorialValidationError(BusinessValidationError):
    code = "EDITORIAL_VALIDATION_ERROR"


class EditorialRiskConflictError(ConflictError):
    code = "EDITORIAL_RISK_EVIDENCE_CONFLICT"


class EditorialEventMergedError(ConflictError):
    code = "EVENT_MERGED"

    def __init__(self, target_event_id: UUID) -> None:
        super().__init__(
            "已合并 source Event 不能生成新的 Trend 或 Editorial Score",
            details={"target_event_id": str(target_event_id)},
        )


class EditorialAIError(ConnectorManagementError):
    status_code = 503
    code = "EDITORIAL_AI_ERROR"

    def __init__(self, ai_error_code: str, message: str) -> None:
        super().__init__(
            "Editorial AI scoring 暂不可用",
            details={"ai_error_code": ai_error_code, "message": message[:300]},
        )
