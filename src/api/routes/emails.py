"""API routes for email generation and management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.company import Company
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.models.lead import Lead, LeadStatus
from src.services.email import EmailGenerator, EmailTemplates


router = APIRouter(prefix="/emails", tags=["emails"])


# Request/Response models
class GenerateSequenceRequest(BaseModel):
    """Request to generate email sequence for a lead."""

    additional_context: str = ""
    start_date: datetime | None = None


class GenerateBatchRequest(BaseModel):
    """Request to generate sequences for multiple leads."""

    lead_ids: list[int] | None = None
    min_score: int = 60
    limit: int = 50
    additional_context: str = ""


class EmailUpdateRequest(BaseModel):
    """Request to update an email."""

    subject: str | None = None
    body_text: str | None = None
    scheduled_at: datetime | None = None


class RegenerateEmailRequest(BaseModel):
    """Request to regenerate an email."""

    additional_context: str = ""


class GeneratedEmailResponse(BaseModel):
    """Response for a generated email."""

    id: int | None = None
    subject: str
    body: str
    preview_text: str
    email_type: str
    sequence_step: int
    word_count: int
    scheduled_for: datetime | None


class SequenceResponse(BaseModel):
    """Response for email sequence generation."""

    lead_id: int
    emails: list[GeneratedEmailResponse]
    total_tokens: int
    estimated_cost: float
    success: bool
    errors: list[str]


class BatchJobResponse(BaseModel):
    """Response for batch generation job."""

    job_id: str
    status: str
    message: str
    leads_count: int


class EmailReadResponse(BaseModel):
    """Response for reading an email."""

    id: int
    lead_id: int
    sequence_step: str
    scheduled_day: int
    subject: str
    body_text: str
    body_html: str | None
    tracking_id: str
    status: str
    scheduled_at: datetime | None
    sent_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None
    replied_at: datetime | None
    open_count: int
    click_count: int


class LeadEmailsResponse(BaseModel):
    """Response for lead's email sequence."""

    lead_id: int
    lead_name: str
    lead_email: str | None
    company_name: str | None
    status: str
    emails: list[EmailReadResponse]
    total_emails: int


class TemplateResponse(BaseModel):
    """Response for an email template."""

    name: str
    email_type: str
    max_words: int
    tone: str
    language: str


class TemplatesListResponse(BaseModel):
    """Response for listing templates."""

    templates: list[TemplateResponse]
    sequence_schedule: list[dict]
    value_propositions: dict[str, str]


class EmailStatsResponse(BaseModel):
    """Response for email statistics."""

    total_emails: int
    by_status: dict[str, int]
    by_sequence_step: dict[str, int]
    total_opens: int
    total_clicks: int
    leads_sequenced: int
    leads_pending: int


# Dependency
def get_generator() -> EmailGenerator:
    """Get email generator instance."""
    return EmailGenerator()


# =============================================================================
# STATIC ROUTES - Must come before parameterized routes
# =============================================================================

@router.get("/templates/list", response_model=TemplatesListResponse)
async def get_templates() -> TemplatesListResponse:
    """Get available email templates and configuration."""
    templates = [
        TemplateResponse(
            name=EmailTemplates.INITIAL_EMAIL.name,
            email_type=EmailTemplates.INITIAL_EMAIL.email_type,
            max_words=EmailTemplates.INITIAL_EMAIL.max_words,
            tone=EmailTemplates.INITIAL_EMAIL.tone,
            language=EmailTemplates.INITIAL_EMAIL.language,
        ),
        TemplateResponse(
            name=EmailTemplates.FOLLOWUP_1.name,
            email_type=EmailTemplates.FOLLOWUP_1.email_type,
            max_words=EmailTemplates.FOLLOWUP_1.max_words,
            tone=EmailTemplates.FOLLOWUP_1.tone,
            language=EmailTemplates.FOLLOWUP_1.language,
        ),
        TemplateResponse(
            name=EmailTemplates.FOLLOWUP_2.name,
            email_type=EmailTemplates.FOLLOWUP_2.email_type,
            max_words=EmailTemplates.FOLLOWUP_2.max_words,
            tone=EmailTemplates.FOLLOWUP_2.tone,
            language=EmailTemplates.FOLLOWUP_2.language,
        ),
        TemplateResponse(
            name=EmailTemplates.BREAKUP.name,
            email_type=EmailTemplates.BREAKUP.email_type,
            max_words=EmailTemplates.BREAKUP.max_words,
            tone=EmailTemplates.BREAKUP.tone,
            language=EmailTemplates.BREAKUP.language,
        ),
    ]

    schedule = EmailTemplates.get_sequence_schedule()

    return TemplatesListResponse(
        templates=templates,
        sequence_schedule=[
            {"email_type": email_type, "days_after_start": days}
            for email_type, days in schedule
        ],
        value_propositions=EmailTemplates.DEFAULT_VALUE_PROPOSITIONS,
    )


@router.get("/stats", response_model=EmailStatsResponse)
async def get_email_stats(
    db: AsyncSession = Depends(get_db),
) -> EmailStatsResponse:
    """Get email generation statistics."""
    # Total emails
    total_stmt = select(func.count(Email.id))
    total_result = await db.execute(total_stmt)
    total_emails = total_result.scalar() or 0

    # By status
    by_status: dict[str, int] = {}
    for status in EmailStatus:
        status_stmt = select(func.count(Email.id)).where(Email.status == status)
        status_result = await db.execute(status_stmt)
        by_status[status.value] = status_result.scalar() or 0

    # By sequence step
    by_sequence_step: dict[str, int] = {}
    for step in EmailSequenceStep:
        step_stmt = select(func.count(Email.id)).where(Email.sequence_step == step)
        step_result = await db.execute(step_stmt)
        by_sequence_step[step.name] = step_result.scalar() or 0

    # Total opens and clicks
    opens_stmt = select(func.sum(Email.open_count))
    opens_result = await db.execute(opens_stmt)
    total_opens = opens_result.scalar() or 0

    clicks_stmt = select(func.sum(Email.click_count))
    clicks_result = await db.execute(clicks_stmt)
    total_clicks = clicks_result.scalar() or 0

    # Leads sequenced
    sequenced_stmt = select(func.count(Lead.id)).where(
        Lead.status == LeadStatus.SEQUENCED
    )
    sequenced_result = await db.execute(sequenced_stmt)
    leads_sequenced = sequenced_result.scalar() or 0

    # Leads pending (scored but not sequenced)
    pending_stmt = select(func.count(Lead.id)).where(
        Lead.status == LeadStatus.QUALIFIED,
        Lead.icp_score >= 60,
    )
    pending_result = await db.execute(pending_stmt)
    leads_pending = pending_result.scalar() or 0

    return EmailStatsResponse(
        total_emails=total_emails,
        by_status=by_status,
        by_sequence_step=by_sequence_step,
        total_opens=total_opens,
        total_clicks=total_clicks,
        leads_sequenced=leads_sequenced,
        leads_pending=leads_pending,
    )


@router.get("/pending")
async def get_pending_emails(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get emails pending generation.

    Returns qualified leads that don't have email sequences yet.
    """
    stmt = (
        select(Lead)
        .where(
            Lead.status == LeadStatus.QUALIFIED,
            Lead.icp_score >= 60,
        )
        .order_by(Lead.icp_score.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    leads = result.scalars().all()

    return {
        "leads": [
            {
                "id": lead.id,
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "email": lead.email,
                "company_id": lead.company_id,
                "icp_score": lead.icp_score,
                "classification": lead.classification.value if lead.classification else None,
            }
            for lead in leads
        ],
        "count": len(leads),
    }


# =============================================================================
# GENERATION ROUTES
# =============================================================================

@router.post("/generate/{lead_id}", response_model=SequenceResponse)
async def generate_sequence(
    lead_id: int,
    request: GenerateSequenceRequest = GenerateSequenceRequest(),
    db: AsyncSession = Depends(get_db),
    generator: EmailGenerator = Depends(get_generator),
) -> SequenceResponse:
    """Generate email sequence for a single lead.

    Creates 4 personalized emails (initial, followup1, followup2, breakup)
    and saves them to the database.
    """
    # Get lead
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Check if lead already has emails
    existing_stmt = select(func.count(Email.id)).where(Email.lead_id == lead_id)
    existing_result = await db.execute(existing_stmt)
    existing_count = existing_result.scalar() or 0

    if existing_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Lead already has {existing_count} emails. Use regenerate endpoint to replace.",
        )

    # Get company
    company = await db.get(Company, lead.company_id) if lead.company_id else None

    # Generate sequence
    sequence = await generator.generate_and_save_sequence(
        db=db,
        lead=lead,
        company=company,
        additional_context=request.additional_context,
        start_date=request.start_date,
    )

    return SequenceResponse(
        lead_id=sequence.lead_id,
        emails=[
            GeneratedEmailResponse(
                subject=email.subject,
                body=email.body,
                preview_text=email.preview_text,
                email_type=email.email_type,
                sequence_step=email.sequence_step,
                word_count=email.word_count,
                scheduled_for=email.scheduled_for,
            )
            for email in sequence.emails
        ],
        total_tokens=sequence.total_tokens,
        estimated_cost=sequence.estimated_cost,
        success=sequence.success,
        errors=sequence.errors,
    )


@router.post("/generate/batch", response_model=BatchJobResponse)
async def generate_batch(
    request: GenerateBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> BatchJobResponse:
    """Start batch email generation job.

    Generates email sequences for multiple qualified leads.
    Uses Celery for async processing.
    """
    from src.workers.email_tasks import generate_batch_task

    # Count leads to process
    if request.lead_ids:
        stmt = select(func.count(Lead.id)).where(
            Lead.id.in_(request.lead_ids),
            Lead.status != LeadStatus.SEQUENCED,
        )
    else:
        stmt = select(func.count(Lead.id)).where(
            Lead.icp_score >= request.min_score,
            Lead.status == LeadStatus.QUALIFIED,
        )

    result = await db.execute(stmt)
    count = result.scalar() or 0

    if count == 0:
        raise HTTPException(
            status_code=400,
            detail="No eligible leads found for email generation",
        )

    # Limit count
    actual_count = min(count, request.limit)

    # Start Celery task
    task = generate_batch_task.delay(
        lead_ids=request.lead_ids,
        min_score=request.min_score,
        limit=request.limit,
        additional_context=request.additional_context,
    )

    return BatchJobResponse(
        job_id=task.id,
        status="started",
        message=f"Email generation started for {actual_count} leads",
        leads_count=actual_count,
    )


# =============================================================================
# LEAD-SPECIFIC ROUTES
# =============================================================================

@router.get("/lead/{lead_id}", response_model=LeadEmailsResponse)
async def get_lead_emails(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
) -> LeadEmailsResponse:
    """Get email sequence for a specific lead."""
    # Get lead with company
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    company = await db.get(Company, lead.company_id) if lead.company_id else None

    # Get emails
    stmt = (
        select(Email)
        .where(Email.lead_id == lead_id)
        .order_by(Email.sequence_step)
    )
    result = await db.execute(stmt)
    emails = result.scalars().all()

    return LeadEmailsResponse(
        lead_id=lead_id,
        lead_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or "Unknown",
        lead_email=lead.email,
        company_name=company.name if company else None,
        status=lead.status.value,
        emails=[
            EmailReadResponse(
                id=email.id,
                lead_id=email.lead_id,
                sequence_step=email.sequence_step.name,
                scheduled_day=email.scheduled_day,
                subject=email.subject,
                body_text=email.body_text,
                body_html=email.body_html,
                tracking_id=email.tracking_id,
                status=email.status.value,
                scheduled_at=email.scheduled_at,
                sent_at=email.sent_at,
                opened_at=email.opened_at,
                clicked_at=email.clicked_at,
                replied_at=email.replied_at,
                open_count=email.open_count,
                click_count=email.click_count,
            )
            for email in emails
        ],
        total_emails=len(emails),
    )


# =============================================================================
# PARAMETERIZED EMAIL ROUTES - Must come after static routes
# =============================================================================

@router.get("/{email_id}", response_model=EmailReadResponse)
async def get_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
) -> EmailReadResponse:
    """Get a specific email by ID."""
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    return EmailReadResponse(
        id=email.id,
        lead_id=email.lead_id,
        sequence_step=email.sequence_step.name,
        scheduled_day=email.scheduled_day,
        subject=email.subject,
        body_text=email.body_text,
        body_html=email.body_html,
        tracking_id=email.tracking_id,
        status=email.status.value,
        scheduled_at=email.scheduled_at,
        sent_at=email.sent_at,
        opened_at=email.opened_at,
        clicked_at=email.clicked_at,
        replied_at=email.replied_at,
        open_count=email.open_count,
        click_count=email.click_count,
    )


@router.put("/{email_id}", response_model=EmailReadResponse)
async def update_email(
    email_id: int,
    request: EmailUpdateRequest,
    db: AsyncSession = Depends(get_db),
    generator: EmailGenerator = Depends(get_generator),
) -> EmailReadResponse:
    """Update an email's content.

    Only allows editing PENDING emails.
    """
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if email.status != EmailStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit email with status '{email.status.value}'. Only PENDING emails can be edited.",
        )

    # Update fields
    if request.subject is not None:
        email.subject = request.subject
    if request.body_text is not None:
        email.body_text = request.body_text
        email.body_html = generator._text_to_html(request.body_text)
    if request.scheduled_at is not None:
        email.scheduled_at = request.scheduled_at

    db.add(email)
    await db.commit()
    await db.refresh(email)

    return EmailReadResponse(
        id=email.id,
        lead_id=email.lead_id,
        sequence_step=email.sequence_step.name,
        scheduled_day=email.scheduled_day,
        subject=email.subject,
        body_text=email.body_text,
        body_html=email.body_html,
        tracking_id=email.tracking_id,
        status=email.status.value,
        scheduled_at=email.scheduled_at,
        sent_at=email.sent_at,
        opened_at=email.opened_at,
        clicked_at=email.clicked_at,
        replied_at=email.replied_at,
        open_count=email.open_count,
        click_count=email.click_count,
    )


@router.post("/{email_id}/regenerate", response_model=GeneratedEmailResponse)
async def regenerate_email(
    email_id: int,
    request: RegenerateEmailRequest = RegenerateEmailRequest(),
    db: AsyncSession = Depends(get_db),
    generator: EmailGenerator = Depends(get_generator),
) -> GeneratedEmailResponse:
    """Regenerate a specific email.

    Generates new content using AI and updates the email.
    Only works for PENDING emails.
    """
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if email.status != EmailStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot regenerate email with status '{email.status.value}'. Only PENDING emails can be regenerated.",
        )

    # Get lead
    lead = await db.get(Lead, email.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found for email")

    # Get company
    company = await db.get(Company, lead.company_id) if lead.company_id else None

    # Regenerate
    generated = await generator.regenerate_email(
        db=db,
        email=email,
        lead=lead,
        company=company,
    )

    return GeneratedEmailResponse(
        id=email.id,
        subject=generated.subject,
        body=generated.body,
        preview_text=generated.preview_text,
        email_type=generated.email_type,
        sequence_step=generated.sequence_step,
        word_count=generated.word_count,
        scheduled_for=email.scheduled_at,
    )


@router.delete("/{email_id}")
async def delete_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an email.

    Only allows deleting PENDING emails.
    """
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if email.status != EmailStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete email with status '{email.status.value}'. Only PENDING emails can be deleted.",
        )

    await db.delete(email)
    await db.commit()

    return {"status": "deleted", "email_id": email_id}
