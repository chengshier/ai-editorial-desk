from __future__ import annotations

from uuid import UUID

from packages.connector_management.exceptions import BusinessValidationError, ConflictError


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
