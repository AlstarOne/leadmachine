"""Celery tasks for enrichment operations."""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.models.company import Company, CompanyStatus
from src.models.lead import Lead, LeadStatus


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def enrich_company_task(
    self: Any,
    company_id: int,
) -> dict[str, Any]:
    """Enrich a single company.

    Args:
        self: Celery task instance.
        company_id: Company ID to enrich.

    Returns:
        Dictionary with enrichment results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.enrichment import EnrichmentOrchestrator

        session_factory = get_async_session()

        async with session_factory() as session:
            company = await session.get(Company, company_id)
            if not company:
                return {
                    "success": False,
                    "company_id": company_id,
                    "error": "Company not found",
                }

            orchestrator = EnrichmentOrchestrator(session)
            try:
                result = await orchestrator.enrich_company(company)

                return {
                    "success": result.success,
                    "company_id": company_id,
                    "leads_created": result.leads_created,
                    "leads_updated": result.leads_updated,
                    "emails_found": result.emails_found,
                    "team_members_found": result.team_members_found,
                    "duration_seconds": result.duration_seconds,
                    "errors": result.errors,
                }
            finally:
                await orchestrator.close()

    return asyncio.run(_run())


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def enrich_lead_task(
    self: Any,
    lead_id: int,
) -> dict[str, Any]:
    """Enrich a single lead.

    Args:
        self: Celery task instance.
        lead_id: Lead ID to enrich.

    Returns:
        Dictionary with enrichment results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.enrichment import EnrichmentOrchestrator

        session_factory = get_async_session()

        async with session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if not lead:
                return {
                    "success": False,
                    "lead_id": lead_id,
                    "error": "Lead not found",
                }

            orchestrator = EnrichmentOrchestrator(session)
            try:
                result = await orchestrator.enrich_lead(lead)

                return {
                    "success": result.success,
                    "lead_id": lead_id,
                    "email_found": result.email_found,
                    "email": result.email,
                    "email_confidence": result.email_confidence,
                    "linkedin_found": result.linkedin_found,
                    "errors": result.errors,
                }
            finally:
                await orchestrator.close()

    return asyncio.run(_run())


@shared_task(bind=True)
def run_enrichment_batch(
    self: Any,
    company_ids: list[int] | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run enrichment on a batch of companies.

    Args:
        self: Celery task instance.
        company_ids: Specific company IDs to enrich (optional).
        status_filter: Filter by company status (default: NEW).
        limit: Maximum companies to process.

    Returns:
        Dictionary with batch results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.enrichment import EnrichmentOrchestrator

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get companies to enrich
            if company_ids:
                companies = []
                for cid in company_ids[:limit]:
                    company = await session.get(Company, cid)
                    if company:
                        companies.append(company)
            else:
                # Get companies by status
                target_status = CompanyStatus(status_filter.upper()) if status_filter else CompanyStatus.NEW
                stmt = (
                    select(Company)
                    .where(Company.status == target_status)
                    .limit(limit)
                )
                result = await session.execute(stmt)
                companies = list(result.scalars().all())

            if not companies:
                return {
                    "success": True,
                    "companies_processed": 0,
                    "message": "No companies to enrich",
                }

            orchestrator = EnrichmentOrchestrator(session)
            try:
                results = await orchestrator.enrich_batch(companies, max_concurrent=3)

                # Aggregate results
                successful = sum(1 for r in results if r.success)
                total_leads = sum(r.leads_created for r in results)
                total_emails = sum(r.emails_found for r in results)

                duration = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "companies_processed": len(companies),
                    "companies_successful": successful,
                    "total_leads_created": total_leads,
                    "total_emails_found": total_emails,
                    "duration_seconds": duration,
                }
            finally:
                await orchestrator.close()

    return asyncio.run(_run())


@shared_task(bind=True)
def run_daily_enrichment(self: Any) -> dict[str, Any]:
    """Run daily enrichment job on new companies.

    Returns:
        Dictionary with job results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.enrichment import EnrichmentOrchestrator

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get all NEW companies
            stmt = (
                select(Company)
                .where(Company.status == CompanyStatus.NEW)
                .where(Company.domain.isnot(None))
                .order_by(Company.created_at.desc())
                .limit(100)  # Process up to 100 per day
            )
            result = await session.execute(stmt)
            companies = list(result.scalars().all())

            if not companies:
                return {
                    "success": True,
                    "message": "No new companies to enrich",
                    "companies_processed": 0,
                }

            orchestrator = EnrichmentOrchestrator(session)
            try:
                results = await orchestrator.enrich_batch(companies, max_concurrent=3)

                successful = sum(1 for r in results if r.success)
                total_leads = sum(r.leads_created for r in results)
                total_emails = sum(r.emails_found for r in results)
                enriched = sum(1 for r in results if r.emails_found > 0)

                duration = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "companies_processed": len(companies),
                    "companies_successful": successful,
                    "companies_enriched": enriched,
                    "total_leads_created": total_leads,
                    "total_emails_found": total_emails,
                    "duration_seconds": duration,
                }
            finally:
                await orchestrator.close()

    return asyncio.run(_run())


@shared_task
def enrich_leads_without_email(limit: int = 50) -> dict[str, Any]:
    """Enrich leads that don't have email addresses.

    Args:
        limit: Maximum leads to process.

    Returns:
        Dictionary with results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.enrichment import EnrichmentOrchestrator

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get leads without email
            stmt = (
                select(Lead)
                .where(Lead.email.is_(None))
                .where(Lead.first_name.isnot(None))
                .where(Lead.last_name.isnot(None))
                .limit(limit)
            )
            result = await session.execute(stmt)
            leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "leads_processed": 0,
                    "message": "No leads to enrich",
                }

            orchestrator = EnrichmentOrchestrator(session)
            emails_found = 0

            try:
                for lead in leads:
                    result = await orchestrator.enrich_lead(lead)
                    if result.email_found:
                        emails_found += 1

                await session.commit()

                duration = (datetime.now() - start_time).total_seconds()

                return {
                    "success": True,
                    "leads_processed": len(leads),
                    "emails_found": emails_found,
                    "duration_seconds": duration,
                }
            finally:
                await orchestrator.close()

    return asyncio.run(_run())
