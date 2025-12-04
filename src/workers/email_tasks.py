"""Celery tasks for email generation operations."""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.models.company import Company
from src.models.lead import Lead, LeadStatus


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_sequence_task(
    self: Any,
    lead_id: int,
    additional_context: str = "",
) -> dict[str, Any]:
    """Generate email sequence for a single lead.

    Args:
        self: Celery task instance.
        lead_id: Lead ID to generate sequence for.
        additional_context: Additional context for personalization.

    Returns:
        Dictionary with generation results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import EmailGenerator

        session_factory = get_async_session()

        async with session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if not lead:
                return {
                    "success": False,
                    "lead_id": lead_id,
                    "error": "Lead not found",
                }

            # Get company
            company = await session.get(Company, lead.company_id) if lead.company_id else None

            generator = EmailGenerator()
            sequence = await generator.generate_and_save_sequence(
                db=session,
                lead=lead,
                company=company,
                additional_context=additional_context,
            )

            return {
                "success": sequence.success,
                "lead_id": lead_id,
                "emails_generated": len(sequence.emails),
                "total_tokens": sequence.total_tokens,
                "estimated_cost": sequence.estimated_cost,
                "errors": sequence.errors,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def generate_batch_task(
    self: Any,
    lead_ids: list[int] | None = None,
    min_score: int = 60,
    limit: int = 50,
    additional_context: str = "",
) -> dict[str, Any]:
    """Generate email sequences for a batch of leads.

    Args:
        self: Celery task instance.
        lead_ids: Specific lead IDs to process (optional).
        min_score: Minimum ICP score for automatic selection.
        limit: Maximum leads to process.
        additional_context: Additional context for personalization.

    Returns:
        Dictionary with batch results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import EmailGenerator

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get leads to process
            if lead_ids:
                leads = []
                for lid in lead_ids[:limit]:
                    lead = await session.get(Lead, lid)
                    if lead and lead.status != LeadStatus.SEQUENCED:
                        leads.append(lead)
            else:
                # Get scored leads without sequences
                stmt = (
                    select(Lead)
                    .where(Lead.status == LeadStatus.QUALIFIED)
                    .where(Lead.icp_score >= min_score)
                    .order_by(Lead.icp_score.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "leads_processed": 0,
                    "message": "No eligible leads found",
                }

            generator = EmailGenerator()
            total_emails = 0
            total_tokens = 0
            total_cost = 0.0
            success_count = 0
            error_count = 0
            all_errors: list[str] = []

            for lead in leads:
                try:
                    # Get company
                    company = await session.get(Company, lead.company_id) if lead.company_id else None

                    sequence = await generator.generate_and_save_sequence(
                        db=session,
                        lead=lead,
                        company=company,
                        additional_context=additional_context,
                    )

                    total_emails += len(sequence.emails)
                    total_tokens += sequence.total_tokens
                    total_cost += sequence.estimated_cost

                    if sequence.success:
                        success_count += 1
                    else:
                        error_count += 1
                        all_errors.extend([f"Lead {lead.id}: {e}" for e in sequence.errors])

                except Exception as e:
                    error_count += 1
                    all_errors.append(f"Lead {lead.id}: {str(e)}")

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": error_count == 0,
                "leads_processed": len(leads),
                "success_count": success_count,
                "error_count": error_count,
                "total_emails_generated": total_emails,
                "total_tokens": total_tokens,
                "total_estimated_cost": round(total_cost, 4),
                "duration_seconds": duration,
                "errors": all_errors[:10],  # Limit errors to first 10
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def run_daily_email_generation(self: Any) -> dict[str, Any]:
    """Run daily email generation job.

    Generates email sequences for all qualified leads (score >= 60)
    that don't have sequences yet.

    Returns:
        Dictionary with job results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.email import EmailGenerator

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get qualified leads without sequences
            stmt = (
                select(Lead)
                .where(Lead.status == LeadStatus.QUALIFIED)
                .where(Lead.icp_score >= 60)
                .order_by(Lead.icp_score.desc())
                .limit(50)  # Process up to 50 per day
            )
            result = await session.execute(stmt)
            leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "message": "No leads pending email generation",
                    "leads_processed": 0,
                }

            generator = EmailGenerator()
            total_emails = 0
            total_tokens = 0
            total_cost = 0.0
            success_count = 0
            error_count = 0
            all_errors: list[str] = []

            for lead in leads:
                try:
                    company = await session.get(Company, lead.company_id) if lead.company_id else None

                    sequence = await generator.generate_and_save_sequence(
                        db=session,
                        lead=lead,
                        company=company,
                    )

                    total_emails += len(sequence.emails)
                    total_tokens += sequence.total_tokens
                    total_cost += sequence.estimated_cost

                    if sequence.success:
                        success_count += 1
                    else:
                        error_count += 1
                        all_errors.extend([f"Lead {lead.id}: {e}" for e in sequence.errors])

                except Exception as e:
                    error_count += 1
                    all_errors.append(f"Lead {lead.id}: {str(e)}")

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": error_count == 0,
                "leads_processed": len(leads),
                "success_count": success_count,
                "error_count": error_count,
                "total_emails_generated": total_emails,
                "total_tokens": total_tokens,
                "total_estimated_cost": round(total_cost, 4),
                "duration_seconds": duration,
                "errors": all_errors[:10],
            }

    return asyncio.run(_run())


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def regenerate_email_task(
    self: Any,
    email_id: int,
) -> dict[str, Any]:
    """Regenerate a specific email.

    Args:
        self: Celery task instance.
        email_id: Email ID to regenerate.

    Returns:
        Dictionary with regeneration results.
    """
    async def _run() -> dict[str, Any]:
        from src.models.email import Email, EmailStatus
        from src.services.email import EmailGenerator

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
                    "error": f"Cannot regenerate email with status '{email.status.value}'",
                }

            lead = await session.get(Lead, email.lead_id)
            if not lead:
                return {
                    "success": False,
                    "email_id": email_id,
                    "error": "Lead not found for email",
                }

            company = await session.get(Company, lead.company_id) if lead.company_id else None

            generator = EmailGenerator()
            generated = await generator.regenerate_email(
                db=session,
                email=email,
                lead=lead,
                company=company,
            )

            return {
                "success": True,
                "email_id": email_id,
                "new_subject": generated.subject,
                "word_count": generated.word_count,
                "tokens_used": generated.generation_result.total_tokens,
            }

    return asyncio.run(_run())


@shared_task
def check_token_usage() -> dict[str, Any]:
    """Check token usage statistics.

    Returns summary of token usage and estimated costs.

    Returns:
        Dictionary with usage statistics.
    """
    async def _run() -> dict[str, Any]:
        from sqlalchemy import func
        from src.models.email import Email

        session_factory = get_async_session()

        async with session_factory() as session:
            # Count total emails
            total_stmt = select(func.count(Email.id))
            total_result = await session.execute(total_stmt)
            total_emails = total_result.scalar() or 0

            # For token tracking, we'd need to store this in the database
            # For now, return basic stats
            return {
                "total_emails_generated": total_emails,
                "note": "Detailed token tracking requires database schema extension",
            }

    return asyncio.run(_run())
