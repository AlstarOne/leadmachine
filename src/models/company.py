"""Company model for storing scraped company data."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.lead import Lead
    from src.models.scrape_job import ScrapeJob


class CompanyStatus(str, enum.Enum):
    """Status of a company in the pipeline."""

    NEW = "NEW"  # Just scraped, not yet enriched
    ENRICHING = "ENRICHING"  # Currently being enriched
    ENRICHED = "ENRICHED"  # Enrichment complete
    NO_CONTACT = "NO_CONTACT"  # Could not find contact info
    DISQUALIFIED = "DISQUALIFIED"  # Does not meet ICP criteria
    ARCHIVED = "ARCHIVED"  # Manually archived


class CompanySource(str, enum.Enum):
    """Source where the company was scraped from."""

    INDEED = "INDEED"
    KVK = "KVK"
    LINKEDIN = "LINKEDIN"
    TECHLEAP = "TECHLEAP"
    DEALROOM = "DEALROOM"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


class Company(Base):
    """Company model representing a scraped business."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_vacancies: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_funding: Mapped[bool] = mapped_column(default=False)
    funding_amount: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source: Mapped[CompanySource] = mapped_column(
        Enum(CompanySource), default=CompanySource.MANUAL
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus), default=CompanyStatus.NEW, index=True
    )
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    scrape_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    leads: Mapped[list["Lead"]] = relationship("Lead", back_populates="company")

    def __repr__(self) -> str:
        return f"<Company(id={self.id}, name='{self.name}', domain='{self.domain}')>"

    def can_transition_to(self, new_status: CompanyStatus) -> bool:
        """Check if status transition is valid."""
        valid_transitions: dict[CompanyStatus, list[CompanyStatus]] = {
            CompanyStatus.NEW: [
                CompanyStatus.ENRICHING,
                CompanyStatus.DISQUALIFIED,
                CompanyStatus.ARCHIVED,
            ],
            CompanyStatus.ENRICHING: [
                CompanyStatus.ENRICHED,
                CompanyStatus.NO_CONTACT,
                CompanyStatus.NEW,  # Retry
            ],
            CompanyStatus.ENRICHED: [
                CompanyStatus.DISQUALIFIED,
                CompanyStatus.ARCHIVED,
            ],
            CompanyStatus.NO_CONTACT: [
                CompanyStatus.NEW,  # Retry
                CompanyStatus.ARCHIVED,
            ],
            CompanyStatus.DISQUALIFIED: [
                CompanyStatus.NEW,  # Re-evaluate
                CompanyStatus.ARCHIVED,
            ],
            CompanyStatus.ARCHIVED: [],  # Terminal state
        }
        return new_status in valid_transitions.get(self.status, [])
