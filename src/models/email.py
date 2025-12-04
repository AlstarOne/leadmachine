"""Email model for storing generated and sent emails."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.event import Event
    from src.models.lead import Lead


class EmailStatus(str, enum.Enum):
    """Status of an email."""

    DRAFT = "DRAFT"  # Not yet ready
    PENDING = "PENDING"  # Ready to send, scheduled
    SENDING = "SENDING"  # Currently being sent
    SENT = "SENT"  # Successfully sent
    OPENED = "OPENED"  # Recipient opened
    CLICKED = "CLICKED"  # Recipient clicked a link
    REPLIED = "REPLIED"  # Recipient replied
    BOUNCED = "BOUNCED"  # Delivery failed
    CANCELLED = "CANCELLED"  # Manually cancelled


class EmailSequenceStep(int, enum.Enum):
    """Step in the email sequence."""

    INITIAL = 1  # Day 0: First contact
    FOLLOWUP_1 = 2  # Day 3: First follow-up
    FOLLOWUP_2 = 3  # Day 7: Second follow-up
    BREAKUP = 4  # Day 14: Final email


class Email(Base):
    """Email model representing a single email in a sequence."""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Email content
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sequence info
    sequence_step: Mapped[EmailSequenceStep] = mapped_column(
        Enum(EmailSequenceStep), default=EmailSequenceStep.INITIAL
    )
    scheduled_day: Mapped[int] = mapped_column(Integer, default=0)  # Days from sequence start

    # Tracking
    tracking_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid.uuid4()), unique=True, index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # SMTP message ID

    # Status
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus), default=EmailStatus.DRAFT, index=True
    )

    # Metrics
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    clicked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bounced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead", back_populates="emails")
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="email", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Email(id={self.id}, tracking_id='{self.tracking_id}', status={self.status})>"

    def can_transition_to(self, new_status: EmailStatus) -> bool:
        """Check if status transition is valid."""
        valid_transitions: dict[EmailStatus, list[EmailStatus]] = {
            EmailStatus.DRAFT: [
                EmailStatus.PENDING,
                EmailStatus.CANCELLED,
            ],
            EmailStatus.PENDING: [
                EmailStatus.SENDING,
                EmailStatus.CANCELLED,
            ],
            EmailStatus.SENDING: [
                EmailStatus.SENT,
                EmailStatus.BOUNCED,
            ],
            EmailStatus.SENT: [
                EmailStatus.OPENED,
                EmailStatus.REPLIED,
                EmailStatus.BOUNCED,
            ],
            EmailStatus.OPENED: [
                EmailStatus.CLICKED,
                EmailStatus.REPLIED,
            ],
            EmailStatus.CLICKED: [
                EmailStatus.REPLIED,
            ],
            EmailStatus.REPLIED: [],  # Terminal state
            EmailStatus.BOUNCED: [],  # Terminal state
            EmailStatus.CANCELLED: [],  # Terminal state
        }
        return new_status in valid_transitions.get(self.status, [])

    def record_open(self) -> None:
        """Record an email open event."""
        self.open_count += 1
        if self.opened_at is None:
            self.opened_at = datetime.now()
        if self.status == EmailStatus.SENT:
            self.status = EmailStatus.OPENED

    def record_click(self) -> None:
        """Record a link click event."""
        self.click_count += 1
        if self.clicked_at is None:
            self.clicked_at = datetime.now()
        if self.status in (EmailStatus.SENT, EmailStatus.OPENED):
            self.status = EmailStatus.CLICKED

    def record_reply(self) -> None:
        """Record a reply event."""
        self.replied_at = datetime.now()
        self.status = EmailStatus.REPLIED

    def record_bounce(self) -> None:
        """Record a bounce event."""
        self.bounced_at = datetime.now()
        self.status = EmailStatus.BOUNCED
