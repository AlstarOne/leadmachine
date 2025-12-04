"""API routes for company operations."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.company import company as company_crud
from src.database import get_db
from src.models.company import Company, CompanySource, CompanyStatus
from src.schemas.company import CompanyCreate, CompanyResponse, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["Companies"])


# Additional response schemas
class CompanyListResponse(BaseModel):
    """Paginated list of companies."""

    companies: list[CompanyResponse]
    total: int
    page: int
    page_size: int


class CompanyStatsResponse(BaseModel):
    """Company statistics."""

    total: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    with_domain: int
    with_linkedin: int
    with_funding: int


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, description="Filter by status"),
    source_filter: str | None = Query(None, description="Filter by source"),
    has_domain: bool | None = Query(None, description="Filter by having domain"),
    search: str | None = Query(None, description="Search in name/domain"),
    db: AsyncSession = Depends(get_db),
) -> CompanyListResponse:
    """List companies with pagination and filtering."""
    query = select(Company)

    # Apply filters
    if status_filter:
        try:
            query = query.where(Company.status == CompanyStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    if source_filter:
        try:
            query = query.where(Company.source == CompanySource(source_filter.upper()))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source: {source_filter}",
            )

    if has_domain is not None:
        if has_domain:
            query = query.where(Company.domain.isnot(None))
        else:
            query = query.where(Company.domain.is_(None))

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (Company.name.ilike(search_pattern)) | (Company.domain.ilike(search_pattern))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    query = query.order_by(Company.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    companies = result.scalars().all()

    return CompanyListResponse(
        companies=[CompanyResponse.model_validate(c) for c in companies],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=CompanyStatsResponse)
async def get_company_stats(
    db: AsyncSession = Depends(get_db),
) -> CompanyStatsResponse:
    """Get company statistics."""
    # Total count
    total_result = await db.execute(select(func.count()).select_from(Company))
    total = total_result.scalar() or 0

    # Count by status
    status_result = await db.execute(
        select(Company.status, func.count()).group_by(Company.status)
    )
    by_status = {s.value: c for s, c in status_result.all()}

    # Count by source
    source_result = await db.execute(
        select(Company.source, func.count()).group_by(Company.source)
    )
    by_source = {s.value: c for s, c in source_result.all()}

    # Count with domain
    domain_result = await db.execute(
        select(func.count()).select_from(Company).where(Company.domain.isnot(None))
    )
    with_domain = domain_result.scalar() or 0

    # Count with LinkedIn
    linkedin_result = await db.execute(
        select(func.count()).select_from(Company).where(Company.linkedin_url.isnot(None))
    )
    with_linkedin = linkedin_result.scalar() or 0

    # Count with funding
    funding_result = await db.execute(
        select(func.count()).select_from(Company).where(Company.has_funding == True)
    )
    with_funding = funding_result.scalar() or 0

    return CompanyStatsResponse(
        total=total,
        by_status=by_status,
        by_source=by_source,
        with_domain=with_domain,
        with_linkedin=with_linkedin,
        with_funding=with_funding,
    )


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Get a specific company by ID."""
    company = await company_crud.get(db, id=company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )
    return CompanyResponse.model_validate(company)


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    company_in: CompanyCreate,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Create a new company."""
    # Check for duplicate domain
    if company_in.domain:
        existing = await company_crud.get_by_domain(db, domain=company_in.domain)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Company with domain {company_in.domain} already exists",
            )

    company = await company_crud.create(db, obj_in=company_in)
    return CompanyResponse.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: int,
    company_in: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Update a company."""
    company = await company_crud.get(db, id=company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )

    # Check domain uniqueness if updating domain
    if company_in.domain and company_in.domain != company.domain:
        existing = await company_crud.get_by_domain(db, domain=company_in.domain)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Company with domain {company_in.domain} already exists",
            )

    updated = await company_crud.update(db, db_obj=company, obj_in=company_in)
    return CompanyResponse.model_validate(updated)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a company."""
    company = await company_crud.get(db, id=company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )

    await company_crud.delete(db, id=company_id)


@router.post("/{company_id}/status", response_model=CompanyResponse)
async def update_company_status(
    company_id: int,
    new_status: str = Query(..., description="New status"),
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Update a company's status."""
    company = await company_crud.get(db, id=company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )

    try:
        target_status = CompanyStatus(new_status.upper())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {new_status}",
        )

    if not company.can_transition_to(target_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition from {company.status.value} to {target_status.value}",
        )

    updated = await company_crud.update_status(db, db_obj=company, new_status=target_status)
    return CompanyResponse.model_validate(updated)


@router.get("/{company_id}/leads")
async def get_company_leads(
    company_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all leads associated with a company."""
    from src.crud.lead import lead as lead_crud
    from src.schemas.lead import LeadResponse

    company = await company_crud.get(db, id=company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )

    leads = await lead_crud.get_by_company(db, company_id=company_id)

    return {
        "company_id": company_id,
        "company_name": company.name,
        "leads": [LeadResponse.model_validate(lead) for lead in leads],
        "total": len(leads),
    }
