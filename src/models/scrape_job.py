"""ScrapeJob model for tracking scraping jobs."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.company import CompanySource


class ScrapeJobStatus(str, enum.Enum):
    """Status of a scrape job."""

    PENDING = "PENDING"  # Queued, not yet started
    RUNNING = "RUNNING"  # Currently executing
    COMPLETED = "COMPLETED"  # Finished successfully
    FAILED = "FAILED"  # Finished with errors
    CANCELLED = "CANCELLED"  # Manually cancelled


class ScrapeJob(Base):
    """ScrapeJob model for tracking scraping jobs."""

    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Job configuration
    source: Mapped[CompanySource] = mapped_column(Enum(CompanySource), nullable=False, index=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)  # Search keywords
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Additional filters

    # Status
    status: Mapped[ScrapeJobStatus] = mapped_column(
        Enum(ScrapeJobStatus), default=ScrapeJobStatus.PENDING, index=True
    )

    # Results
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    new_companies_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Celery task info
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<ScrapeJob(id={self.id}, source={self.source}, status={self.status})>"

    def start(self) -> None:
        """Mark job as started."""
        self.status = ScrapeJobStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self, results_count: int, new_count: int, duplicate_count: int) -> None:
        """Mark job as completed with results."""
        self.status = ScrapeJobStatus.COMPLETED
        self.completed_at = datetime.now()
        self.results_count = results_count
        self.new_companies_count = new_count
        self.duplicate_count = duplicate_count

    def fail(self, error_message: str) -> None:
        """Mark job as failed with error."""
        self.status = ScrapeJobStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error_message

    def cancel(self) -> None:
        """Mark job as cancelled."""
        self.status = ScrapeJobStatus.CANCELLED
        self.completed_at = datetime.now()

    @property
    def duration_seconds(self) -> float | None:
        """Calculate job duration in seconds."""
        if self.started_at is None:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()
