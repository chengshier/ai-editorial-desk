"""Import all ORM models so Base.metadata and Alembic see a complete schema."""

from packages.database.models.audit import ConfigurationChangeLog
from packages.database.models.connectors import ConnectorDefinition, ConnectorInstance, PlatformAccount
from packages.database.models.risk import PlatformRiskEvent
from packages.database.models.runs import ConnectorCheckpoint, ConnectorRun, ConnectorRunStatus, ConnectorRunTriggerType
from packages.database.models.scheduling import (
    CollectionSchedule,
    CollectionScheduleTrigger,
    ConnectorValidationRecord,
    ConnectorValidationStatus,
    SchedulerInstance,
    ScheduleTriggerStatus,
    ScheduleType,
)
from packages.database.models.signals import (
    CollectionBudget,
    CollectionBudgetUsage,
    RawSignalCommentRecord,
    RawSignalRecord,
    Source,
)

__all__ = [
    "CollectionBudget",
    "CollectionBudgetUsage",
    "CollectionSchedule",
    "CollectionScheduleTrigger",
    "ConfigurationChangeLog",
    "ConnectorCheckpoint",
    "ConnectorDefinition",
    "ConnectorInstance",
    "ConnectorRun",
    "ConnectorRunStatus",
    "ConnectorRunTriggerType",
    "ConnectorValidationRecord",
    "ConnectorValidationStatus",
    "PlatformAccount",
    "PlatformRiskEvent",
    "RawSignalCommentRecord",
    "RawSignalRecord",
    "ScheduleTriggerStatus",
    "SchedulerInstance",
    "ScheduleType",
    "Source",
]
