from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIProviderCreate(BaseModel):
    provider_key: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    provider_type: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=1000)
    credential_ref: str | None = Field(default=None, max_length=500)
    enabled: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_concurrency: int = Field(default=4, ge=1, le=100)
    retry_limit: int = Field(default=1, ge=0, le=3)
    config: dict[str, Any] = Field(default_factory=dict)


class AIProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=1, max_length=1000)
    replace_credential_ref: str | None = Field(default=None, max_length=500)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    retry_limit: int | None = Field(default=None, ge=0, le=3)
    config: dict[str, Any] | None = None


class AIProviderResponse(BaseModel):
    id: UUID
    provider_key: str
    display_name: str
    provider_type: str
    base_url: str
    credential_configured: bool
    credential_ref_masked: str | None
    enabled: bool
    validation_status: str
    last_validated_at: datetime | None
    timeout_seconds: int
    max_concurrency: int
    retry_limit: int
    config: dict[str, Any]
    model_count: int = 0
    last_invocation_at: datetime | None = None
    error_rate: float | None = None
    created_at: datetime
    updated_at: datetime


class AIProviderPage(BaseModel):
    items: list[AIProviderResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class AIModelCreate(BaseModel):
    provider_id: UUID
    model_key: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=255)
    capabilities: list[str] = Field(min_length=1)
    enabled: bool = False
    context_window: int | None = Field(default=None, gt=0)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    embedding_price_per_million: Decimal | None = Field(default=None, ge=0)
    pricing_version: str = Field(default="unpriced-v1", min_length=1, max_length=100)
    dimensions: int | None = Field(default=None, gt=0)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class AIModelUpdate(BaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=255)
    capabilities: list[str] | None = None
    context_window: int | None = Field(default=None, gt=0)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    embedding_price_per_million: Decimal | None = Field(default=None, ge=0)
    pricing_version: str | None = Field(default=None, min_length=1, max_length=100)
    dimensions: int | None = Field(default=None, gt=0)
    config: dict[str, Any] | None = None


class AIModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    model_key: str
    model_name: str
    capabilities: list[str]
    enabled: bool
    context_window: int | None
    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
    embedding_price_per_million: Decimal | None
    pricing_version: str
    dimensions: int | None
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AIModelPage(BaseModel):
    items: list[AIModelResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class AITaskRouteUpdate(BaseModel):
    primary_model_id: UUID | None = None
    fallback_model_ids: list[UUID] = Field(default_factory=list, max_length=5)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    retry_limit: int = Field(default=1, ge=0, le=3)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class AITaskRouteResponse(BaseModel):
    id: UUID
    task_key: str
    version: int
    primary_model_id: UUID | None
    fallback_model_ids: list[UUID]
    timeout_seconds: int
    retry_limit: int
    budget_policy: dict[str, Any]
    config: dict[str, Any]
    enabled: bool
    is_active: bool
    created_at: datetime


class AITaskRoutePage(BaseModel):
    items: list[AITaskRouteResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class AIBudgetCreate(BaseModel):
    scope_type: str = Field(pattern="^(global|task|provider)$")
    scope_key: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    daily_cost_limit: Decimal | None = Field(default=None, ge=0)
    monthly_cost_limit: Decimal | None = Field(default=None, ge=0)
    daily_token_limit: int | None = Field(default=None, ge=0)
    unknown_usage_policy: str = Field(default="block", pattern="^(block|allow_once)$")
    config: dict[str, Any] = Field(default_factory=dict)


class AIBudgetUpdate(BaseModel):
    enabled: bool | None = None
    daily_cost_limit: Decimal | None = Field(default=None, ge=0)
    monthly_cost_limit: Decimal | None = Field(default=None, ge=0)
    daily_token_limit: int | None = Field(default=None, ge=0)
    unknown_usage_policy: str | None = Field(default=None, pattern="^(block|allow_once)$")
    config: dict[str, Any] | None = None


class AIBudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope_type: str
    scope_key: str
    enabled: bool
    daily_cost_limit: Decimal | None
    monthly_cost_limit: Decimal | None
    daily_token_limit: int | None
    unknown_usage_policy: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AIBudgetPage(BaseModel):
    items: list[AIBudgetResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class AIInvocationAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_no: int
    retry_index: int
    fallback_index: int
    provider_key: str
    model_name: str
    status: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost: Decimal | None
    latency_ms: int | None
    provider_request_id: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class AIInvocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    task_key: str
    route_version: int
    provider_key: str | None
    model_name: str | None
    capability: str
    status: str
    input_hash: str
    prompt_version: str | None
    schema_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost: Decimal | None
    latency_ms: int | None
    retry_count: int
    fallback_index: int
    provider_request_id: str | None
    subject_type: str | None
    subject_id: str | None
    pricing_snapshot: dict[str, Any]
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None


class AIInvocationDetail(AIInvocationResponse):
    attempts: list[AIInvocationAttemptResponse]


class AIInvocationPage(BaseModel):
    items: list[AIInvocationResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class AIConnectionTestRequest(BaseModel):
    model_id: UUID


class AIConnectionTestResponse(BaseModel):
    invocation_id: UUID | None
    status: str
    error_code: str | None = None
