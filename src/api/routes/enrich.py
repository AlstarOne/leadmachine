"""API routes for enrichment operations."""

from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.company import company as company_crud
from src.crud.lead import lead as lead_crud
from src.database import get_db
from src.models.company import Company, CompanyStatus
from src.models.lead import Lead, LeadStatus

router = APIRouter(prefix="/enrich", tags=["Enrichment"])


# Request/Response schemas
class EnrichCompanyRequest(BaseModel):
    """Request to enrich a single company."""

    company_id: int


class EnrichBatchRequest(BaseModel):
    """Request to enrich multiple companies."""

    company_ids: list[int] | None = Field(
        None, description="Specific company IDs to enrich"
    )
    status_filter: str | None = Field(
        None, description="Filter by company status (default: NEW)"
    )
    limit: int = Field(50, ge=1, le=100, description="Maximum companies to process")


class EnrichLeadRequest(BaseModel):
    """Request to enrich a single lead."""

    lead_id: int


class EnrichJobResponse(BaseModel):
    """Response with enrichment job info."""

    job_id: str
    status: str
    message: str


class EnrichmentStatsResponse(BaseModel):
    """Enrichment statistics."""

    total_companies: int
    enriched_companies: int
    enriching_companies: int
    no_contact_companies: int
    total_leads: int
    leads_with_email: int
    leads_without_email: int


@router.post("/company", response_model=EnrichJobResponse)
async def enrich_company(
    request: EnrichCompanyRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrichJobResponse:
    """Start enrichment for a single company.

    This creates a background task that:
    1. Verifies/finds the company domain
    2. Scrapes team/about pages for team members
    3. Generates email patterns and verifies them
    4. Creates leads with enriched contact data
    """
    # Verify company exists
    company = await company_crud.get(db, id=request.company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {request.company_id} not found",
        )

    # Import and start Celery task
    from src.workers.enrich_tasks import enrich_company_task

    task = enrich_company_task.delay(request.company_id)

    return EnrichJobResponse(
        job_id=task.id,
        status="started",
        message=f"Enrichment started for company {company.name}",
    )


@router.post("/lead", response_model=EnrichJobResponse)
async def enrich_lead(
    request: EnrichLeadRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrichJobResponse:
    """Start enrichment for a single lead.

    This creates a background task that:
    1. Looks up the lead's company domain
    2. Generates email patterns based on first/last name
    3. Verifies email addresses via SMTP
    4. Updates the lead with found email
    """
    # Verify lead exists
    lead = await lead_crud.get(db, id=request.lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {request.lead_id} not found",
        )

    # Import and start Celery task
    from src.workers.enrich_tasks import enrich_lead_task

    task = enrich_lead_task.delay(request.lead_id)

    return EnrichJobResponse(
        job_id=task.id,
        status="started",
        message=f"Enrichment started for lead {lead.first_name} {lead.last_name}",
    )


@router.post("/batch", response_model=EnrichJobResponse)
async def enrich_batch(
    request: EnrichBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrichJobResponse:
    """Start enrichment for multiple companies.

    If company_ids is provided, enriches those specific companies.
    Otherwise, enriches companies by status (default: NEW).
    """
    # Import and start Celery task
    from src.workers.enrich_tasks import run_enrichment_batch

    task = run_enrichment_batch.delay(
        company_ids=request.company_ids,
        status_filter=request.status_filter,
        limit=request.limit,
    )

    return EnrichJobResponse(
        job_id=task.id,
        status="started",
        message=f"Batch enrichment started (limit: {request.limit})",
    )


@router.post("/leads-without-email", response_model=EnrichJobResponse)
async def enrich_leads_without_email(
    limit: int = Query(50, ge=1, le=100),
) -> EnrichJobResponse:
    """Enrich leads that don't have email addresses.

    Finds leads with first_name and last_name but no email,
    and attempts to find their email addresses.
    """
    from src.workers.enrich_tasks import enrich_leads_without_email as enrich_task

    task = enrich_task.delay(limit=limit)

    return EnrichJobResponse(
        job_id=task.id,
        status="started",
        message=f"Enriching leads without email (limit: {limit})",
    )


@router.get("/jobs/{job_id}")
async def get_enrichment_job(
    job_id: str,
) -> dict[str, Any]:
    """Get the status and result of an enrichment job."""
    result = AsyncResult(job_id)

    response: dict[str, Any] = {
        "job_id": job_id,
        "status": result.status,
        "ready": result.ready(),
    }

    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)

    return response


@router.get("/stats", response_model=EnrichmentStatsResponse)
async def get_enrichment_stats(
    db: AsyncSession = Depends(get_db),
) -> EnrichmentStatsResponse:
    """Get enrichment statistics."""
    # Company counts by status
    total_companies_result = await db.execute(
        select(func.count()).select_from(Company)
    )
    total_companies = total_companies_result.scalar() or 0

    enriched_result = await db.execute(
        select(func.count())
        .select_from(Company)
        .where(Company.status == CompanyStatus.ENRICHED)
    )
    enriched_companies = enriched_result.scalar() or 0

    enriching_result = await db.execute(
        select(func.count())
        .select_from(Company)
        .where(Company.status == CompanyStatus.ENRICHING)
    )
    enriching_companies = enriching_result.scalar() or 0

    no_contact_result = await db.execute(
        select(func.count())
        .select_from(Company)
        .where(Company.status == CompanyStatus.NO_CONTACT)
    )
    no_contact_companies = no_contact_result.scalar() or 0

    # Lead counts
    total_leads_result = await db.execute(select(func.count()).select_from(Lead))
    total_leads = total_leads_result.scalar() or 0

    leads_with_email_result = await db.execute(
        select(func.count()).select_from(Lead).where(Lead.email.isnot(None))
    )
    leads_with_email = leads_with_email_result.scalar() or 0

    leads_without_email = total_leads - leads_with_email

    return EnrichmentStatsResponse(
        total_companies=total_companies,
        enriched_companies=enriched_companies,
        enriching_companies=enriching_companies,
        no_contact_companies=no_contact_companies,
        total_leads=total_leads,
        leads_with_email=leads_with_email,
        leads_without_email=leads_without_email,
    )


@router.get("/ready-to-enrich")
async def get_companies_ready_to_enrich(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get companies that are ready for enrichment (status NEW with domain)."""
    from src.schemas.company import CompanyResponse

    stmt = (
        select(Company)
        .where(Company.status == CompanyStatus.NEW)
        .where(Company.domain.isnot(None))
        .order_by(Company.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    companies = list(result.scalars().all())

    return {
        "companies": [CompanyResponse.model_validate(c) for c in companies],
        "total": len(companies),
    }
