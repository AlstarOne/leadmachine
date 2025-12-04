"""Lead model for storing contact person data."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.company import Company
    from src.models.email import Email


class LeadStatus(str, enum.Enum):
    """Status of a lead in the pipeline."""

    NEW = "NEW"  # Just created from enrichment
    ENRICHED = "ENRICHED"  # Contact info found
    NO_EMAIL = "NO_EMAIL"  # Could not find email
    QUALIFIED = "QUALIFIED"  # Passed ICP scoring (score >= 60)
    DISQUALIFIED = "DISQUALIFIED"  # Failed ICP scoring (score < 60)
    SEQUENCED = "SEQUENCED"  # Emails generated
    CONTACTED = "CONTACTED"  # First email sent
    OPENED = "OPENED"  # Email opened
    CLICKED = "CLICKED"  # Link clicked
    REPLIED = "REPLIED"  # Received reply
    BOUNCED = "BOUNCED"  # Email bounced
    CONVERTED = "CONVERTED"  # Became customer
    ARCHIVED = "ARCHIVED"  # Manually archived


class LeadClassification(str, enum.Enum):
    """ICP classification based on score."""

    HOT = "HOT"  # Score >= 75
    WARM = "WARM"  # Score 60-74
    COOL = "COOL"  # Score 45-59
    COLD = "COLD"  # Score < 45
    UNSCORED = "UNSCORED"  # Not yet scored


class Lead(Base):
    """Lead model representing a contact person at a company."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Contact info
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    email_confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0-100%
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_posts_30d: Mapped[int] = mapped_column(Integer, default=0)

    # ICP Scoring
    icp_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classification: Mapped[LeadClassification] = mapped_column(
        Enum(LeadClassification), default=LeadClassification.UNSCORED, index=True
    )

    # Status
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus), default=LeadStatus.NEW, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sequenced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="leads")
    emails: Mapped[list["Email"]] = relationship(
        "Email", back_populates="lead", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Lead(id={self.id}, email='{self.email}', status={self.status})>"

    @property
    def full_name(self) -> str:
        """Get full name of lead."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"

    def can_transition_to(self, new_status: LeadStatus) -> bool:
        """Check if status transition is valid."""
        valid_transitions: dict[LeadStatus, list[LeadStatus]] = {
            LeadStatus.NEW: [
                LeadStatus.ENRICHED,
                LeadStatus.NO_EMAIL,
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.ENRICHED: [
                LeadStatus.QUALIFIED,
                LeadStatus.DISQUALIFIED,
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.NO_EMAIL: [
                LeadStatus.NEW,  # Retry enrichment
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.QUALIFIED: [
                LeadStatus.SEQUENCED,
                LeadStatus.DISQUALIFIED,  # Re-score
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.DISQUALIFIED: [
                LeadStatus.QUALIFIED,  # Re-score
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.SEQUENCED: [
                LeadStatus.CONTACTED,
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.CONTACTED: [
                LeadStatus.OPENED,
                LeadStatus.BOUNCED,
                LeadStatus.REPLIED,
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.OPENED: [
                LeadStatus.CLICKED,
                LeadStatus.REPLIED,
                LeadStatus.CONTACTED,  # Next email in sequence
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.CLICKED: [
                LeadStatus.REPLIED,
                LeadStatus.OPENED,  # Reset for next email
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.REPLIED: [
                LeadStatus.CONVERTED,
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.BOUNCED: [
                LeadStatus.NO_EMAIL,  # Try to find new email
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.CONVERTED: [
                LeadStatus.ARCHIVED,
            ],
            LeadStatus.ARCHIVED: [],  # Terminal state
        }
        return new_status in valid_transitions.get(self.status, [])

    @staticmethod
    def get_classification_for_score(score: int) -> LeadClassification:
        """Get classification for a given score."""
        if score >= 75:
            return LeadClassification.HOT
        elif score >= 60:
            return LeadClassification.WARM
        elif score >= 45:
            return LeadClassification.COOL
        else:
            return LeadClassification.COLD

    def update_classification(self) -> None:
        """Update classification based on ICP score."""
        if self.icp_score is None:
            self.classification = LeadClassification.UNSCORED
        else:
            self.classification = self.get_classification_for_score(self.icp_score)
