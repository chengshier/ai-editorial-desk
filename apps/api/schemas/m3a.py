from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.database.models import (
    EventSignalAttachedBy,
    EventSignalRelation,
    EventStatus,
)


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    category: str | None = Field(default=None, max_length=100)
    status: EventStatus = EventStatus.EMERGING
    primary_language: str | None = Field(default=None, max_length=32)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: str | None
    category: str | None
    status: EventStatus
    first_seen_at: datetime | None
    last_updated_at: datetime
    primary_language: str | None
    entities: list[dict[str, Any]]
    keywords: list[str]
    source_count: int
    platform_count: int
    created_at: datetime
    updated_at: datetime


class EventPage(BaseModel):
    items: list[EventResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class EventSignalAttach(BaseModel):
    signal_id: UUID
    relation: EventSignalRelation
    confidence: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    attached_by: EventSignalAttachedBy = EventSignalAttachedBy.HUMAN

    @model_validator(mode="after")
    def require_current_attachment_method(self) -> EventSignalAttach:
        if self.attached_by is not EventSignalAttachedBy.HUMAN:
            raise ValueError("M3-A Admin API 仅允许 attached_by=human")
        return self


class EventSignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    signal_id: UUID
    relation: EventSignalRelation
    confidence: float
    attached_by: EventSignalAttachedBy
    created_at: datetime
    updated_at: datetime


class EventSignalPage(BaseModel):
    items: list[EventSignalResponse]
    page: int
    page_size: int
    total: int
    has_next: bool
