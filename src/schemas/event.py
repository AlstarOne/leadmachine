"""Pydantic schemas for Event model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.event import EventType


class EventBase(BaseModel):
    """Base schema for Event."""

    event_type: EventType
    ip_address: str | None = Field(None, max_length=45)
    user_agent: str | None = Field(None, max_length=500)
    referer: str | None = Field(None, max_length=500)


class EventCreate(EventBase):
    """Schema for creating an Event."""

    email_id: int
    clicked_url: str | None = Field(None, max_length=2000)
    extra_data: dict | None = None


class EventRead(EventBase):
    """Schema for reading an Event."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email_id: int
    clicked_url: str | None
    extra_data: dict | None
    timestamp: datetime


class EventList(BaseModel):
    """Schema for listing Events."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email_id: int
    event_type: EventType
    timestamp: datetime
    clicked_url: str | None


class TrackingStats(BaseModel):
    """Schema for tracking statistics."""

    total_opens: int
    unique_opens: int
    total_clicks: int
    unique_clicks: int
    replies: int
    bounces: int
    open_rate: float
    click_rate: float
    reply_rate: float
    bounce_rate: float
