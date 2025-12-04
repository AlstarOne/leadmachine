"""Pydantic schemas for Company model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.models.company import CompanySource, CompanyStatus


class CompanyBase(BaseModel):
    """Base schema for Company."""

    name: str = Field(..., min_length=1, max_length=255)
    domain: str | None = Field(None, max_length=255)
    website_url: str | None = Field(None, max_length=500)
    industry: str | None = Field(None, max_length=100)
    employee_count: int | None = Field(None, ge=0)
    open_vacancies: int | None = Field(None, ge=0)
    location: str | None = Field(None, max_length=255)
    description: str | None = None


class CompanyCreate(CompanyBase):
    """Schema for creating a Company."""

    source: CompanySource
    source_url: str | None = Field(None, max_length=500)
    raw_data: dict | None = None


class CompanyUpdate(BaseModel):
    """Schema for updating a Company."""

    name: str | None = Field(None, min_length=1, max_length=255)
    domain: str | None = Field(None, max_length=255)
    website_url: str | None = Field(None, max_length=500)
    industry: str | None = Field(None, max_length=100)
    employee_count: int | None = Field(None, ge=0)
    open_vacancies: int | None = Field(None, ge=0)
    location: str | None = Field(None, max_length=255)
    description: str | None = None
    status: CompanyStatus | None = None


class CompanyRead(CompanyBase):
    """Schema for reading a Company."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: CompanySource
    source_url: str | None
    status: CompanyStatus
    created_at: datetime
    updated_at: datetime
    enriched_at: datetime | None


class CompanyList(BaseModel):
    """Schema for listing Companies."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str | None
    industry: str | None
    source: CompanySource
    status: CompanyStatus
    created_at: datetime


# Alias for API responses
CompanyResponse = CompanyRead
