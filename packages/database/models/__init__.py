"""Import all ORM models so Base.metadata and Alembic see a complete schema."""

from packages.database.models.audit import ConfigurationChangeLog
from packages.database.models.clustering import (
    MatchDecisionType,
    MatchOverrideDecision,
    MatchPrimaryMethod,
    SignalEventSuppressionRecord,
    SignalFingerprintRecord,
    SignalMatchDecisionRecord,
    SignalMatchOverrideRecord,
)
from packages.database.models.connectors import (
    ConnectorDefinition,
    ConnectorInstance,
    PlatformAccount,
)
from packages.database.models.embeddings import SignalEmbeddingRecord
from packages.database.models.events import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
)
from packages.database.models.processing import (
    ClusteringProcessingMode,
    ClusteringProcessingRunRecord,
    ClusteringProcessingStatus,
    EventAssignmentAction,
    EventAssignmentRecord,
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
    "ClusteringProcessingMode",
    "ClusteringProcessingRunRecord",
    "ClusteringProcessingStatus",
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
    "EventAssignmentAction",
    "EventAssignmentRecord",
    "EventRecord",
    "EventSignalAttachedBy",
    "EventSignalRecord",
    "EventSignalRelation",
    "EventStatus",
    "MatchDecisionType",
    "MatchOverrideDecision",
    "MatchPrimaryMethod",
    "PlatformAccount",
    "PlatformRiskEvent",
    "RawSignalCommentRecord",
    "RawSignalRecord",
    "ScheduleTriggerStatus",
    "SchedulerInstance",
    "ScheduleType",
    "SignalEmbeddingRecord",
    "SignalEventSuppressionRecord",
    "SignalFingerprintRecord",
    "SignalMatchDecisionRecord",
    "SignalMatchOverrideRecord",
    "Source",
]
