from __future__ import annotations

from uuid import UUID

from packages.connector_management.exceptions import (
    BusinessValidationError,
    ConflictError,
    ConnectorManagementError,
)


class EvidenceValidationError(BusinessValidationError):
    code = "evidence_validation_error"


class EventMergedError(ConflictError):
    code = "EVENT_MERGED"

    def __init__(self, target_event_id: UUID) -> None:
        super().__init__(
            "已合并事件不能新增或修改 Evidence",
            details={"target_event_id": str(target_event_id)},
        )


class EvidenceSourceConflictError(ConflictError):
    code = "EVIDENCE_SOURCE_ROLE_CONFLICT"


class EvidenceAIError(ConnectorManagementError):
    status_code = 503
    code = "EVIDENCE_AI_ERROR"

    def __init__(self, ai_error_code: str, message: str) -> None:
        super().__init__(
            "Evidence AI extraction 暂不可用",
            details={"ai_error_code": ai_error_code, "message": message[:300]},
        )
