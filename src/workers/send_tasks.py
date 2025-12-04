"""Celery tasks for email sending operations."""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.models.email import Email, EmailStatus
from src.models.lead import Lead


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_email_task(
    self: Any,
    email_id: int,
) -> dict[str, Any]:
    """Send a single email.

    Args:
        self: Celery task instance.
        email_id: Email ID to send.

    Returns:
        Dictionary with send results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import EmailSender, SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            email = await session.get(Email, email_id)
            if not email:
                return {
                    "success": False,
                    "email_id": email_id,
                    "error": "Email not found",
                }

            if email.status != EmailStatus.PENDING:
                return {
                    "success": False,
                    "email_id": email_id,
                    "error": f"Email status is {email.status.value}, not PENDING",
                }

            # Check if we can send now
            scheduler = SchedulerService()
            can_send, reason = await scheduler.can_send_now(session)
            if not can_send:
                return {
                    "success": False,
                    "email_id": email_id,
                    "error": reason,
                    "should_retry": True,
                }

            sender = EmailSender()
            result = await sender.send_email(session, email)

            return {
                "success": result.success,
                "email_id": email_id,
                "message_id": result.message_id,
                "tracking_id": result.tracking_id,
                "error": result.error,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def send_batch_task(
    self: Any,
    limit: int | None = None,
    respect_business_hours: bool = True,
) -> dict[str, Any]:
    """Send batch of pending emails.

    Args:
        self: Celery task instance.
        limit: Maximum emails to send.
        respect_business_hours: Whether to check business hours.

    Returns:
        Dictionary with batch results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import EmailSender, SchedulerService

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            scheduler = SchedulerService()

            # Check if we can send
            if respect_business_hours and not scheduler.is_business_hours():
                next_slot = scheduler.get_next_business_hour()
                return {
                    "success": False,
                    "error": "Outside business hours",
                    "next_slot": next_slot.isoformat(),
                    "emails_sent": 0,
                }

            # Get emails to send
            emails = await scheduler.get_emails_to_send(session, limit)
            if not emails:
                return {
                    "success": True,
                    "message": "No emails ready to send",
                    "emails_sent": 0,
                }

            sender = EmailSender()
            results = await sender.send_batch(
                session,
                emails,
                delay_between=scheduler.get_random_delay(),
            )

            success_count = sum(1 for r in results if r.success)
            error_count = len(results) - success_count
            errors = [r.error for r in results if r.error]

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": error_count == 0,
                "emails_sent": success_count,
                "errors": error_count,
                "error_messages": errors[:10],
                "duration_seconds": duration,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def process_send_queue(self: Any) -> dict[str, Any]:
    """Process the email send queue.

    This is the main task that runs periodically during business hours
    to send pending emails with appropriate delays.

    Returns:
        Dictionary with processing results.
    """
    async def _run() -> dict[str, Any]:
        import random
        from src.services.email import EmailSender, SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()

            # Check business hours
            if not scheduler.is_business_hours():
                next_slot = scheduler.get_next_business_hour()
                return {
                    "success": True,
                    "message": "Outside business hours",
                    "next_slot": next_slot.isoformat(),
                    "emails_sent": 0,
                }

            # Check rate limit
            rate_status = await scheduler.check_daily_limit(session)
            if not rate_status.can_send:
                return {
                    "success": True,
                    "message": f"Daily limit reached ({rate_status.daily_limit})",
                    "reset_at": rate_status.reset_at.isoformat(),
                    "emails_sent": 0,
                }

            # Get one email to send (we process one at a time with random delays)
            emails = await scheduler.get_emails_to_send(session, limit=1)
            if not emails:
                return {
                    "success": True,
                    "message": "No emails ready to send",
                    "emails_sent": 0,
                }

            email = emails[0]
            sender = EmailSender()
            result = await sender.send_email(session, email)

            # Schedule next check with random delay
            delay = scheduler.get_random_delay()
            process_send_queue.apply_async(countdown=delay)

            return {
                "success": result.success,
                "email_id": email.id,
                "message_id": result.message_id,
                "error": result.error,
                "next_check_in_seconds": delay,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def start_send_queue(self: Any) -> dict[str, Any]:
    """Start the email send queue processor.

    This kicks off the send queue processing loop.

    Returns:
        Dictionary with start status.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()

            # Check if we can start now
            if not scheduler.is_business_hours():
                next_slot = scheduler.get_next_business_hour()
                # Schedule for next business hour
                delay = (next_slot - scheduler.get_current_time_cet()).total_seconds()
                process_send_queue.apply_async(countdown=max(0, delay))
                return {
                    "success": True,
                    "message": "Send queue scheduled for next business hours",
                    "starts_at": next_slot.isoformat(),
                }

            # Start processing now
            process_send_queue.delay()
            return {
                "success": True,
                "message": "Send queue started",
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def schedule_lead_sequence(
    self: Any,
    lead_id: int,
    start_date: str | None = None,
) -> dict[str, Any]:
    """Schedule send times for a lead's email sequence.

    Args:
        self: Celery task instance.
        lead_id: Lead ID.
        start_date: ISO format start date (optional).

    Returns:
        Dictionary with scheduling results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()

            start_dt = None
            if start_date:
                start_dt = datetime.fromisoformat(start_date)

            scheduled_times = await scheduler.schedule_sequence_emails(
                session,
                lead_id,
                start_dt,
            )

            return {
                "success": True,
                "lead_id": lead_id,
                "emails_scheduled": len(scheduled_times),
                "scheduled_times": [dt.isoformat() for dt in scheduled_times],
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def pause_lead_sequence(
    self: Any,
    lead_id: int,
) -> dict[str, Any]:
    """Pause a lead's email sequence.

    Args:
        self: Celery task instance.
        lead_id: Lead ID.

    Returns:
        Dictionary with pause results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()
            count = await scheduler.pause_sequence(session, lead_id)

            return {
                "success": True,
                "lead_id": lead_id,
                "emails_paused": count,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def resume_lead_sequence(
    self: Any,
    lead_id: int,
) -> dict[str, Any]:
    """Resume a paused email sequence.

    Args:
        self: Celery task instance.
        lead_id: Lead ID.

    Returns:
        Dictionary with resume results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()
            count = await scheduler.resume_sequence(session, lead_id)

            return {
                "success": True,
                "lead_id": lead_id,
                "emails_resumed": count,
            }

    return asyncio.run(_run())


@shared_task
def get_queue_status() -> dict[str, Any]:
    """Get current email queue status.

    Returns:
        Dictionary with queue statistics.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()
            status = await scheduler.get_queue_status(session)
            return status

    return asyncio.run(_run())


@shared_task(bind=True)
def run_business_hours_send(self: Any) -> dict[str, Any]:
    """Run email sending during business hours.

    This task is scheduled via beat to run during business hours.
    It checks if sending is appropriate and triggers the send queue.

    Returns:
        Dictionary with job results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import SchedulerService

        session_factory = get_async_session()

        async with session_factory() as session:
            scheduler = SchedulerService()

            # Check business hours
            if not scheduler.is_business_hours():
                return {
                    "success": True,
                    "message": "Outside business hours, skipping",
                }

            # Check rate limit
            rate_status = await scheduler.check_daily_limit(session)
            if not rate_status.can_send:
                return {
                    "success": True,
                    "message": f"Daily limit reached ({rate_status.daily_limit})",
                }

            # Get queue status
            queue_status = await scheduler.get_queue_status(session)

            if queue_status["due_count"] == 0:
                return {
                    "success": True,
                    "message": "No emails due for sending",
                    "pending_count": queue_status["pending_count"],
                }

            # Trigger send queue
            process_send_queue.delay()

            return {
                "success": True,
                "message": "Send queue triggered",
                "due_count": queue_status["due_count"],
                "remaining_today": rate_status.remaining_today,
            }

    return asyncio.run(_run())
