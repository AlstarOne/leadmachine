"""CRUD operations for ScrapeJob model."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.base import CRUDBase
from src.models.company import CompanySource
from src.models.scrape_job import ScrapeJob, ScrapeJobStatus
from src.schemas.scrape_job import ScrapeJobCreate, ScrapeJobUpdate


class CRUDScrapeJob(CRUDBase[ScrapeJob, ScrapeJobCreate, ScrapeJobUpdate]):
    """CRUD operations for ScrapeJob."""

    async def get_by_status(
        self,
        db: AsyncSession,
        *,
        status: ScrapeJobStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ScrapeJob]:
        """Get scrape jobs by status."""
        result = await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.status == status)
            .order_by(ScrapeJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_source(
        self,
        db: AsyncSession,
        *,
        source: CompanySource,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ScrapeJob]:
        """Get scrape jobs by source."""
        result = await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.source == source)
            .order_by(ScrapeJob.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_pending(
        self,
        db: AsyncSession,
        *,
        limit: int = 10,
    ) -> list[ScrapeJob]:
        """Get pending scrape jobs."""
        result = await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.status == ScrapeJobStatus.PENDING)
            .order_by(ScrapeJob.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_running(
        self,
        db: AsyncSession,
    ) -> list[ScrapeJob]:
        """Get currently running scrape jobs."""
        result = await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.status == ScrapeJobStatus.RUNNING)
        )
        return list(result.scalars().all())

    async def start_job(
        self,
        db: AsyncSession,
        *,
        db_obj: ScrapeJob,
        celery_task_id: str | None = None,
    ) -> ScrapeJob:
        """Mark job as started."""
        db_obj.start()
        if celery_task_id:
            db_obj.celery_task_id = celery_task_id
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def complete_job(
        self,
        db: AsyncSession,
        *,
        db_obj: ScrapeJob,
        results_count: int,
        new_count: int,
        duplicate_count: int,
    ) -> ScrapeJob:
        """Mark job as completed with results."""
        db_obj.complete(results_count, new_count, duplicate_count)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def fail_job(
        self,
        db: AsyncSession,
        *,
        db_obj: ScrapeJob,
        error_message: str,
    ) -> ScrapeJob:
        """Mark job as failed with error."""
        db_obj.fail(error_message)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def cancel_job(
        self,
        db: AsyncSession,
        *,
        db_obj: ScrapeJob,
    ) -> ScrapeJob:
        """Mark job as cancelled."""
        db_obj.cancel()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


scrape_job = CRUDScrapeJob(ScrapeJob)
