class DatabaseError(RuntimeError):
    """Base exception for main-system database failures."""


class DatabaseUnavailableError(DatabaseError):
    """Raised when the database cannot satisfy a bounded readiness check."""


class DatabaseOperationError(DatabaseError):
    """Raised when a SQLAlchemy operation fails inside a managed session."""
