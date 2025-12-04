"""API routes for scraping operations."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.scrape_job import ScrapeJob, ScrapeJobStatus
from src.services.scrapers.base import ScraperType

router = APIRouter(prefix="/scrape", tags=["Scraping"])


# Request/Response schemas
class ScrapeJobCreate(BaseModel):
    """Request to start a new scrape job."""

    source: str = Field(..., description="Scraper type: INDEED, KVK, LINKEDIN, TECHLEAP, DEALROOM")
    keywords: list[str] = Field(..., min_length=1, description="Search keywords")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filters")
    max_pages: int = Field(default=5, ge=1, le=20, description="Maximum pages to scrape")


class ScrapeJobResponse(BaseModel):
    """Scrape job response."""

    id: int
    source: str
    keywords: list[str]
    status: str
    results_count: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class ScrapeJobListResponse(BaseModel):
    """List of scrape jobs."""

    jobs: list[ScrapeJobResponse]
    total: int
    page: int
    page_size: int


class ScrapeTaskResponse(BaseModel):
    """Response when starting a scrape task."""

    job_id: int
    task_id: str
    status: str
    message: str


@router.post("/start", response_model=ScrapeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_scrape(
    request: ScrapeJobCreate,
    db: AsyncSession = Depends(get_db),
) -> ScrapeTaskResponse:
    """Start a new scrape job.

    Creates a scrape job record and queues it for background processing.
    """
    # Validate scraper type
    valid_sources = [s.value for s in ScraperType]
    if request.source.upper() not in valid_sources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source. Must be one of: {', '.join(valid_sources)}",
        )

    # Create job record
    job = ScrapeJob(
        source=request.source.upper(),
        keywords=request.keywords,
        config=request.filters,
        status=ScrapeJobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Queue background task
    from src.workers.scrape_tasks import run_scrape_job

    task = run_scrape_job.delay(
        job_id=job.id,
        scraper_type=request.source.upper(),
        keywords=request.keywords,
        filters=request.filters,
        max_pages=request.max_pages,
    )

    return ScrapeTaskResponse(
        job_id=job.id,
        task_id=task.id,
        status="queued",
        message=f"Scrape job {job.id} queued for {request.source}",
    )


@router.get("/jobs", response_model=ScrapeJobListResponse)
async def list_scrape_jobs(
    page: int = 1,
    page_size: int = 20,
    source: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> ScrapeJobListResponse:
    """List scrape jobs with pagination and filtering."""
    query = select(ScrapeJob)

    # Apply filters
    if source:
        query = query.where(ScrapeJob.source == source.upper())
    if status_filter:
        query = query.where(ScrapeJob.status == ScrapeJobStatus(status_filter.upper()))

    # Get total count
    count_query = select(func.count()).select_from(ScrapeJob)
    if source:
        count_query = count_query.where(ScrapeJob.source == source.upper())
    if status_filter:
        count_query = count_query.where(ScrapeJob.status == ScrapeJobStatus(status_filter.upper()))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(ScrapeJob.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return ScrapeJobListResponse(
        jobs=[
            ScrapeJobResponse(
                id=job.id,
                source=job.source,
                keywords=job.keywords,
                status=job.status.value,
                results_count=job.results_count,
                created_at=job.created_at.isoformat() if job.created_at else "",
                started_at=job.started_at.isoformat() if job.started_at else None,
                completed_at=job.completed_at.isoformat() if job.completed_at else None,
                error_message=job.error_message,
            )
            for job in jobs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=ScrapeJobResponse)
async def get_scrape_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> ScrapeJobResponse:
    """Get details of a specific scrape job."""
    job = await db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scrape job {job_id} not found",
        )

    return ScrapeJobResponse(
        id=job.id,
        source=job.source,
        keywords=job.keywords,
        status=job.status.value,
        results_count=job.results_count,
        created_at=job.created_at.isoformat() if job.created_at else "",
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error_message=job.error_message,
    )


@router.post("/jobs/{job_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_scrape_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Cancel a pending or running scrape job."""
    job = await db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scrape job {job_id} not found",
        )

    if job.status not in (ScrapeJobStatus.PENDING, ScrapeJobStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job with status {job.status.value}",
        )

    job.status = ScrapeJobStatus.CANCELLED
    db.add(job)
    await db.commit()

    return {"message": f"Scrape job {job_id} cancelled"}


@router.get("/sources")
async def list_scraper_sources() -> dict[str, Any]:
    """List available scraper sources."""
    return {
        "sources": [
            {
                "name": ScraperType.INDEED.value,
                "description": "Indeed.nl job listings - finds companies with open vacancies",
                "filters": ["location"],
            },
            {
                "name": ScraperType.KVK.value,
                "description": "KvK Handelsregister - finds newly registered Dutch companies",
                "filters": ["legal_form", "sbi_codes"],
            },
            {
                "name": ScraperType.LINKEDIN.value,
                "description": "LinkedIn company search - requires proxy support",
                "filters": ["company_size", "location"],
            },
            {
                "name": ScraperType.TECHLEAP.value,
                "description": "Techleap.nl - Dutch funded startups/scale-ups",
                "filters": ["funding_stage", "location"],
            },
            {
                "name": ScraperType.DEALROOM.value,
                "description": "Dealroom.co - European startup database",
                "filters": ["country", "funding_stage"],
            },
        ]
    }


@router.post("/trigger-daily", status_code=status.HTTP_202_ACCEPTED)
async def trigger_daily_scrape() -> dict[str, str]:
    """Manually trigger the daily scrape job."""
    from src.workers.scrape_tasks import run_daily_scrape

    task = run_daily_scrape.delay()

    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Daily scrape job triggered",
    }
