from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from packages.database.models import (
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRunStatus,
    PlatformAccount,
    Source,
)

MAX_TEST_RUN_LIMIT = 100
INGESTION_BATCH_SIZE = 50


@dataclass(slots=True, frozen=True)
class RuntimeResult:
    run_id: UUID
    status: ConnectorRunStatus
    signal_ids: tuple[UUID, ...]
    collected_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    fetch_status: str | None = None


@dataclass(slots=True, frozen=True)
class PreflightContext:
    instance: ConnectorInstance
    definition: ConnectorDefinition
    source: Source
    account: PlatformAccount | None
    runtime_context: object | None = None
