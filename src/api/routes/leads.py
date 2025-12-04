"""API routes for lead operations."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.lead import lead as lead_crud
from src.database import get_db
from src.models.company import Company
from src.models.lead import Lead, LeadClassification, LeadStatus
from src.schemas.lead import LeadCreate, LeadList, LeadResponse, LeadUpdate

router = APIRouter(prefix="/leads", tags=["Leads"])


# Response schemas
class LeadListResponse(BaseModel):
    """Paginated list of leads."""

    leads: list[LeadList]
    total: int
    page: int
    page_size: int


class LeadStatsResponse(BaseModel):
    """Lead statistics."""

    total: int
    by_status: dict[str, int]
    by_classification: dict[str, int]
    with_email: int
    with_linkedin: int
    average_score: float | None


class LeadWithCompanyResponse(LeadResponse):
    """Lead response with company info."""

    company_name: str | None = None
    company_domain: str | None = None


@router.get("", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, description="Filter by status"),
    classification_filter: str | None = Query(
        None, description="Filter by classification"
    ),
    has_email: bool | None = Query(None, description="Filter by having email"),
    company_id: int | None = Query(None, description="Filter by company"),
    min_score: int | None = Query(None, ge=0, le=100, description="Minimum ICP score"),
    search: str | None = Query(None, description="Search in name/email"),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    """List leads with pagination and filtering."""
    query = select(Lead)

    # Apply filters
    if status_filter:
        try:
            query = query.where(Lead.status == LeadStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    if classification_filter:
        try:
            query = query.where(
                Lead.classification == LeadClassification(classification_filter.upper())
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid classification: {classification_filter}",
            )

    if has_email is not None:
        if has_email:
            query = query.where(Lead.email.isnot(None))
        else:
            query = query.where(Lead.email.is_(None))

    if company_id:
        query = query.where(Lead.company_id == company_id)

    if min_score is not None:
        query = query.where(Lead.icp_score >= min_score)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (Lead.first_name.ilike(search_pattern))
            | (Lead.last_name.ilike(search_pattern))
            | (Lead.email.ilike(search_pattern))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    query = query.order_by(Lead.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    leads = result.scalars().all()

    return LeadListResponse(
        leads=[LeadList.model_validate(lead) for lead in leads],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=LeadStatsResponse)
async def get_lead_stats(
    db: AsyncSession = Depends(get_db),
) -> LeadStatsResponse:
    """Get lead statistics."""
    # Total count
    total_result = await db.execute(select(func.count()).select_from(Lead))
    total = total_result.scalar() or 0

    # Count by status
    status_result = await db.execute(
        select(Lead.status, func.count()).group_by(Lead.status)
    )
    by_status = {s.value: c for s, c in status_result.all()}

    # Count by classification
    classification_result = await db.execute(
        select(Lead.classification, func.count()).group_by(Lead.classification)
    )
    by_classification = {c.value: n for c, n in classification_result.all()}

    # Count with email
    email_result = await db.execute(
        select(func.count()).select_from(Lead).where(Lead.email.isnot(None))
    )
    with_email = email_result.scalar() or 0

    # Count with LinkedIn
    linkedin_result = await db.execute(
        select(func.count()).select_from(Lead).where(Lead.linkedin_url.isnot(None))
    )
    with_linkedin = linkedin_result.scalar() or 0

    # Average score
    avg_result = await db.execute(
        select(func.avg(Lead.icp_score)).where(Lead.icp_score.isnot(None))
    )
    average_score = avg_result.scalar()

    return LeadStatsResponse(
        total=total,
        by_status=by_status,
        by_classification=by_classification,
        with_email=with_email,
        with_linkedin=with_linkedin,
        average_score=float(average_score) if average_score else None,
    )


@router.get("/qualified")
async def list_qualified_leads(
    min_score: int = Query(60, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List qualified leads (score >= threshold)."""
    query = (
        select(Lead)
        .where(Lead.icp_score >= min_score)
        .order_by(Lead.icp_score.desc())
    )

    # Get total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    leads = result.scalars().all()

    return {
        "leads": [LeadResponse.model_validate(lead) for lead in leads],
        "total": total,
        "page": page,
        "page_size": page_size,
        "min_score": min_score,
    }


@router.get("/enriched")
async def list_enriched_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List leads with ENRICHED status."""
    query = (
        select(Lead)
        .where(Lead.status == LeadStatus.ENRICHED)
        .order_by(Lead.created_at.desc())
    )

    # Get total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    leads = result.scalars().all()

    return {
        "leads": [LeadResponse.model_validate(lead) for lead in leads],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{lead_id}", response_model=LeadWithCompanyResponse)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> LeadWithCompanyResponse:
    """Get a specific lead by ID with company info."""
    lead = await lead_crud.get(db, id=lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    # Get company info
    company = await db.get(Company, lead.company_id)

    response_data = LeadResponse.model_validate(lead).model_dump()
    response_data["company_name"] = company.name if company else None
    response_data["company_domain"] = company.domain if company else None

    return LeadWithCompanyResponse(**response_data)


@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    lead_in: LeadCreate,
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Create a new lead."""
    from src.crud.company import company as company_crud

    # Verify company exists
    company = await company_crud.get(db, id=lead_in.company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {lead_in.company_id} not found",
        )

    # Check for duplicate email
    if lead_in.email:
        existing = await lead_crud.get_by_email(db, email=lead_in.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lead with email {lead_in.email} already exists",
            )

    lead = await lead_crud.create(db, obj_in=lead_in)
    return LeadResponse.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    lead_in: LeadUpdate,
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Update a lead."""
    lead = await lead_crud.get(db, id=lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    # Check email uniqueness if updating email
    if lead_in.email and lead_in.email != lead.email:
        existing = await lead_crud.get_by_email(db, email=lead_in.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lead with email {lead_in.email} already exists",
            )

    updated = await lead_crud.update(db, db_obj=lead, obj_in=lead_in)
    return LeadResponse.model_validate(updated)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a lead."""
    lead = await lead_crud.get(db, id=lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    await lead_crud.delete(db, id=lead_id)


@router.post("/{lead_id}/status", response_model=LeadResponse)
async def update_lead_status(
    lead_id: int,
    new_status: str = Query(..., description="New status"),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Update a lead's status."""
    lead = await lead_crud.get(db, id=lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead {lead_id} not found",
        )

    try:
        target_status = LeadStatus(new_status.upper())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {new_status}",
        )

    if not lead.can_transition_to(target_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition from {lead.status.value} to {target_status.value}",
        )

    updated = await lead_crud.update_status(db, db_obj=lead, new_status=target_status)
    return LeadResponse.model_validate(updated)
