class CollectorRuntimeError(RuntimeError):
    """Safe collector runtime failure."""


class PreflightRejectedError(CollectorRuntimeError):
    pass


class ConnectorImplementationUnavailableError(PreflightRejectedError):
    pass


class RunClaimConflictError(CollectorRuntimeError):
    pass


class BudgetExceededError(PreflightRejectedError):
    pass
