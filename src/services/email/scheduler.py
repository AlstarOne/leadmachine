"""Email scheduling service with business hours and rate limiting."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.email import Email, EmailStatus
from src.models.lead import Lead, LeadStatus


# CET/CEST timezone
CET = ZoneInfo("Europe/Amsterdam")


@dataclass
class SendSlot:
    """A send slot for scheduling emails."""

    datetime: datetime
    is_business_hours: bool
    delay_reason: str | None = None


@dataclass
class RateLimitStatus:
    """Current rate limit status."""

    emails_sent_today: int
    daily_limit: int
    remaining_today: int
    can_send: bool
    reset_at: datetime


class SchedulerService:
    """Service for scheduling email sends."""

    # Business hours (CET)
    BUSINESS_START = time(9, 0)  # 9:00 AM
    BUSINESS_END = time(17, 0)  # 5:00 PM
    BUSINESS_DAYS = (0, 1, 2, 3, 4)  # Monday to Friday

    def __init__(
        self,
        daily_limit: int | None = None,
        min_delay_seconds: int | None = None,
        max_delay_seconds: int | None = None,
    ) -> None:
        """Initialize scheduler service.

        Args:
            daily_limit: Maximum emails per day.
            min_delay_seconds: Minimum delay between emails.
            max_delay_seconds: Maximum delay between emails.
        """
        settings = get_settings()
        self.daily_limit = daily_limit or settings.email_daily_limit
        self.min_delay_seconds = min_delay_seconds or settings.email_min_delay_seconds
        self.max_delay_seconds = max_delay_seconds or settings.email_max_delay_seconds

    def get_current_time_cet(self) -> datetime:
        """Get current time in CET timezone.

        Returns:
            Current datetime in CET.
        """
        return datetime.now(CET)

    def is_business_hours(self, dt: datetime | None = None) -> bool:
        """Check if given time is within business hours.

        Args:
            dt: Datetime to check (defaults to now).

        Returns:
            True if within business hours.
        """
        if dt is None:
            dt = self.get_current_time_cet()
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=CET)

        # Convert to CET if needed
        dt_cet = dt.astimezone(CET)

        # Check if it's a business day (Monday=0, Sunday=6)
        if dt_cet.weekday() not in self.BUSINESS_DAYS:
            return False

        # Check if it's within business hours
        current_time = dt_cet.time()
        return self.BUSINESS_START <= current_time < self.BUSINESS_END

    def get_next_business_hour(self, from_dt: datetime | None = None) -> datetime:
        """Get the next business hour start time.

        Args:
            from_dt: Starting datetime (defaults to now).

        Returns:
            Next datetime when business hours start.
        """
        if from_dt is None:
            from_dt = self.get_current_time_cet()
        elif from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=CET)

        dt_cet = from_dt.astimezone(CET)

        # If currently in business hours, return now
        if self.is_business_hours(dt_cet):
            return dt_cet

        # Find next business day/time
        next_dt = dt_cet

        # If past business hours today, move to next day
        if next_dt.time() >= self.BUSINESS_END:
            next_dt = next_dt + timedelta(days=1)

        # Set to business start time
        next_dt = next_dt.replace(
            hour=self.BUSINESS_START.hour,
            minute=self.BUSINESS_START.minute,
            second=0,
            microsecond=0,
        )

        # Skip weekends
        while next_dt.weekday() not in self.BUSINESS_DAYS:
            next_dt = next_dt + timedelta(days=1)

        return next_dt

    def get_next_send_slot(
        self,
        from_dt: datetime | None = None,
        respect_business_hours: bool = True,
    ) -> SendSlot:
        """Get the next available send slot.

        Args:
            from_dt: Starting datetime.
            respect_business_hours: Whether to wait for business hours.

        Returns:
            SendSlot with datetime and status.
        """
        if from_dt is None:
            from_dt = self.get_current_time_cet()
        elif from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=CET)

        # Add random delay
        delay = random.randint(self.min_delay_seconds, self.max_delay_seconds)
        send_dt = from_dt + timedelta(seconds=delay)

        if respect_business_hours and not self.is_business_hours(send_dt):
            # Wait for next business hour
            send_dt = self.get_next_business_hour(send_dt)
            return SendSlot(
                datetime=send_dt,
                is_business_hours=True,
                delay_reason="Waiting for business hours",
            )

        return SendSlot(
            datetime=send_dt,
            is_business_hours=self.is_business_hours(send_dt),
        )

    async def check_daily_limit(self, db: AsyncSession) -> RateLimitStatus:
        """Check if daily email limit has been reached.

        Args:
            db: Database session.

        Returns:
            RateLimitStatus with current counts.
        """
        # Get today's date in CET
        now_cet = self.get_current_time_cet()
        today_start = now_cet.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # Count emails sent today
        stmt = select(func.count(Email.id)).where(
            Email.status == EmailStatus.SENT,
            Email.sent_at >= today_start,
            Email.sent_at < today_end,
        )
        result = await db.execute(stmt)
        sent_today = result.scalar() or 0

        remaining = max(0, self.daily_limit - sent_today)
        can_send = remaining > 0

        return RateLimitStatus(
            emails_sent_today=sent_today,
            daily_limit=self.daily_limit,
            remaining_today=remaining,
            can_send=can_send,
            reset_at=today_end,
        )

    async def can_send_now(self, db: AsyncSession) -> tuple[bool, str | None]:
        """Check if we can send an email right now.

        Args:
            db: Database session.

        Returns:
            Tuple of (can_send, reason_if_not).
        """
        # Check business hours
        if not self.is_business_hours():
            next_slot = self.get_next_business_hour()
            return False, f"Outside business hours. Next slot: {next_slot.isoformat()}"

        # Check daily limit
        rate_status = await self.check_daily_limit(db)
        if not rate_status.can_send:
            return False, f"Daily limit reached ({rate_status.daily_limit}). Resets at {rate_status.reset_at.isoformat()}"

        return True, None

    async def get_emails_to_send(
        self,
        db: AsyncSession,
        limit: int | None = None,
    ) -> list[Email]:
        """Get emails that are ready to be sent.

        Args:
            db: Database session.
            limit: Maximum number of emails to return.

        Returns:
            List of emails ready for sending.
        """
        # Check rate limit
        rate_status = await self.check_daily_limit(db)
        if not rate_status.can_send:
            return []

        # Use remaining limit if no limit specified
        if limit is None:
            limit = rate_status.remaining_today

        # Get scheduled emails that are due
        now = self.get_current_time_cet()
        stmt = (
            select(Email)
            .where(
                Email.status == EmailStatus.PENDING,
                Email.scheduled_at <= now,
            )
            .order_by(Email.scheduled_at)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_next_scheduled_email(
        self,
        db: AsyncSession,
    ) -> Email | None:
        """Get the next email scheduled for sending.

        Args:
            db: Database session.

        Returns:
            Next scheduled email or None.
        """
        stmt = (
            select(Email)
            .where(Email.status == EmailStatus.PENDING)
            .order_by(Email.scheduled_at)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def schedule_sequence_emails(
        self,
        db: AsyncSession,
        lead_id: int,
        start_date: datetime | None = None,
    ) -> list[datetime]:
        """Schedule send times for a lead's email sequence.

        Args:
            db: Database session.
            lead_id: Lead ID.
            start_date: When to start the sequence.

        Returns:
            List of scheduled datetimes.
        """
        if start_date is None:
            start_date = self.get_next_business_hour()

        # Get lead's emails
        stmt = (
            select(Email)
            .where(Email.lead_id == lead_id)
            .order_by(Email.sequence_step)
        )
        result = await db.execute(stmt)
        emails = list(result.scalars().all())

        scheduled_times = []
        for email in emails:
            # Calculate scheduled time based on sequence day
            days_offset = email.scheduled_day
            scheduled_dt = start_date + timedelta(days=days_offset)

            # Ensure it's during business hours
            if not self.is_business_hours(scheduled_dt):
                scheduled_dt = self.get_next_business_hour(scheduled_dt)

            # Add some randomness to avoid predictable patterns
            random_minutes = random.randint(0, 120)  # 0-2 hours
            scheduled_dt = scheduled_dt + timedelta(minutes=random_minutes)

            # Ensure still within business hours
            if not self.is_business_hours(scheduled_dt):
                scheduled_dt = self.get_next_business_hour(scheduled_dt)

            email.scheduled_at = scheduled_dt
            email.status = EmailStatus.PENDING
            db.add(email)
            scheduled_times.append(scheduled_dt)

        await db.commit()
        return scheduled_times

    async def pause_sequence(
        self,
        db: AsyncSession,
        lead_id: int,
    ) -> int:
        """Pause a lead's email sequence.

        Args:
            db: Database session.
            lead_id: Lead ID.

        Returns:
            Number of emails paused.
        """
        # Get pending emails for this lead
        stmt = select(Email).where(
            Email.lead_id == lead_id,
            Email.status == EmailStatus.PENDING,
        )
        result = await db.execute(stmt)
        emails = list(result.scalars().all())

        for email in emails:
            email.status = EmailStatus.CANCELLED
            db.add(email)

        await db.commit()
        return len(emails)

    async def resume_sequence(
        self,
        db: AsyncSession,
        lead_id: int,
    ) -> int:
        """Resume a paused email sequence.

        Args:
            db: Database session.
            lead_id: Lead ID.

        Returns:
            Number of emails resumed.
        """
        # Get cancelled emails for this lead
        stmt = select(Email).where(
            Email.lead_id == lead_id,
            Email.status == EmailStatus.CANCELLED,
        )
        result = await db.execute(stmt)
        emails = list(result.scalars().all())

        now = self.get_current_time_cet()
        for email in emails:
            email.status = EmailStatus.PENDING
            # Reschedule if scheduled time has passed
            if email.scheduled_at and email.scheduled_at < now:
                email.scheduled_at = self.get_next_business_hour()
            db.add(email)

        await db.commit()
        return len(emails)

    def get_random_delay(self) -> int:
        """Get a random delay between emails.

        Returns:
            Delay in seconds.
        """
        return random.randint(self.min_delay_seconds, self.max_delay_seconds)

    async def get_queue_status(self, db: AsyncSession) -> dict[str, Any]:
        """Get current email queue status.

        Args:
            db: Database session.

        Returns:
            Dictionary with queue statistics.
        """
        now = self.get_current_time_cet()

        # Count pending emails
        pending_stmt = select(func.count(Email.id)).where(
            Email.status == EmailStatus.PENDING
        )
        pending_result = await db.execute(pending_stmt)
        pending_count = pending_result.scalar() or 0

        # Count due emails (scheduled_at <= now)
        due_stmt = select(func.count(Email.id)).where(
            Email.status == EmailStatus.PENDING,
            Email.scheduled_at <= now,
        )
        due_result = await db.execute(due_stmt)
        due_count = due_result.scalar() or 0

        # Get rate limit status
        rate_status = await self.check_daily_limit(db)

        # Get next scheduled email
        next_email = await self.get_next_scheduled_email(db)

        return {
            "pending_count": pending_count,
            "due_count": due_count,
            "next_scheduled_at": next_email.scheduled_at.isoformat() if next_email and next_email.scheduled_at else None,
            "is_business_hours": self.is_business_hours(),
            "next_business_hour": self.get_next_business_hour().isoformat() if not self.is_business_hours() else None,
            "daily_limit": rate_status.daily_limit,
            "sent_today": rate_status.emails_sent_today,
            "remaining_today": rate_status.remaining_today,
            "can_send": rate_status.can_send and self.is_business_hours(),
        }
