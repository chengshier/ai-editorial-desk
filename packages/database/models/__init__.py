"""Import all ORM models so Base.metadata and Alembic see a complete schema."""

from packages.database.models.audit import ConfigurationChangeLog
from packages.database.models.connectors import (
    ConnectorDefinition,
    ConnectorInstance,
    PlatformAccount,
)
from packages.database.models.risk import PlatformRiskEvent
from packages.database.models.runs import ConnectorCheckpoint, ConnectorRun, ConnectorRunStatus
from packages.database.models.signals import (
    CollectionBudget,
    CollectionBudgetUsage,
    RawSignalRecord,
    Source,
)

__all__ = [
    "CollectionBudget",
    "CollectionBudgetUsage",
    "ConfigurationChangeLog",
    "ConnectorCheckpoint",
    "ConnectorDefinition",
    "ConnectorInstance",
    "ConnectorRun",
    "ConnectorRunStatus",
    "PlatformAccount",
    "PlatformRiskEvent",
    "RawSignalRecord",
    "Source",
]
