"""Celery tasks for ICP scoring operations."""

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
def score_lead_task(
    self: Any,
    lead_id: int,
) -> dict[str, Any]:
    """Score a single lead.

    Args:
        self: Celery task instance.
        lead_id: Lead ID to score.

    Returns:
        Dictionary with scoring results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.scoring import ICPScorer

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

            scorer = ICPScorer()
            result = await scorer.score_lead(session, lead, company, save=True)

            return {
                "success": True,
                "lead_id": lead_id,
                "score": result.score,
                "classification": result.classification.value,
                "qualified": result.qualified,
                "breakdown": result.breakdown.to_dict(),
                "errors": result.errors,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def score_batch_task(
    self: Any,
    lead_ids: list[int] | None = None,
    status_filter: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Score a batch of leads.

    Args:
        self: Celery task instance.
        lead_ids: Specific lead IDs to score (optional).
        status_filter: Filter by lead status (default: ENRICHED, NEW).
        limit: Maximum leads to process.

    Returns:
        Dictionary with batch results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.scoring import ICPScorer

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get leads to score
            if lead_ids:
                leads = []
                for lid in lead_ids[:limit]:
                    lead = await session.get(Lead, lid)
                    if lead:
                        leads.append(lead)
            else:
                # Get leads by status (unscored)
                if status_filter:
                    target_status = LeadStatus(status_filter.upper())
                    stmt = (
                        select(Lead)
                        .where(Lead.status == target_status)
                        .where(Lead.icp_score.is_(None))
                        .limit(limit)
                    )
                else:
                    # Default: get all unscored leads with status NEW or ENRICHED
                    stmt = (
                        select(Lead)
                        .where(Lead.status.in_([LeadStatus.NEW, LeadStatus.ENRICHED]))
                        .where(Lead.icp_score.is_(None))
                        .order_by(Lead.created_at.desc())
                        .limit(limit)
                    )
                result = await session.execute(stmt)
                leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "leads_processed": 0,
                    "message": "No leads to score",
                }

            scorer = ICPScorer()
            results = await scorer.score_batch(session, leads)

            # Aggregate results
            qualified_count = sum(1 for r in results if r.qualified)
            avg_score = sum(r.score for r in results) / len(results) if results else 0

            # Count by classification
            by_classification: dict[str, int] = {}
            for r in results:
                cls = r.classification.value
                by_classification[cls] = by_classification.get(cls, 0) + 1

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "leads_processed": len(leads),
                "qualified_count": qualified_count,
                "average_score": round(avg_score, 1),
                "by_classification": by_classification,
                "duration_seconds": duration,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def run_daily_scoring(self: Any) -> dict[str, Any]:
    """Run daily scoring job on unscored leads.

    This task should be scheduled to run daily after enrichment.

    Returns:
        Dictionary with job results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.scoring import ICPScorer

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            # Get all unscored leads with status ENRICHED
            stmt = (
                select(Lead)
                .where(Lead.status == LeadStatus.ENRICHED)
                .where(Lead.icp_score.is_(None))
                .order_by(Lead.created_at.desc())
                .limit(500)  # Process up to 500 per day
            )
            result = await session.execute(stmt)
            leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "message": "No unscored leads found",
                    "leads_processed": 0,
                }

            scorer = ICPScorer()
            results = await scorer.score_batch(session, leads)

            qualified_count = sum(1 for r in results if r.qualified)
            avg_score = sum(r.score for r in results) / len(results) if results else 0

            by_classification: dict[str, int] = {}
            for r in results:
                cls = r.classification.value
                by_classification[cls] = by_classification.get(cls, 0) + 1

            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "leads_processed": len(leads),
                "qualified_count": qualified_count,
                "average_score": round(avg_score, 1),
                "by_classification": by_classification,
                "duration_seconds": duration,
            }

    return asyncio.run(_run())


@shared_task
def rescore_leads_by_classification(
    classification: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Re-score leads with a specific classification.

    Useful when scoring configuration changes.

    Args:
        classification: Classification to re-score (HOT, WARM, COOL, COLD).
        limit: Maximum leads to process.

    Returns:
        Dictionary with results.
    """
    async def _run() -> dict[str, Any]:
        from src.models.lead import LeadClassification
        from src.services.scoring import ICPScorer

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            target_classification = LeadClassification(classification.upper())

            stmt = (
                select(Lead)
                .where(Lead.classification == target_classification)
                .limit(limit)
            )
            result = await session.execute(stmt)
            leads = list(result.scalars().all())

            if not leads:
                return {
                    "success": True,
                    "leads_processed": 0,
                    "message": f"No leads with classification {classification}",
                }

            scorer = ICPScorer()
            results = await scorer.score_batch(session, leads)

            # Track classification changes
            changed_count = 0
            for r, lead in zip(results, leads):
                if r.classification != target_classification:
                    changed_count += 1

            qualified_count = sum(1 for r in results if r.qualified)
            duration = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "leads_processed": len(leads),
                "original_classification": classification,
                "classifications_changed": changed_count,
                "qualified_count": qualified_count,
                "duration_seconds": duration,
            }

    return asyncio.run(_run())
