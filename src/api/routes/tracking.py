"""API routes for email tracking."""

import urllib.parse
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.email import Email, EmailStatus
from src.models.event import Event, EventType
from src.models.lead import Lead
from src.services.tracking import TrackingService, TrackingStats


# Create two routers - one for /api/tracking, one for /t
router = APIRouter(prefix="/tracking", tags=["tracking"])
tracking_pixel_router = APIRouter(tags=["tracking-pixel"])


# Response models
class StatsResponse(BaseModel):
    """Response for tracking statistics."""

    total_sent: int
    total_opens: int
    unique_opens: int
    total_clicks: int
    unique_clicks: int
    total_replies: int
    total_bounces: int
    open_rate: float
    click_rate: float
    reply_rate: float
    bounce_rate: float
    period_start: str | None
    period_end: str | None


class LeadEngagementResponse(BaseModel):
    """Response for lead engagement data."""

    lead_id: int
    lead_name: str
    email_address: str
    emails_sent: int
    opens: int
    clicks: int
    replied: bool
    last_activity: str | None
    events: list[dict]


class EventResponse(BaseModel):
    """Response for event data."""

    id: int
    email_id: int
    type: str
    timestamp: str | None
    ip_address: str | None
    user_agent: str | None
    url: str | None
    extra_data: dict | None


class DailyStatsResponse(BaseModel):
    """Response for daily stats."""

    date: str
    sent: int
    opens: int
    clicks: int
    replies: int


class TopLinkResponse(BaseModel):
    """Response for top clicked link."""

    url: str
    clicks: int


# Helper functions
def get_tracker() -> TrackingService:
    """Get tracking service instance."""
    return TrackingService()


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from request."""
    # Check X-Forwarded-For header (from reverse proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain
        return forwarded.split(",")[0].strip()

    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback to client host
    if request.client:
        return request.client.host

    return None


# ============= Tracking Pixel Endpoints (at /t/) =============

@tracking_pixel_router.get("/t/o/{tracking_id}.gif")
async def tracking_pixel(
    tracking_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> Response:
    """Serve tracking pixel and record open.

    This endpoint is embedded in emails as an invisible image.
    When the email client loads the image, we record an open event.
    """
    # Record the open event
    await tracker.record_open(
        db=db,
        tracking_id=tracking_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )

    # Return 1x1 transparent GIF
    return Response(
        content=TrackingService.TRACKING_PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@tracking_pixel_router.get("/t/c/{tracking_id}")
async def click_redirect(
    tracking_id: str,
    url: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> RedirectResponse:
    """Handle click tracking and redirect to original URL.

    Links in emails are rewritten to go through this endpoint.
    We record the click and redirect to the original destination.
    """
    # Decode URL if needed
    decoded_url = urllib.parse.unquote(url)

    # Record the click event
    await tracker.record_click(
        db=db,
        tracking_id=tracking_id,
        url=decoded_url,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )

    # Redirect to original URL
    return RedirectResponse(url=decoded_url, status_code=302)


# ============= API Endpoints (at /api/tracking/) =============

@router.get("/stats", response_model=StatsResponse)
async def get_tracking_stats(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> StatsResponse:
    """Get overall tracking statistics."""
    stats = await tracker.get_overall_stats(db, days)

    return StatsResponse(
        total_sent=stats.total_sent,
        total_opens=stats.total_opens,
        unique_opens=stats.unique_opens,
        total_clicks=stats.total_clicks,
        unique_clicks=stats.unique_clicks,
        total_replies=stats.total_replies,
        total_bounces=stats.total_bounces,
        open_rate=stats.open_rate,
        click_rate=stats.click_rate,
        reply_rate=stats.reply_rate,
        bounce_rate=stats.bounce_rate,
        period_start=stats.period_start.isoformat() if stats.period_start else None,
        period_end=stats.period_end.isoformat() if stats.period_end else None,
    )


@router.get("/lead/{lead_id}", response_model=LeadEngagementResponse)
async def get_lead_engagement(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> LeadEngagementResponse:
    """Get engagement data for a specific lead."""
    engagement = await tracker.get_lead_engagement(db, lead_id)

    if not engagement:
        raise HTTPException(status_code=404, detail="Lead not found")

    return LeadEngagementResponse(
        lead_id=engagement.lead_id,
        lead_name=engagement.lead_name,
        email_address=engagement.email_address,
        emails_sent=engagement.emails_sent,
        opens=engagement.opens,
        clicks=engagement.clicks,
        replied=engagement.replied,
        last_activity=engagement.last_activity.isoformat() if engagement.last_activity else None,
        events=engagement.events,
    )


@router.get("/events", response_model=list[EventResponse])
async def get_events(
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> list[EventResponse]:
    """Get recent tracking events."""
    # Convert event_type string to enum
    event_type_enum = None
    if event_type:
        try:
            event_type_enum = EventType(event_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event type: {event_type}. Valid types: {[e.value for e in EventType]}",
            )

    events = await tracker.get_events(db, event_type_enum, limit, offset)

    return [
        EventResponse(
            id=e["id"],
            email_id=e["email_id"],
            type=e["type"],
            timestamp=e["timestamp"],
            ip_address=e["ip_address"],
            user_agent=e["user_agent"],
            url=e["url"],
            extra_data=e["extra_data"],
        )
        for e in events
    ]


@router.get("/daily", response_model=list[DailyStatsResponse])
async def get_daily_stats(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> list[DailyStatsResponse]:
    """Get daily statistics for charting."""
    stats = await tracker.get_daily_stats(db, days)

    return [
        DailyStatsResponse(
            date=s["date"],
            sent=s["sent"],
            opens=s["opens"],
            clicks=s["clicks"],
            replies=s["replies"],
        )
        for s in stats
    ]


@router.get("/top-links", response_model=list[TopLinkResponse])
async def get_top_links(
    limit: int = Query(default=10, ge=1, le=50),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    tracker: TrackingService = Depends(get_tracker),
) -> list[TopLinkResponse]:
    """Get most clicked links."""
    links = await tracker.get_top_clicked_links(db, limit, days)

    return [
        TopLinkResponse(url=link["url"], clicks=link["clicks"])
        for link in links
    ]


@router.get("/email/{email_id}")
async def get_email_tracking(
    email_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get tracking data for a specific email."""
    email = await db.get(Email, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Get events for this email
    stmt = (
        select(Event)
        .where(Event.email_id == email_id)
        .order_by(Event.timestamp.desc())
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    return {
        "email_id": email.id,
        "tracking_id": email.tracking_id,
        "status": email.status.value,
        "sent_at": email.sent_at.isoformat() if email.sent_at else None,
        "opened_at": email.opened_at.isoformat() if email.opened_at else None,
        "clicked_at": email.clicked_at.isoformat() if email.clicked_at else None,
        "replied_at": email.replied_at.isoformat() if email.replied_at else None,
        "open_count": email.open_count,
        "click_count": email.click_count,
        "events": [
            {
                "id": e.id,
                "type": e.event_type.value,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "ip_address": e.ip_address,
                "url": e.clicked_url,
            }
            for e in events
        ],
    }


@router.get("/summary")
async def get_tracking_summary(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a quick summary of tracking metrics."""
    # Total emails sent
    sent_stmt = select(func.count(Email.id)).where(Email.status == EmailStatus.SENT)
    sent_result = await db.execute(sent_stmt)
    total_sent = sent_result.scalar() or 0

    # Total unique opens
    opened_stmt = select(func.count(Email.id)).where(Email.open_count > 0)
    opened_result = await db.execute(opened_stmt)
    unique_opens = opened_result.scalar() or 0

    # Total unique clicks
    clicked_stmt = select(func.count(Email.id)).where(Email.click_count > 0)
    clicked_result = await db.execute(clicked_stmt)
    unique_clicks = clicked_result.scalar() or 0

    # Total replies
    replied_stmt = select(func.count(Email.id)).where(Email.status == EmailStatus.REPLIED)
    replied_result = await db.execute(replied_stmt)
    total_replies = replied_result.scalar() or 0

    # Total bounced
    bounced_stmt = select(func.count(Email.id)).where(Email.status == EmailStatus.BOUNCED)
    bounced_result = await db.execute(bounced_stmt)
    total_bounced = bounced_result.scalar() or 0

    # Calculate rates
    open_rate = round(unique_opens / total_sent * 100, 2) if total_sent > 0 else 0
    click_rate = round(unique_clicks / total_sent * 100, 2) if total_sent > 0 else 0
    reply_rate = round(total_replies / total_sent * 100, 2) if total_sent > 0 else 0
    bounce_rate = round(total_bounced / total_sent * 100, 2) if total_sent > 0 else 0

    # Recent events count
    recent_events_stmt = select(func.count(Event.id))
    recent_events_result = await db.execute(recent_events_stmt)
    total_events = recent_events_result.scalar() or 0

    return {
        "total_sent": total_sent,
        "unique_opens": unique_opens,
        "unique_clicks": unique_clicks,
        "total_replies": total_replies,
        "total_bounced": total_bounced,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "reply_rate": reply_rate,
        "bounce_rate": bounce_rate,
        "total_events": total_events,
    }
