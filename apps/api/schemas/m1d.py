from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.database.models import (
    ConnectorCheckpoint,
    ConnectorRun,
    ConnectorRunStatus,
    ConnectorRunTriggerType,
    ConnectorValidationRecord,
    ConnectorValidationStatus,
    ScheduleType,
)


class ScheduleCreate(BaseModel):
    connector_instance_id: UUID
    source_id: UUID
    platform_account_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    schedule_type: ScheduleType
    interval_seconds: int | None = Field(default=None, ge=300)
    cron_expression: str | None = Field(default=None, max_length=200)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    requested_limit: int = Field(default=20, ge=1, le=100)


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    schedule_type: ScheduleType | None = None
    interval_seconds: int | None = Field(default=None, ge=300)
    cron_expression: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    requested_limit: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def reject_invalid_nulls(self) -> ScheduleUpdate:
        for field in ("name", "enabled", "schedule_type", "timezone", "requested_limit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_instance_id: UUID
    source_id: UUID
    platform_account_id: UUID | None
    name: str
    enabled: bool
    schedule_type: ScheduleType
    interval_seconds: int | None
    cron_expression: str | None
    timezone: str
    requested_limit: int
    next_run_at: datetime
    last_triggered_at: datetime | None
    last_run_id: UUID | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    consecutive_failures: int
    paused_reason: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class SchedulePage(BaseModel):
    items: list[ScheduleResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class PauseScheduleRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RunNowRequest(BaseModel):
    requested_limit: int | None = Field(default=None, ge=1, le=100)


class RunActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class RunDebugResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    source_id: UUID | None
    platform_account_id: UUID | None
    parent_run_id: UUID | None
    trigger_type: ConnectorRunTriggerType
    mode: str
    status: ConnectorRunStatus
    started_at: datetime | None
    progress_updated_at: datetime | None
    finished_at: datetime | None
    requested_limit: int
    collected_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    retry_count: int
    error_code: str | None
    error_message: str | None
    checkpoint_before: dict[str, Any] | None
    checkpoint_after: dict[str, Any] | None
    budget: Any
    risk_action: Any
    metadata: dict[str, Any]
    latency_seconds: float | None
    created_at: datetime

    @classmethod
    def from_orm_model(cls, run: ConnectorRun) -> RunDebugResponse:
        latency = None
        if run.started_at is not None:
            end = run.finished_at or run.progress_updated_at
            if end is not None:
                latency = max((end - run.started_at).total_seconds(), 0.0)
        return cls(
            id=run.id,
            connector_instance_id=run.connector_instance_id,
            source_id=run.source_id,
            platform_account_id=run.platform_account_id,
            parent_run_id=run.parent_run_id,
            trigger_type=run.trigger_type,
            mode=run.mode,
            status=run.status,
            started_at=run.started_at,
            progress_updated_at=run.progress_updated_at,
            finished_at=run.finished_at,
            requested_limit=run.requested_limit,
            collected_count=run.collected_count,
            inserted_count=run.inserted_count,
            duplicate_count=run.duplicate_count,
            failed_count=run.failed_count,
            retry_count=run.retry_count,
            error_code=run.error_code,
            error_message=run.error_message,
            checkpoint_before=run.checkpoint_before,
            checkpoint_after=run.checkpoint_after,
            budget=run.run_metadata.get("budget"),
            risk_action=run.run_metadata.get("risk_action"),
            metadata=run.run_metadata,
            latency_seconds=latency,
            created_at=run.created_at,
        )


class RunDebugPage(BaseModel):
    items: list[RunDebugResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class CheckpointResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    source_id: UUID | None
    platform_account_id: UUID | None
    mode: str
    scope_key: str
    cursor: dict[str, Any] | None
    watermark: str | None
    last_external_id: str | None
    last_published_at: datetime | None
    checkpoint_data: dict[str, Any]
    version: int
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, checkpoint: ConnectorCheckpoint) -> CheckpointResponse:
        return cls.model_validate(checkpoint, from_attributes=True)


class CheckpointPage(BaseModel):
    items: list[CheckpointResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class CheckpointResetRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class ValidationCreate(BaseModel):
    connector_type: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=100)
    implementation_version: str = Field(min_length=1, max_length=100)
    environment: str = Field(default="local", min_length=1, max_length=100)
    status: ConnectorValidationStatus
    notes: str | None = Field(default=None, max_length=4000)
    safe_evidence: dict[str, Any] = Field(default_factory=dict)
    real_smoke_test: bool = False


class ValidationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_type: str
    platform: str
    implementation_version: str
    environment: str
    status: ConnectorValidationStatus
    validated_at: datetime | None
    validated_by: str | None
    notes: str | None
    safe_evidence: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_orm_model(cls, record: ConnectorValidationRecord) -> ValidationResponse:
        return cls.model_validate(record, from_attributes=True)


class ValidationPage(BaseModel):
    items: list[ValidationResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class SchedulerStatusResponse(BaseModel):
    scheduler_instance: str | None
    started_at: datetime | None
    last_heartbeat: datetime | None
    active_leases: int
    due_schedule_count: int
    recent_trigger_failures: int
