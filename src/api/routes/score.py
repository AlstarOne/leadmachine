"""API routes for ICP scoring."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.company import Company
from src.models.lead import Lead, LeadClassification, LeadStatus
from src.services.scoring import ICPScorer, ScoringConfig
from src.workers.score_tasks import score_lead_task, score_batch_task

router = APIRouter(prefix="/score", tags=["scoring"])


# Request/Response models
class ScoreLeadRequest(BaseModel):
    """Request to score a single lead."""

    lead_id: int


class ScoreBatchRequest(BaseModel):
    """Request to score multiple leads."""

    lead_ids: list[int] | None = None
    status_filter: str | None = None
    limit: int = 100


class ScoringConfigUpdate(BaseModel):
    """Request to update scoring configuration."""

    weights: dict | None = None
    thresholds: dict | None = None


class ScoreBreakdownResponse(BaseModel):
    """Score breakdown in response."""

    company_size: dict
    industry: dict
    growth: dict
    activity: dict
    location: dict
    total: int


class ScoringResponse(BaseModel):
    """Response for scoring result."""

    lead_id: int
    score: int
    breakdown: ScoreBreakdownResponse
    classification: str
    qualified: bool
    errors: list[str] = []


class BatchJobResponse(BaseModel):
    """Response for batch scoring job."""

    job_id: str
    status: str
    message: str


class ScoringStatsResponse(BaseModel):
    """Response for scoring statistics."""

    total_leads: int
    scored_leads: int
    unscored_leads: int
    by_classification: dict[str, int]
    qualified_count: int
    average_score: float | None


class QualifiedLeadsResponse(BaseModel):
    """Response for qualified leads list."""

    leads: list[dict]
    total: int
    min_score: int


class ConfigResponse(BaseModel):
    """Response for scoring configuration."""

    weights: dict
    thresholds: dict


# Helper function
def get_scorer() -> ICPScorer:
    """Get ICP scorer instance."""
    return ICPScorer()


# Endpoints
@router.post("/calculate", response_model=ScoringResponse)
async def calculate_score(
    request: ScoreLeadRequest,
    db: AsyncSession = Depends(get_db),
    scorer: ICPScorer = Depends(get_scorer),
) -> ScoringResponse:
    """Calculate ICP score for a single lead.

    This calculates and saves the score synchronously.
    """
    # Get lead
    lead = await db.get(Lead, request.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Get company
    company = await db.get(Company, lead.company_id) if lead.company_id else None

    # Calculate score
    result = await scorer.score_lead(db, lead, company, save=True)

    return ScoringResponse(
        lead_id=result.lead_id,
        score=result.score,
        breakdown=ScoreBreakdownResponse(**result.breakdown.to_dict()),
        classification=result.classification.value,
        qualified=result.qualified,
        errors=result.errors,
    )


@router.post("/calculate/{lead_id}", response_model=ScoringResponse)
async def calculate_score_by_id(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    scorer: ICPScorer = Depends(get_scorer),
) -> ScoringResponse:
    """Calculate ICP score for a lead by ID."""
    # Get lead
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Get company
    company = await db.get(Company, lead.company_id) if lead.company_id else None

    # Calculate score
    result = await scorer.score_lead(db, lead, company, save=True)

    return ScoringResponse(
        lead_id=result.lead_id,
        score=result.score,
        breakdown=ScoreBreakdownResponse(**result.breakdown.to_dict()),
        classification=result.classification.value,
        qualified=result.qualified,
        errors=result.errors,
    )


@router.post("/batch", response_model=BatchJobResponse)
async def score_batch(
    request: ScoreBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> BatchJobResponse:
    """Start batch scoring job.

    Scores multiple leads asynchronously using Celery.
    """
    # Validate lead_ids if provided
    if request.lead_ids:
        stmt = select(func.count(Lead.id)).where(Lead.id.in_(request.lead_ids))
        result = await db.execute(stmt)
        count = result.scalar() or 0
        if count != len(request.lead_ids):
            raise HTTPException(
                status_code=400,
                detail=f"Some lead IDs not found. Found {count} of {len(request.lead_ids)}",
            )

    # Start Celery task
    task = score_batch_task.delay(
        lead_ids=request.lead_ids,
        status_filter=request.status_filter,
        limit=request.limit,
    )

    return BatchJobResponse(
        job_id=task.id,
        status="started",
        message=f"Scoring job started for up to {request.limit} leads",
    )


@router.get("/stats", response_model=ScoringStatsResponse)
async def get_scoring_stats(
    db: AsyncSession = Depends(get_db),
) -> ScoringStatsResponse:
    """Get scoring statistics."""
    # Total leads
    total_stmt = select(func.count(Lead.id))
    total_result = await db.execute(total_stmt)
    total_leads = total_result.scalar() or 0

    # Scored leads
    scored_stmt = select(func.count(Lead.id)).where(Lead.icp_score.isnot(None))
    scored_result = await db.execute(scored_stmt)
    scored_leads = scored_result.scalar() or 0

    # By classification
    by_classification: dict[str, int] = {}
    for classification in LeadClassification:
        class_stmt = select(func.count(Lead.id)).where(
            Lead.classification == classification
        )
        class_result = await db.execute(class_stmt)
        by_classification[classification.value] = class_result.scalar() or 0

    # Qualified count
    scorer = ICPScorer()
    threshold = scorer.config.thresholds.qualified_threshold
    qualified_stmt = select(func.count(Lead.id)).where(Lead.icp_score >= threshold)
    qualified_result = await db.execute(qualified_stmt)
    qualified_count = qualified_result.scalar() or 0

    # Average score
    avg_stmt = select(func.avg(Lead.icp_score)).where(Lead.icp_score.isnot(None))
    avg_result = await db.execute(avg_stmt)
    average_score = avg_result.scalar()

    return ScoringStatsResponse(
        total_leads=total_leads,
        scored_leads=scored_leads,
        unscored_leads=total_leads - scored_leads,
        by_classification=by_classification,
        qualified_count=qualified_count,
        average_score=float(average_score) if average_score else None,
    )


@router.get("/qualified", response_model=QualifiedLeadsResponse)
async def get_qualified_leads(
    min_score: int = Query(default=60, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    scorer: ICPScorer = Depends(get_scorer),
) -> QualifiedLeadsResponse:
    """Get list of qualified leads.

    Returns leads with score >= min_score, sorted by score descending.
    """
    leads, total = await scorer.get_qualified_leads(db, min_score, limit, offset)

    leads_data = []
    for lead in leads:
        leads_data.append({
            "id": lead.id,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "email": lead.email,
            "job_title": lead.job_title,
            "company_id": lead.company_id,
            "icp_score": lead.icp_score,
            "classification": lead.classification.value,
            "status": lead.status.value,
        })

    return QualifiedLeadsResponse(
        leads=leads_data,
        total=total,
        min_score=min_score,
    )


@router.get("/unscored")
async def get_unscored_leads(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    scorer: ICPScorer = Depends(get_scorer),
) -> dict:
    """Get leads that need scoring."""
    leads = await scorer.get_leads_to_score(db, limit)

    return {
        "leads": [
            {
                "id": lead.id,
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "email": lead.email,
                "company_id": lead.company_id,
                "status": lead.status.value,
            }
            for lead in leads
        ],
        "count": len(leads),
    }


@router.get("/config", response_model=ConfigResponse)
async def get_scoring_config(
    scorer: ICPScorer = Depends(get_scorer),
) -> ConfigResponse:
    """Get current scoring configuration."""
    config = scorer.get_config()
    return ConfigResponse(
        weights=config["weights"],
        thresholds=config["thresholds"],
    )


@router.put("/config", response_model=ConfigResponse)
async def update_scoring_config(
    update: ScoringConfigUpdate,
    scorer: ICPScorer = Depends(get_scorer),
) -> ConfigResponse:
    """Update scoring configuration.

    Note: This only updates the in-memory configuration.
    For persistent configuration, store in database.
    """
    config_data: dict = {}

    if update.weights:
        config_data["weights"] = update.weights
    if update.thresholds:
        config_data["thresholds"] = update.thresholds

    if config_data:
        scorer.update_config(config_data)

    config = scorer.get_config()
    return ConfigResponse(
        weights=config["weights"],
        thresholds=config["thresholds"],
    )


@router.get("/lead/{lead_id}")
async def get_lead_score(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get score details for a specific lead."""
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.icp_score is None:
        return {
            "lead_id": lead_id,
            "scored": False,
            "message": "Lead has not been scored yet",
        }

    return {
        "lead_id": lead_id,
        "scored": True,
        "score": lead.icp_score,
        "classification": lead.classification.value,
        "breakdown": lead.score_breakdown,
        "scored_at": lead.scored_at.isoformat() if lead.scored_at else None,
    }
