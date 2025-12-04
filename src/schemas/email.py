"""Pydantic schemas for Email model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.email import EmailSequenceStep, EmailStatus


class EmailBase(BaseModel):
    """Base schema for Email."""

    subject: str = Field(..., min_length=1, max_length=500)
    body_text: str = Field(..., min_length=1)
    body_html: str | None = None


class EmailCreate(EmailBase):
    """Schema for creating an Email."""

    lead_id: int
    sequence_step: EmailSequenceStep = EmailSequenceStep.INITIAL
    scheduled_day: int = Field(0, ge=0)
    scheduled_at: datetime | None = None


class EmailUpdate(BaseModel):
    """Schema for updating an Email."""

    subject: str | None = Field(None, min_length=1, max_length=500)
    body_text: str | None = Field(None, min_length=1)
    body_html: str | None = None
    status: EmailStatus | None = None
    scheduled_at: datetime | None = None


class EmailRead(EmailBase):
    """Schema for reading an Email."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    sequence_step: EmailSequenceStep
    scheduled_day: int
    tracking_id: str
    message_id: str | None
    status: EmailStatus
    open_count: int
    click_count: int
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None
    replied_at: datetime | None
    bounced_at: datetime | None


class EmailList(BaseModel):
    """Schema for listing Emails."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    subject: str
    sequence_step: EmailSequenceStep
    status: EmailStatus
    scheduled_at: datetime | None
    sent_at: datetime | None
    open_count: int
    click_count: int


class EmailSequence(BaseModel):
    """Schema for a complete email sequence."""

    lead_id: int
    emails: list[EmailRead]
    total_opens: int
    total_clicks: int
    has_replied: bool
