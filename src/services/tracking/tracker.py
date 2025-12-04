"""Tracking service for email opens, clicks, and stats."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.email import Email, EmailStatus
from src.models.event import Event, EventType
from src.models.lead import Lead, LeadStatus


CET = ZoneInfo("Europe/Amsterdam")


@dataclass
class TrackingStats:
    """Overall tracking statistics."""

    total_sent: int = 0
    total_opens: int = 0
    unique_opens: int = 0
    total_clicks: int = 0
    unique_clicks: int = 0
    total_replies: int = 0
    total_bounces: int = 0

    # Rates
    open_rate: float = 0.0
    click_rate: float = 0.0
    reply_rate: float = 0.0
    bounce_rate: float = 0.0

    # Time-based
    period_start: datetime | None = None
    period_end: datetime | None = None

    def calculate_rates(self) -> None:
        """Calculate engagement rates."""
        if self.total_sent > 0:
            self.open_rate = round(self.unique_opens / self.total_sent * 100, 2)
            self.click_rate = round(self.unique_clicks / self.total_sent * 100, 2)
            self.reply_rate = round(self.total_replies / self.total_sent * 100, 2)
            self.bounce_rate = round(self.total_bounces / self.total_sent * 100, 2)


@dataclass
class LeadEngagement:
    """Engagement data for a single lead."""

    lead_id: int
    lead_name: str
    email_address: str
    emails_sent: int = 0
    opens: int = 0
    clicks: int = 0
    replied: bool = False
    last_activity: datetime | None = None
    events: list[dict] = field(default_factory=list)


class TrackingService:
    """Service for tracking email engagement."""

    # 1x1 transparent GIF pixel
    TRACKING_PIXEL = (
        b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
        b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00'
        b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    )

    async def record_open(
        self,
        db: AsyncSession,
        tracking_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> bool:
        """Record an email open event.

        Args:
            db: Database session.
            tracking_id: Tracking ID from URL.
            ip_address: Client IP address.
            user_agent: Client user agent.

        Returns:
            True if open was recorded successfully.
        """
        # Find email by tracking ID
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await db.execute(stmt)
        email = result.scalar_one_or_none()

        if not email:
            return False

        # Record open on email
        email.record_open()

        # Create event
        event = Event.create_open_event(
            email_id=email.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(event)

        # Update lead status
        lead = await db.get(Lead, email.lead_id)
        if lead and lead.status == LeadStatus.CONTACTED:
            lead.status = LeadStatus.OPENED
            db.add(lead)

        db.add(email)
        await db.commit()

        return True

    async def record_click(
        self,
        db: AsyncSession,
        tracking_id: str,
        url: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str | None:
        """Record a link click event.

        Args:
            db: Database session.
            tracking_id: Tracking ID from URL.
            url: Original URL clicked.
            ip_address: Client IP address.
            user_agent: Client user agent.

        Returns:
            Original URL if found, None otherwise.
        """
        # Find email by tracking ID
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await db.execute(stmt)
        email = result.scalar_one_or_none()

        if not email:
            return None

        # Record click on email
        email.record_click()

        # Create event
        event = Event.create_click_event(
            email_id=email.id,
            clicked_url=url,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(event)

        # Update lead status
        lead = await db.get(Lead, email.lead_id)
        if lead and lead.status in (LeadStatus.CONTACTED, LeadStatus.OPENED):
            lead.status = LeadStatus.CLICKED
            db.add(lead)

        db.add(email)
        await db.commit()

        return url

    async def record_reply(
        self,
        db: AsyncSession,
        email_id: int,
        from_email: str,
        subject: str | None = None,
        message_id: str | None = None,
    ) -> bool:
        """Record a reply event.

        Args:
            db: Database session.
            email_id: Email ID that received a reply.
            from_email: Sender email address.
            subject: Reply subject.
            message_id: Message ID of the reply.

        Returns:
            True if reply was recorded successfully.
        """
        email = await db.get(Email, email_id)
        if not email:
            return False

        # Update email
        email.replied_at = datetime.now()
        email.status = EmailStatus.REPLIED

        # Create event
        event = Event.create_reply_event(
            email_id=email.id,
            extra_data={
                "from_email": from_email,
                "subject": subject,
                "message_id": message_id,
            },
        )
        db.add(event)

        # Update lead status and stop sequence
        lead = await db.get(Lead, email.lead_id)
        if lead:
            lead.status = LeadStatus.REPLIED
            lead.replied_at = datetime.now()
            db.add(lead)

            # Cancel remaining emails in sequence
            await self._cancel_pending_emails(db, lead.id)

        db.add(email)
        await db.commit()

        return True

    async def _cancel_pending_emails(
        self,
        db: AsyncSession,
        lead_id: int,
    ) -> int:
        """Cancel pending emails for a lead.

        Args:
            db: Database session.
            lead_id: Lead ID.

        Returns:
            Number of emails cancelled.
        """
        stmt = select(Email).where(
            Email.lead_id == lead_id,
            Email.status == EmailStatus.PENDING,
        )
        result = await db.execute(stmt)
        emails = list(result.scalars().all())

        for email in emails:
            email.status = EmailStatus.CANCELLED
            db.add(email)

        return len(emails)

    async def get_overall_stats(
        self,
        db: AsyncSession,
        days: int = 30,
    ) -> TrackingStats:
        """Get overall tracking statistics.

        Args:
            db: Database session.
            days: Number of days to include.

        Returns:
            TrackingStats with aggregated data.
        """
        now = datetime.now(CET)
        start_date = now - timedelta(days=days)

        stats = TrackingStats(
            period_start=start_date,
            period_end=now,
        )

        # Total sent emails
        sent_stmt = select(func.count(Email.id)).where(
            Email.status == EmailStatus.SENT,
            Email.sent_at >= start_date,
        )
        sent_result = await db.execute(sent_stmt)
        stats.total_sent = sent_result.scalar() or 0

        # Total opens (events)
        opens_stmt = select(func.count(Event.id)).where(
            Event.event_type == EventType.OPEN,
            Event.timestamp >= start_date,
        )
        opens_result = await db.execute(opens_stmt)
        stats.total_opens = opens_result.scalar() or 0

        # Unique opens (distinct emails)
        unique_opens_stmt = select(func.count(func.distinct(Event.email_id))).where(
            Event.event_type == EventType.OPEN,
            Event.timestamp >= start_date,
        )
        unique_opens_result = await db.execute(unique_opens_stmt)
        stats.unique_opens = unique_opens_result.scalar() or 0

        # Total clicks (events)
        clicks_stmt = select(func.count(Event.id)).where(
            Event.event_type == EventType.CLICK,
            Event.timestamp >= start_date,
        )
        clicks_result = await db.execute(clicks_stmt)
        stats.total_clicks = clicks_result.scalar() or 0

        # Unique clicks (distinct emails)
        unique_clicks_stmt = select(func.count(func.distinct(Event.email_id))).where(
            Event.event_type == EventType.CLICK,
            Event.timestamp >= start_date,
        )
        unique_clicks_result = await db.execute(unique_clicks_stmt)
        stats.unique_clicks = unique_clicks_result.scalar() or 0

        # Replies
        replies_stmt = select(func.count(Event.id)).where(
            Event.event_type == EventType.REPLY,
            Event.timestamp >= start_date,
        )
        replies_result = await db.execute(replies_stmt)
        stats.total_replies = replies_result.scalar() or 0

        # Bounces
        bounces_stmt = select(func.count(Event.id)).where(
            Event.event_type == EventType.BOUNCE,
            Event.timestamp >= start_date,
        )
        bounces_result = await db.execute(bounces_stmt)
        stats.total_bounces = bounces_result.scalar() or 0

        # Calculate rates
        stats.calculate_rates()

        return stats

    async def get_lead_engagement(
        self,
        db: AsyncSession,
        lead_id: int,
    ) -> LeadEngagement | None:
        """Get engagement data for a specific lead.

        Args:
            db: Database session.
            lead_id: Lead ID.

        Returns:
            LeadEngagement data or None if lead not found.
        """
        lead = await db.get(Lead, lead_id)
        if not lead:
            return None

        engagement = LeadEngagement(
            lead_id=lead.id,
            lead_name=f"{lead.first_name} {lead.last_name}",
            email_address=lead.email or "",
            replied=lead.status == LeadStatus.REPLIED,
        )

        # Get emails for this lead
        emails_stmt = select(Email).where(
            Email.lead_id == lead_id,
            Email.status == EmailStatus.SENT,
        )
        emails_result = await db.execute(emails_stmt)
        emails = list(emails_result.scalars().all())

        engagement.emails_sent = len(emails)
        engagement.opens = sum(e.open_count for e in emails)
        engagement.clicks = sum(e.click_count for e in emails)

        # Get events
        email_ids = [e.id for e in emails]
        if email_ids:
            events_stmt = (
                select(Event)
                .where(Event.email_id.in_(email_ids))
                .order_by(Event.timestamp.desc())
                .limit(50)
            )
            events_result = await db.execute(events_stmt)
            events = list(events_result.scalars().all())

            engagement.events = [
                {
                    "type": e.event_type.value,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "ip_address": e.ip_address,
                    "url": e.clicked_url,
                }
                for e in events
            ]

            if events:
                engagement.last_activity = events[0].timestamp

        return engagement

    async def get_events(
        self,
        db: AsyncSession,
        event_type: EventType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get recent events.

        Args:
            db: Database session.
            event_type: Filter by event type.
            limit: Maximum number of events.
            offset: Offset for pagination.

        Returns:
            List of event dictionaries.
        """
        stmt = select(Event).order_by(Event.timestamp.desc())

        if event_type:
            stmt = stmt.where(Event.event_type == event_type)

        stmt = stmt.offset(offset).limit(limit)

        result = await db.execute(stmt)
        events = list(result.scalars().all())

        return [
            {
                "id": e.id,
                "email_id": e.email_id,
                "type": e.event_type.value,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "ip_address": e.ip_address,
                "user_agent": e.user_agent,
                "url": e.clicked_url,
                "extra_data": e.extra_data,
            }
            for e in events
        ]

    async def get_daily_stats(
        self,
        db: AsyncSession,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Get daily statistics for charting.

        Args:
            db: Database session.
            days: Number of days to include.

        Returns:
            List of daily stats dictionaries.
        """
        now = datetime.now(CET)
        daily_stats = []

        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            # Emails sent
            sent_stmt = select(func.count(Email.id)).where(
                Email.status == EmailStatus.SENT,
                Email.sent_at >= day_start,
                Email.sent_at < day_end,
            )
            sent_result = await db.execute(sent_stmt)
            sent = sent_result.scalar() or 0

            # Opens
            opens_stmt = select(func.count(Event.id)).where(
                Event.event_type == EventType.OPEN,
                Event.timestamp >= day_start,
                Event.timestamp < day_end,
            )
            opens_result = await db.execute(opens_stmt)
            opens = opens_result.scalar() or 0

            # Clicks
            clicks_stmt = select(func.count(Event.id)).where(
                Event.event_type == EventType.CLICK,
                Event.timestamp >= day_start,
                Event.timestamp < day_end,
            )
            clicks_result = await db.execute(clicks_stmt)
            clicks = clicks_result.scalar() or 0

            # Replies
            replies_stmt = select(func.count(Event.id)).where(
                Event.event_type == EventType.REPLY,
                Event.timestamp >= day_start,
                Event.timestamp < day_end,
            )
            replies_result = await db.execute(replies_stmt)
            replies = replies_result.scalar() or 0

            daily_stats.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "sent": sent,
                "opens": opens,
                "clicks": clicks,
                "replies": replies,
            })

        # Reverse to have oldest first
        daily_stats.reverse()
        return daily_stats

    async def get_top_clicked_links(
        self,
        db: AsyncSession,
        limit: int = 10,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get most clicked links.

        Args:
            db: Database session.
            limit: Maximum number of links.
            days: Number of days to include.

        Returns:
            List of link dictionaries with click counts.
        """
        start_date = datetime.now(CET) - timedelta(days=days)

        stmt = (
            select(Event.clicked_url, func.count(Event.id).label("click_count"))
            .where(
                Event.event_type == EventType.CLICK,
                Event.timestamp >= start_date,
                Event.clicked_url.isnot(None),
            )
            .group_by(Event.clicked_url)
            .order_by(func.count(Event.id).desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        rows = result.all()

        return [
            {"url": row.clicked_url, "clicks": row.click_count}
            for row in rows
        ]

    async def get_email_by_tracking_id(
        self,
        db: AsyncSession,
        tracking_id: str,
    ) -> Email | None:
        """Get email by tracking ID.

        Args:
            db: Database session.
            tracking_id: Tracking ID.

        Returns:
            Email or None if not found.
        """
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
