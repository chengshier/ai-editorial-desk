from packages.connector_management.exceptions import ConnectorManagementError


class CollectorRuntimeError(ConnectorManagementError):
    """Safe collector runtime failure rendered by the common API handler."""

    status_code = 409
    code = "collector_runtime_error"


class PreflightRejectedError(CollectorRuntimeError):
    code = "collector_preflight_rejected"


class ConnectorImplementationUnavailableError(PreflightRejectedError):
    code = "connector_implementation_unavailable"


class RunClaimConflictError(CollectorRuntimeError):
    code = "run_claim_conflict"


class BudgetExceededError(PreflightRejectedError):
    code = "collection_budget_exceeded"
