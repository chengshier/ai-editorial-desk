from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.database.models import (
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunStatus,
    PlatformAccount,
    PlatformRiskEvent,
)
from packages.risk_guard.models import AccountStatus, RiskAction


class ConnectorDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_type: str
    platform: str
    display_name: str
    capabilities: dict[str, Any]
    config_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    implementation_version: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class ConnectorDefinitionPage(BaseModel):
    items: list[ConnectorDefinitionResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class ConnectorInstanceCreate(BaseModel):
    definition_id: UUID
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_config: dict[str, Any] = Field(default_factory=dict)


class ConnectorInstanceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    schedule_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "ConnectorInstanceUpdate":
        for field_name in ("name", "config", "schedule_config"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ConnectorInstanceResponse(BaseModel):
    id: UUID
    definition_id: UUID
    connector_type: str
    platform: str
    name: str
    enabled: bool
    status: str
    config: dict[str, Any]
    schedule_config: dict[str, Any]
    credential_configured: bool
    config_version: int
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, instance: ConnectorInstance) -> "ConnectorInstanceResponse":
        return cls(
            id=instance.id,
            definition_id=instance.definition_id,
            connector_type=instance.definition.connector_type,
            platform=instance.definition.platform,
            name=instance.name,
            enabled=instance.enabled,
            status=instance.status,
            config=instance.config,
            schedule_config=instance.schedule_config,
            credential_configured=bool(instance.credential_ref),
            config_version=instance.config_version,
            last_success_at=instance.last_success_at,
            last_error_at=instance.last_error_at,
            last_error_code=instance.last_error_code,
            last_error_message=instance.last_error_message,
            updated_by=instance.updated_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )


class ConnectorInstancePage(BaseModel):
    items: list[ConnectorInstanceResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class PlatformAccountCreate(BaseModel):
    connector_instance_id: UUID
    platform: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    account_identifier: str = Field(min_length=1, max_length=255)
    credential_ref: str | None = Field(default=None, max_length=500)
    browser_profile_ref: str | None = Field(default=None, max_length=500)


class PlatformAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    credential_ref: str | None = Field(default=None, max_length=500)
    browser_profile_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def reject_null_display_name(self) -> "PlatformAccountUpdate":
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null")
        return self


class PlatformAccountTransition(BaseModel):
    target_status: AccountStatus
    reason: str = Field(min_length=3, max_length=2000)
    cooldown_until: datetime | None = None
    override_cooldown: bool = False


class PlatformAccountResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    platform: str
    display_name: str
    account_identifier: str
    credential_configured: bool
    browser_profile_configured: bool
    status: AccountStatus
    risk_level: str
    last_success_at: datetime | None
    last_warning_at: datetime | None
    last_warning_code: str | None
    consecutive_failures: int
    cooldown_until: datetime | None
    manual_review_required: bool
    daily_request_count: int
    daily_item_count: int
    daily_comment_count: int
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, account: PlatformAccount) -> "PlatformAccountResponse":
        return cls(
            id=account.id,
            connector_instance_id=account.connector_instance_id,
            platform=account.platform,
            display_name=account.display_name,
            account_identifier=account.account_identifier,
            credential_configured=bool(account.credential_ref),
            browser_profile_configured=bool(account.browser_profile_ref),
            status=account.status,
            risk_level=account.risk_level,
            last_success_at=account.last_success_at,
            last_warning_at=account.last_warning_at,
            last_warning_code=account.last_warning_code,
            consecutive_failures=account.consecutive_failures,
            cooldown_until=account.cooldown_until,
            manual_review_required=account.manual_review_required,
            daily_request_count=account.daily_request_count,
            daily_item_count=account.daily_item_count,
            daily_comment_count=account.daily_comment_count,
            updated_by=account.updated_by,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class PlatformAccountPage(BaseModel):
    items: list[PlatformAccountResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class ConnectorRunResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    platform_account_id: UUID | None
    mode: str
    status: ConnectorRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    requested_limit: int
    collected_count: int
    inserted_count: int
    duplicate_count: int
    error_code: str | None
    error_message: str | None
    retry_count: int
    checkpoint_before: dict[str, Any] | None
    checkpoint_after: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_orm_model(cls, run: ConnectorRun) -> "ConnectorRunResponse":
        return cls(
            id=run.id,
            connector_instance_id=run.connector_instance_id,
            platform_account_id=run.platform_account_id,
            mode=run.mode,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            requested_limit=run.requested_limit,
            collected_count=run.collected_count,
            inserted_count=run.inserted_count,
            duplicate_count=run.duplicate_count,
            error_code=run.error_code,
            error_message=run.error_message,
            retry_count=run.retry_count,
            checkpoint_before=run.checkpoint_before,
            checkpoint_after=run.checkpoint_after,
            metadata=run.run_metadata,
            created_at=run.created_at,
        )


class ConnectorRunPage(BaseModel):
    items: list[ConnectorRunResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class PlatformRiskEventResolve(BaseModel):
    resolution_note: str = Field(min_length=3, max_length=4000)


class PlatformRiskEventResponse(BaseModel):
    id: UUID
    connector_instance_id: UUID
    platform_account_id: UUID | None
    connector_run_id: UUID | None
    platform: str
    risk_type: str
    risk_level: str
    raw_error_code: str | None
    standard_error_code: str | None
    message: str
    action_taken: RiskAction
    retryable: bool
    request_context: dict[str, Any]
    response_context: dict[str, Any]
    occurred_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    manual_review_required: bool
    created_at: datetime

    @classmethod
    def from_orm_model(cls, event: PlatformRiskEvent) -> "PlatformRiskEventResponse":
        return cls(
            id=event.id,
            connector_instance_id=event.connector_instance_id,
            platform_account_id=event.platform_account_id,
            connector_run_id=event.connector_run_id,
            platform=event.platform,
            risk_type=event.risk_type,
            risk_level=event.risk_level,
            raw_error_code=event.raw_error_code,
            standard_error_code=event.standard_error_code,
            message=event.message,
            action_taken=event.action_taken,
            retryable=event.retryable,
            request_context=event.request_context,
            response_context=event.response_context,
            occurred_at=event.occurred_at,
            resolved_at=event.resolved_at,
            resolved_by=event.resolved_by,
            resolution_note=event.resolution_note,
            manual_review_required=event.manual_review_required,
            created_at=event.created_at,
        )


class PlatformRiskEventPage(BaseModel):
    items: list[PlatformRiskEventResponse]
    page: int
    page_size: int
    total: int
    has_next: bool
