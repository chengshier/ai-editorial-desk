from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class TriggerType(StrEnum):
    MANUAL = "manual"
    TEST = "test"
    SCHEDULED = "scheduled"
    RETRY = "retry"


@dataclass(slots=True, frozen=True)
class CollectionTask:
    task_id: UUID
    connector_instance_id: UUID
    source_id: UUID
    platform_account_id: UUID | None
    mode: str
    requested_limit: int
    checkpoint_version: int | None
    trigger_type: TriggerType
    triggered_by: str
    created_at: datetime
    dry_run: bool = False
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            **payload,
            "task_id": str(self.task_id),
            "connector_instance_id": str(self.connector_instance_id),
            "source_id": str(self.source_id),
            "platform_account_id": (
                str(self.platform_account_id)
                if self.platform_account_id is not None
                else None
            ),
            "trigger_type": self.trigger_type.value,
            "created_at": self.created_at.isoformat(),
        }
