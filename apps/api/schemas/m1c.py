from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.connectors.registry import ConnectorRegistry
from packages.database.models import (
    ConnectorDefinition,
    ConnectorRun,
    ConnectorRunStatus,
    RawSignalRecord,
)


class ConnectorDefinitionRuntimeResponse(BaseModel):
    id: UUID
    connector_type: str
    platform: str
    display_name: str
    capabilities: dict[str, Any]
    config_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    implementation_version: str
    is_enabled: bool
    registered: bool
    implemented: bool
    enabled: bool
    validated: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(
        cls,
        definition: ConnectorDefinition,
        registry: ConnectorRegistry,
    ) -> ConnectorDefinitionRuntimeResponse:
        return cls(
            id=definition.id,
            connector_type=definition.connector_type,
            platform=definition.platform,
            display_name=definition.display_name,
            capabilities=definition.capabilities,
            config_schema=definition.config_schema,
            ui_schema=definition.ui_schema,
            implementation_version=definition.implementation_version,
            is_enabled=definition.is_enabled,
            registered=True,
            implemented=registry.has(definition.connector_type),
            enabled=definition.is_enabled,
            validated=False,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
        )


class ConnectorDefinitionRuntimePage(BaseModel):
    items: list[ConnectorDefinitionRuntimeResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class ConnectorRunRuntimeResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    source_id: UUID | None
    platform_account_id: UUID | None
    mode: str
    status: ConnectorRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    requested_limit: int
    collected_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    error_message: str | None
    retry_count: int
    checkpoint_before: dict[str, Any] | None
    checkpoint_after: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_orm_model(cls, run: ConnectorRun) -> ConnectorRunRuntimeResponse:
        return cls(
            id=run.id,
            connector_instance_id=run.connector_instance_id,
            source_id=run.source_id,
            platform_account_id=run.platform_account_id,
            mode=run.mode,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            requested_limit=run.requested_limit,
            collected_count=run.collected_count,
            inserted_count=run.inserted_count,
            duplicate_count=run.duplicate_count,
            failed_count=run.failed_count,
            error_code=run.error_code,
            error_message=run.error_message,
            retry_count=run.retry_count,
            checkpoint_before=run.checkpoint_before,
            checkpoint_after=run.checkpoint_after,
            metadata=run.run_metadata,
            created_at=run.created_at,
        )


class ConnectorRunRuntimePage(BaseModel):
    items: list[ConnectorRunRuntimeResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class SourceCreate(BaseModel):
    connector_instance_id: UUID
    name: str = Field(min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=100)
    mode: str = Field(min_length=1, max_length=100)
    scope_key: str = Field(min_length=1, max_length=500)
    external_ref: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    external_ref: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_invalid_nulls(self) -> SourceUpdate:
        for name in ("name", "config", "enabled"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_instance_id: UUID
    name: str
    source_type: str
    mode: str
    scope_key: str
    external_ref: str | None
    config: dict[str, Any]
    enabled: bool
    status: str
    last_collected_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class SourcePage(BaseModel):
    items: list[SourceResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class RawSignalResponse(BaseModel):
    id: UUID
    source_id: UUID
    connector_instance_id: UUID
    connector_run_id: UUID | None
    platform: str
    external_id: str | None
    original_url: str
    canonical_url: str
    title: str | None
    text: str | None
    author_id: str | None
    author_name: str | None
    published_at: datetime | None
    collected_at: datetime
    metrics: dict[str, int | float]
    media: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    language: str | None
    content_hash: str
    idempotency_key: str
    created_at: datetime

    @classmethod
    def from_orm_model(cls, signal: RawSignalRecord) -> RawSignalResponse:
        return cls.model_validate(signal, from_attributes=True)


class RawSignalPage(BaseModel):
    items: list[RawSignalResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class CollectionBudgetCreate(BaseModel):
    scope_type: Literal["platform", "account", "connector", "task"]
    scope_key: str = Field(min_length=1, max_length=500)
    max_runs_per_day: int = Field(ge=1, le=100000)
    max_items_per_run: int = Field(ge=1, le=10000)
    max_items_per_day: int = Field(ge=1, le=10000000)
    max_comments_per_run: int = Field(default=0, ge=0, le=100000)
    max_comments_per_day: int = Field(default=0, ge=0, le=10000000)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    enabled: bool = True


class CollectionBudgetUpdate(BaseModel):
    max_runs_per_day: int | None = Field(default=None, ge=1, le=100000)
    max_items_per_run: int | None = Field(default=None, ge=1, le=10000)
    max_items_per_day: int | None = Field(default=None, ge=1, le=10000000)
    max_comments_per_run: int | None = Field(default=None, ge=0, le=100000)
    max_comments_per_day: int | None = Field(default=None, ge=0, le=10000000)
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> CollectionBudgetUpdate:
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CollectionBudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope_type: str
    scope_key: str
    max_runs_per_day: int
    max_items_per_run: int
    max_items_per_day: int
    max_comments_per_run: int
    max_comments_per_day: int
    max_concurrency: int
    timezone: str
    enabled: bool
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class CollectionBudgetPage(BaseModel):
    items: list[CollectionBudgetResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class TestRunRequest(BaseModel):
    source_id: UUID
    requested_limit: int = Field(ge=1, le=100)
    expected_checkpoint_version: int | None = Field(default=None, ge=1)
    platform_account_id: UUID | None = None
    dry_run: bool = False


class TestRunResponse(BaseModel):
    run_id: UUID
    status: ConnectorRunStatus
    signal_ids: list[UUID]
    collected_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    fetch_status: str | None


class ManualImportRequest(BaseModel):
    connector_instance_id: UUID
    url: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=500000)
    note: str | None = Field(default=None, max_length=4000)
    fetch_metadata: bool = True


class ManualImportResponse(BaseModel):
    run_id: UUID
    signal_id: UUID
    duplicate: bool
    normalized_url: str
    fetch_status: str | None
