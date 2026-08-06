from typing import Any


class ConnectorManagementError(RuntimeError):
    """Safe application error that can be rendered without internal details."""

    status_code = 400
    code = "connector_management_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AuthorizationError(ConnectorManagementError):
    status_code = 401
    code = "admin_auth_failed"


class ActorRequiredError(ConnectorManagementError):
    status_code = 422
    code = "actor_required"


class ResourceNotFoundError(ConnectorManagementError):
    status_code = 404
    code = "resource_not_found"


class ConflictError(ConnectorManagementError):
    status_code = 409
    code = "resource_conflict"


class InvalidStateTransitionError(ConflictError):
    code = "invalid_state_transition"


class VersionConflictError(ConflictError):
    code = "version_conflict"


class BusinessValidationError(ConnectorManagementError):
    status_code = 400
    code = "business_validation_error"


class SchemaValidationError(ConnectorManagementError):
    status_code = 422
    code = "schema_validation_error"


class DefinitionSyncError(RuntimeError):
    """Raised by the internal manifest synchronization command."""
