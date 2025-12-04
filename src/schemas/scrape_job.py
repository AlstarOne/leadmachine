"""Pydantic schemas for ScrapeJob model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.company import CompanySource
from src.models.scrape_job import ScrapeJobStatus


class ScrapeJobBase(BaseModel):
    """Base schema for ScrapeJob."""

    source: CompanySource
    keywords: list[str] | None = None
    filters: dict | None = None


class ScrapeJobCreate(ScrapeJobBase):
    """Schema for creating a ScrapeJob."""

    pass


class ScrapeJobUpdate(BaseModel):
    """Schema for updating a ScrapeJob."""

    status: ScrapeJobStatus | None = None
    error_message: str | None = None


class ScrapeJobRead(ScrapeJobBase):
    """Schema for reading a ScrapeJob."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ScrapeJobStatus
    results_count: int
    new_companies_count: int
    duplicate_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    celery_task_id: str | None


class ScrapeJobList(BaseModel):
    """Schema for listing ScrapeJobs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: CompanySource
    status: ScrapeJobStatus
    results_count: int
    new_companies_count: int
    created_at: datetime
    completed_at: datetime | None


class ScrapeJobWithDuration(ScrapeJobRead):
    """Schema for ScrapeJob with duration."""

    duration_seconds: float | None
