"""Pydantic schemas for Lead model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.models.lead import LeadClassification, LeadStatus


class LeadBase(BaseModel):
    """Base schema for Lead."""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    job_title: str | None = Field(None, max_length=200)
    linkedin_url: str | None = Field(None, max_length=500)
    phone: str | None = Field(None, max_length=50)


class LeadCreate(LeadBase):
    """Schema for creating a Lead."""

    company_id: int


class LeadUpdate(BaseModel):
    """Schema for updating a Lead."""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    job_title: str | None = Field(None, max_length=200)
    linkedin_url: str | None = Field(None, max_length=500)
    phone: str | None = Field(None, max_length=50)
    status: LeadStatus | None = None
    icp_score: int | None = Field(None, ge=0, le=100)
    classification: LeadClassification | None = None
    score_breakdown: dict | None = None


class LeadRead(LeadBase):
    """Schema for reading a Lead."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    status: LeadStatus
    icp_score: int | None
    classification: LeadClassification
    score_breakdown: dict | None
    email_confidence: int | None
    created_at: datetime
    updated_at: datetime
    scored_at: datetime | None
    sequenced_at: datetime | None


class LeadList(BaseModel):
    """Schema for listing Leads."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    first_name: str | None
    last_name: str | None
    email: str | None
    job_title: str | None
    status: LeadStatus
    icp_score: int | None
    classification: LeadClassification
    created_at: datetime


class LeadWithCompany(LeadRead):
    """Schema for Lead with Company details."""

    company_name: str
    company_domain: str | None


# Alias for API responses
LeadResponse = LeadRead
