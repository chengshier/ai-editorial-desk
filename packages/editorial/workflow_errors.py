from __future__ import annotations

from uuid import UUID

from packages.connector_management.exceptions import BusinessValidationError, ConflictError


class CandidateValidationError(BusinessValidationError):
    code = "CANDIDATE_VALIDATION_ERROR"


class StaleCandidateContextError(ConflictError):
    code = "STALE_CANDIDATE_CONTEXT"


class CandidateRunStaleError(ConflictError):
    code = "CANDIDATE_RUN_STALE"


class EditorialDecisionConflictError(ConflictError):
    code = "EDITORIAL_DECISION_CONFLICT"


class RiskAcknowledgementRequiredError(ConflictError):
    code = "RISK_ACKNOWLEDGEMENT_REQUIRED"


class WorkflowEventMergedError(ConflictError):
    code = "EVENT_MERGED"

    def __init__(self, target_event_id: UUID) -> None:
        super().__init__(
            "已合并 source Event 不能基于旧候选创建新的 Editorial Decision",
            details={"target_event_id": str(target_event_id)},
        )
