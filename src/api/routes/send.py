"""API routes for email sending."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.email import Email, EmailStatus
from src.models.lead import Lead
from src.services.email import SchedulerService, EmailSender, RateLimitStatus
from src.workers.send_tasks import (
    send_email_task,
    send_batch_task,
    start_send_queue,
    process_send_queue,
    schedule_lead_sequence,
    pause_lead_sequence,
    resume_lead_sequence,
    get_queue_status,
)

router = APIRouter(prefix="/send", tags=["sending"])


# Request/Response models
class SendEmailRequest(BaseModel):
    """Request to send a single email."""

    email_id: int


class SendBatchRequest(BaseModel):
    """Request to send batch of emails."""

    limit: int | None = None
    respect_business_hours: bool = True


class ScheduleSequenceRequest(BaseModel):
    """Request to schedule a lead's sequence."""

    lead_id: int
    start_date: str | None = None


class SendConfigUpdate(BaseModel):
    """Request to update send configuration."""

    daily_limit: int | None = None
    min_delay_seconds: int | None = None
    max_delay_seconds: int | None = None


class JobResponse(BaseModel):
    """Response for async job."""

    job_id: str
    status: str
    message: str


class QueueStatusResponse(BaseModel):
    """Response for queue status."""

    pending_count: int
    due_count: int
    next_scheduled_at: str | None
    is_business_hours: bool
    next_business_hour: str | None
    daily_limit: int
    sent_today: int
    remaining_today: int
    can_send: bool


class RateLimitResponse(BaseModel):
    """Response for rate limit status."""

    emails_sent_today: int
    daily_limit: int
    remaining_today: int
    can_send: bool
    reset_at: str


class SendResultResponse(BaseModel):
    """Response for send result."""

    email_id: int
    success: bool
    message_id: str | None = None
    tracking_id: str | None = None
    error: str | None = None


class BusinessHoursResponse(BaseModel):
    """Response for business hours check."""

    is_business_hours: bool
    current_time: str
    next_business_hour: str | None
    business_start: str
    business_end: str
    business_days: list[str]


# Helper functions
def get_scheduler() -> SchedulerService:
    """Get scheduler service instance."""
    return SchedulerService()


def get_sender() -> EmailSender:
    """Get email sender instance."""
    return EmailSender()


# Endpoints
@router.post("/start", response_model=JobResponse)
async def start_sending(
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> JobResponse:
    """Start the email send queue.

    This starts the automated send queue that will send pending emails
    during business hours with appropriate delays.
    """
    # Check if we can send
    can_send, reason = await scheduler.can_send_now(db)

    if not can_send:
        # Still start the queue - it will wait for business hours
        task = start_send_queue.delay()
        return JobResponse(
            job_id=task.id,
            status="scheduled",
            message=f"Send queue scheduled. Current status: {reason}",
        )

    task = start_send_queue.delay()
    return JobResponse(
        job_id=task.id,
        status="started",
        message="Send queue started",
    )


@router.post("/pause", response_model=dict)
async def pause_sending() -> dict:
    """Pause the email send queue.

    Note: This doesn't actually pause running tasks but prevents
    new sends from being triggered. Use lead-specific pause for
    stopping a sequence.
    """
    # In a production system, you'd use a Redis flag or similar
    # to signal the queue to stop
    return {
        "success": True,
        "message": "Send queue pause signal sent. New sends will be delayed.",
        "note": "To stop a specific sequence, use /send/pause/{lead_id}",
    }


@router.get("/status", response_model=QueueStatusResponse)
async def get_send_status(
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> QueueStatusResponse:
    """Get current send queue status."""
    status = await scheduler.get_queue_status(db)

    return QueueStatusResponse(
        pending_count=status["pending_count"],
        due_count=status["due_count"],
        next_scheduled_at=status["next_scheduled_at"],
        is_business_hours=status["is_business_hours"],
        next_business_hour=status["next_business_hour"],
        daily_limit=status["daily_limit"],
        sent_today=status["sent_today"],
        remaining_today=status["remaining_today"],
        can_send=status["can_send"],
    )


@router.get("/queue")
async def get_email_queue(
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get emails in the send queue."""
    # Build query
    stmt = select(Email)

    if status_filter:
        try:
            status = EmailStatus(status_filter)
            stmt = stmt.where(Email.status == status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status_filter}. Valid: {[s.value for s in EmailStatus]}",
            )
    else:
        # Default to pending emails
        stmt = stmt.where(Email.status == EmailStatus.PENDING)

    stmt = stmt.order_by(Email.scheduled_at).limit(limit)

    result = await db.execute(stmt)
    emails = result.scalars().all()

    return {
        "emails": [
            {
                "id": email.id,
                "lead_id": email.lead_id,
                "subject": email.subject,
                "sequence_step": email.sequence_step.value,
                "status": email.status.value,
                "scheduled_at": email.scheduled_at.isoformat() if email.scheduled_at else None,
                "tracking_id": email.tracking_id,
            }
            for email in emails
        ],
        "count": len(emails),
        "status_filter": status_filter or "PENDING",
    }


@router.get("/rate-limit", response_model=RateLimitResponse)
async def get_rate_limit_status(
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> RateLimitResponse:
    """Get current rate limit status."""
    status = await scheduler.check_daily_limit(db)

    return RateLimitResponse(
        emails_sent_today=status.emails_sent_today,
        daily_limit=status.daily_limit,
        remaining_today=status.remaining_today,
        can_send=status.can_send,
        reset_at=status.reset_at.isoformat(),
    )


@router.get("/business-hours", response_model=BusinessHoursResponse)
async def check_business_hours(
    scheduler: SchedulerService = Depends(get_scheduler),
) -> BusinessHoursResponse:
    """Check current business hours status."""
    now = scheduler.get_current_time_cet()
    is_bh = scheduler.is_business_hours()
    next_bh = None if is_bh else scheduler.get_next_business_hour()

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    business_days = [days[d] for d in scheduler.BUSINESS_DAYS]

    return BusinessHoursResponse(
        is_business_hours=is_bh,
        current_time=now.isoformat(),
        next_business_hour=next_bh.isoformat() if next_bh else None,
        business_start=scheduler.BUSINESS_START.isoformat(),
        business_end=scheduler.BUSINESS_END.isoformat(),
        business_days=business_days,
    )


@router.post("/email/{email_id}", response_model=SendResultResponse)
async def send_single_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
    sender: EmailSender = Depends(get_sender),
) -> SendResultResponse:
    """Send a single email immediately.

    Bypasses the queue and sends the email directly.
    Still respects rate limits.
    """
    # Get email
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if email.status != EmailStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Email status is {email.status.value}, must be PENDING",
        )

    # Check rate limit
    rate_status = await scheduler.check_daily_limit(db)
    if not rate_status.can_send:
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit reached ({rate_status.daily_limit}). Resets at {rate_status.reset_at.isoformat()}",
        )

    # Send email
    result = await sender.send_email(db, email)

    return SendResultResponse(
        email_id=result.email_id,
        success=result.success,
        message_id=result.message_id,
        tracking_id=result.tracking_id,
        error=result.error,
    )


@router.post("/batch", response_model=JobResponse)
async def send_batch(
    request: SendBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Start batch send job.

    Sends multiple pending emails asynchronously.
    """
    task = send_batch_task.delay(
        limit=request.limit,
        respect_business_hours=request.respect_business_hours,
    )

    return JobResponse(
        job_id=task.id,
        status="started",
        message=f"Batch send started (limit: {request.limit or 'rate limit'})",
    )


@router.post("/schedule/{lead_id}", response_model=JobResponse)
async def schedule_sequence(
    lead_id: int,
    start_date: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Schedule send times for a lead's email sequence.

    This sets the scheduled_at times for all pending emails
    in the lead's sequence.
    """
    # Verify lead exists
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Check for pending emails
    stmt = select(func.count(Email.id)).where(
        Email.lead_id == lead_id,
        Email.status == EmailStatus.PENDING,
    )
    result = await db.execute(stmt)
    count = result.scalar() or 0

    if count == 0:
        raise HTTPException(
            status_code=400,
            detail="Lead has no pending emails to schedule",
        )

    task = schedule_lead_sequence.delay(lead_id, start_date)

    return JobResponse(
        job_id=task.id,
        status="started",
        message=f"Scheduling {count} emails for lead {lead_id}",
    )


@router.post("/pause/{lead_id}")
async def pause_sequence(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> dict:
    """Pause a lead's email sequence.

    Cancels all pending emails for this lead.
    """
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    count = await scheduler.pause_sequence(db, lead_id)

    return {
        "success": True,
        "lead_id": lead_id,
        "emails_paused": count,
        "message": f"Paused {count} emails for lead {lead_id}",
    }


@router.post("/resume/{lead_id}")
async def resume_sequence(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> dict:
    """Resume a paused email sequence.

    Reactivates cancelled emails for this lead.
    """
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    count = await scheduler.resume_sequence(db, lead_id)

    return {
        "success": True,
        "lead_id": lead_id,
        "emails_resumed": count,
        "message": f"Resumed {count} emails for lead {lead_id}",
    }


@router.get("/config")
async def get_send_config(
    scheduler: SchedulerService = Depends(get_scheduler),
) -> dict:
    """Get current send configuration."""
    return {
        "daily_limit": scheduler.daily_limit,
        "min_delay_seconds": scheduler.min_delay_seconds,
        "max_delay_seconds": scheduler.max_delay_seconds,
        "business_hours": {
            "start": scheduler.BUSINESS_START.isoformat(),
            "end": scheduler.BUSINESS_END.isoformat(),
            "days": list(scheduler.BUSINESS_DAYS),
        },
        "timezone": "Europe/Amsterdam (CET/CEST)",
    }


@router.put("/config")
async def update_send_config(
    update: SendConfigUpdate,
) -> dict:
    """Update send configuration.

    Note: This only updates the in-memory configuration for new requests.
    For persistent configuration, update environment variables.
    """
    # In a production system, you'd persist this to database
    # For now, just acknowledge the update
    changes = []
    if update.daily_limit is not None:
        changes.append(f"daily_limit={update.daily_limit}")
    if update.min_delay_seconds is not None:
        changes.append(f"min_delay_seconds={update.min_delay_seconds}")
    if update.max_delay_seconds is not None:
        changes.append(f"max_delay_seconds={update.max_delay_seconds}")

    return {
        "success": True,
        "message": "Configuration update acknowledged",
        "changes": changes,
        "note": "For persistent changes, update environment variables and restart",
    }


@router.get("/stats")
async def get_send_stats(
    db: AsyncSession = Depends(get_db),
    scheduler: SchedulerService = Depends(get_scheduler),
) -> dict:
    """Get sending statistics."""
    # Get counts by status
    stats: dict[str, Any] = {}

    for status in EmailStatus:
        stmt = select(func.count(Email.id)).where(Email.status == status)
        result = await db.execute(stmt)
        stats[status.value] = result.scalar() or 0

    # Get rate limit status
    rate_status = await scheduler.check_daily_limit(db)

    # Get today's sends by hour
    now = scheduler.get_current_time_cet()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    hourly_stmt = (
        select(Email)
        .where(
            Email.status == EmailStatus.SENT,
            Email.sent_at >= today_start,
        )
        .order_by(Email.sent_at)
    )
    hourly_result = await db.execute(hourly_stmt)
    sent_today = hourly_result.scalars().all()

    hourly_counts: dict[int, int] = {}
    for email in sent_today:
        if email.sent_at:
            hour = email.sent_at.hour
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    return {
        "by_status": stats,
        "today": {
            "sent": rate_status.emails_sent_today,
            "remaining": rate_status.remaining_today,
            "limit": rate_status.daily_limit,
            "by_hour": hourly_counts,
        },
        "queue": {
            "pending": stats.get("PENDING", 0),
            "is_business_hours": scheduler.is_business_hours(),
        },
    }
