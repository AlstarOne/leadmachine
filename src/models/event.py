"""Event model for tracking email interactions."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.email import Email


class EventType(str, enum.Enum):
    """Type of tracking event."""

    OPEN = "open"  # Email was opened (pixel loaded)
    CLICK = "click"  # Link was clicked
    REPLY = "reply"  # Reply received
    BOUNCE = "bounce"  # Email bounced
    COMPLAINT = "complaint"  # Marked as spam
    UNSUBSCRIBE = "unsubscribe"  # Unsubscribed


class Event(Base):
    """Event model for tracking email interactions."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Event info
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False, index=True)

    # Request metadata
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max length
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referer: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Click-specific data
    clicked_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Additional data
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    email: Mapped["Email"] = relationship("Email", back_populates="events")

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, type={self.event_type}, email_id={self.email_id})>"

    @classmethod
    def create_open_event(
        cls,
        email_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> "Event":
        """Create an open tracking event."""
        return cls(
            email_id=email_id,
            event_type=EventType.OPEN,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @classmethod
    def create_click_event(
        cls,
        email_id: int,
        clicked_url: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> "Event":
        """Create a click tracking event."""
        return cls(
            email_id=email_id,
            event_type=EventType.CLICK,
            clicked_url=clicked_url,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @classmethod
    def create_reply_event(
        cls,
        email_id: int,
        extra_data: dict | None = None,
    ) -> "Event":
        """Create a reply event."""
        return cls(
            email_id=email_id,
            event_type=EventType.REPLY,
            extra_data=extra_data,
        )

    @classmethod
    def create_bounce_event(
        cls,
        email_id: int,
        extra_data: dict | None = None,
    ) -> "Event":
        """Create a bounce event."""
        return cls(
            email_id=email_id,
            event_type=EventType.BOUNCE,
            extra_data=extra_data,
        )
