"""Celery tasks for scraping operations."""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.models.scrape_job import ScrapeJob, ScrapeJobStatus
from src.services.deduplication import DeduplicationService
from src.services.scrapers.base import CompanyRaw, ScraperType, ScrapeResult


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _run_scraper(
    scraper_type: str,
    keywords: list[str],
    filters: dict[str, Any],
    max_pages: int,
) -> ScrapeResult:
    """Run a specific scraper.

    Args:
        scraper_type: Type of scraper to run.
        keywords: Search keywords.
        filters: Search filters.
        max_pages: Maximum pages to scrape.

    Returns:
        ScrapeResult from scraper.
    """
    from src.services.scrapers import (
        IndeedScraper,
        KvKScraper,
        LinkedInScraper,
        TechleapScraper,
    )
    from src.services.scrapers.techleap import DealroomScraper

    scraper_map = {
        ScraperType.INDEED.value: IndeedScraper,
        ScraperType.KVK.value: KvKScraper,
        ScraperType.LINKEDIN.value: LinkedInScraper,
        ScraperType.TECHLEAP.value: TechleapScraper,
        ScraperType.DEALROOM.value: DealroomScraper,
    }

    scraper_class = scraper_map.get(scraper_type)
    if not scraper_class:
        return ScrapeResult(
            success=False,
            errors=[f"Unknown scraper type: {scraper_type}"],
        )

    scraper = scraper_class()
    try:
        result = await scraper.scrape(keywords, filters, max_pages)
        return result
    finally:
        await scraper.close()


async def _save_scraped_companies(
    companies: list[CompanyRaw],
    scrape_job_id: int,
) -> tuple[int, int]:
    """Save scraped companies to database with deduplication.

    Args:
        companies: List of scraped companies.
        scrape_job_id: ID of the scrape job.

    Returns:
        Tuple of (new_count, updated_count).
    """
    session_factory = get_async_session()
    new_count = 0
    updated_count = 0

    async with session_factory() as session:
        dedup_service = DeduplicationService(session)

        for company_raw in companies:
            company, is_new = await dedup_service.find_or_create_company(company_raw)

            # Link to scrape job
            if company.scrape_job_id is None:
                company.scrape_job_id = scrape_job_id
                session.add(company)

            if is_new:
                new_count += 1
            else:
                updated_count += 1

        await session.commit()

    return new_count, updated_count


async def _update_job_status(
    job_id: int,
    status: ScrapeJobStatus,
    results_count: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update scrape job status.

    Args:
        job_id: Job ID.
        status: New status.
        results_count: Number of results found.
        error_message: Error message if failed.
    """
    session_factory = get_async_session()

    async with session_factory() as session:
        job = await session.get(ScrapeJob, job_id)
        if job:
            job.status = status

            if status == ScrapeJobStatus.RUNNING:
                job.started_at = datetime.now()
            elif status in (ScrapeJobStatus.COMPLETED, ScrapeJobStatus.FAILED):
                job.completed_at = datetime.now()

            if results_count is not None:
                job.results_count = results_count

            if error_message:
                job.error_message = error_message

            session.add(job)
            await session.commit()


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def run_scrape_job(
    self: Any,
    job_id: int,
    scraper_type: str,
    keywords: list[str],
    filters: dict[str, Any] | None = None,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Run a scrape job.

    Args:
        self: Celery task instance.
        job_id: Scrape job ID.
        scraper_type: Type of scraper to use.
        keywords: Search keywords.
        filters: Optional filters.
        max_pages: Maximum pages to scrape.

    Returns:
        Dictionary with job results.
    """
    filters = filters or {}

    async def _run() -> dict[str, Any]:
        # Update status to running
        await _update_job_status(job_id, ScrapeJobStatus.RUNNING)

        try:
            # Run scraper
            result = await _run_scraper(scraper_type, keywords, filters, max_pages)

            if not result.success and not result.companies:
                await _update_job_status(
                    job_id,
                    ScrapeJobStatus.FAILED,
                    error_message="; ".join(result.errors[:5]),
                )
                return {
                    "success": False,
                    "job_id": job_id,
                    "errors": result.errors,
                }

            # Save companies
            new_count, updated_count = await _save_scraped_companies(
                result.companies, job_id
            )

            # Update job as completed
            await _update_job_status(
                job_id,
                ScrapeJobStatus.COMPLETED,
                results_count=new_count + updated_count,
            )

            return {
                "success": True,
                "job_id": job_id,
                "new_companies": new_count,
                "updated_companies": updated_count,
                "total_found": result.total_found,
                "pages_scraped": result.pages_scraped,
                "duration_seconds": result.duration_seconds,
                "errors": result.errors,
            }

        except Exception as e:
            await _update_job_status(
                job_id,
                ScrapeJobStatus.FAILED,
                error_message=str(e),
            )
            raise

    return asyncio.run(_run())


@shared_task(bind=True)
def run_daily_scrape(self: Any) -> dict[str, Any]:
    """Run daily scheduled scrape across all sources.

    Returns:
        Dictionary with combined results.
    """
    # Default keywords for Dutch tech companies
    default_keywords = [
        "software",
        "saas",
        "fintech",
        "ai artificial intelligence",
        "machine learning",
        "cloud",
        "startup",
        "scale-up",
    ]

    async def _run() -> dict[str, Any]:
        session_factory = get_async_session()
        results: dict[str, Any] = {}

        scrapers_config = [
            (ScraperType.INDEED.value, {"location": "Nederland"}, 3),
            (ScraperType.KVK.value, {"legal_form": "BV"}, 3),
            (ScraperType.TECHLEAP.value, {}, 5),
        ]

        async with session_factory() as session:
            for scraper_type, filters, max_pages in scrapers_config:
                # Create job record
                job = ScrapeJob(
                    source=scraper_type,
                    keywords=default_keywords,
                    config=filters,
                    status=ScrapeJobStatus.PENDING,
                )
                session.add(job)
                await session.commit()
                await session.refresh(job)

                # Run scraper
                try:
                    result = await _run_scraper(
                        scraper_type, default_keywords, filters, max_pages
                    )

                    if result.companies:
                        new_count, updated_count = await _save_scraped_companies(
                            result.companies, job.id
                        )

                        job.status = ScrapeJobStatus.COMPLETED
                        job.completed_at = datetime.now()
                        job.results_count = new_count + updated_count
                    else:
                        job.status = ScrapeJobStatus.FAILED
                        job.error_message = "; ".join(result.errors[:3])

                    results[scraper_type] = {
                        "job_id": job.id,
                        "success": result.success,
                        "companies_found": result.total_found,
                    }

                except Exception as e:
                    job.status = ScrapeJobStatus.FAILED
                    job.error_message = str(e)
                    results[scraper_type] = {
                        "job_id": job.id,
                        "success": False,
                        "error": str(e),
                    }

                session.add(job)
                await session.commit()

        return results

    return asyncio.run(_run())


@shared_task
def scrape_single_source(
    scraper_type: str,
    keywords: list[str],
    filters: dict[str, Any] | None = None,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Scrape a single source (for manual/API triggered scrapes).

    Args:
        scraper_type: Type of scraper.
        keywords: Search keywords.
        filters: Optional filters.
        max_pages: Maximum pages.

    Returns:
        Scrape results.
    """
    filters = filters or {}

    async def _run() -> dict[str, Any]:
        session_factory = get_async_session()

        async with session_factory() as session:
            # Create job
            job = ScrapeJob(
                source=scraper_type,
                keywords=keywords,
                config=filters,
                status=ScrapeJobStatus.PENDING,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            job.status = ScrapeJobStatus.RUNNING
            job.started_at = datetime.now()
            session.add(job)
            await session.commit()

            try:
                result = await _run_scraper(scraper_type, keywords, filters, max_pages)

                if result.companies:
                    new_count, updated_count = await _save_scraped_companies(
                        result.companies, job.id
                    )

                    job.status = ScrapeJobStatus.COMPLETED
                    job.completed_at = datetime.now()
                    job.results_count = new_count + updated_count
                else:
                    job.status = ScrapeJobStatus.COMPLETED
                    job.results_count = 0

                session.add(job)
                await session.commit()

                return {
                    "success": True,
                    "job_id": job.id,
                    "companies_found": result.total_found,
                    "pages_scraped": result.pages_scraped,
                    "duration": result.duration_seconds,
                    "errors": result.errors,
                }

            except Exception as e:
                job.status = ScrapeJobStatus.FAILED
                job.error_message = str(e)
                session.add(job)
                await session.commit()

                return {
                    "success": False,
                    "job_id": job.id,
                    "error": str(e),
                }

    return asyncio.run(_run())
