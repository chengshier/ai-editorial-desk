"""Import all ORM models so Base.metadata and Alembic see a complete schema."""

from packages.database.models.audit import ConfigurationChangeLog
from packages.database.models.connectors import (
    ConnectorDefinition,
    ConnectorInstance,
    PlatformAccount,
)
from packages.database.models.risk import PlatformRiskEvent
from packages.database.models.runs import (
    ConnectorCheckpoint,
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunTriggerType,
)
from packages.database.models.scheduling import (
    CollectionSchedule,
    CollectionScheduleTrigger,
    ConnectorValidationRecord,
    ConnectorValidationStatus,
    ScheduleTriggerStatus,
    SchedulerInstance,
    ScheduleType,
)
from packages.database.models.signals import (
    CollectionBudget,
    CollectionBudgetUsage,
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
    "RawSignalRecord",
    "ScheduleTriggerStatus",
    "SchedulerInstance",
    "ScheduleType",
    "Source",
]
