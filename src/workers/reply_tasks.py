"""Celery tasks for reply checking and tracking operations."""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_inbox_task(
    self: Any,
    folder: str = "INBOX",
    unseen_only: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Check inbox for new replies.

    Args:
        self: Celery task instance.
        folder: IMAP folder to check.
        unseen_only: Only check unseen messages.
        limit: Maximum messages to process.

    Returns:
        Dictionary with check results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.tracking import ReplyChecker

        session_factory = get_async_session()

        async with session_factory() as session:
            checker = ReplyChecker()

            # Check if IMAP is configured
            if not checker.host or not checker.user:
                return {
                    "success": False,
                    "error": "IMAP not configured",
                    "replies_found": 0,
                    "replies_processed": 0,
                }

            try:
                # Check inbox for replies
                replies = await checker.check_inbox(
                    db=session,
                    folder=folder,
                    unseen_only=unseen_only,
                    limit=limit,
                )

                if not replies:
                    return {
                        "success": True,
                        "message": "No new replies found",
                        "replies_found": 0,
                        "replies_processed": 0,
                    }

                # Process the replies
                result = await checker.process_replies(session, replies)

                return {
                    "success": True,
                    "replies_found": len(replies),
                    "replies_processed": result["processed"],
                    "errors": result["errors"],
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "replies_found": 0,
                    "replies_processed": 0,
                }

    return asyncio.run(_run())


@shared_task(bind=True)
def record_reply_task(
    self: Any,
    email_id: int,
    from_email: str,
    subject: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Manually record a reply for an email.

    Args:
        self: Celery task instance.
        email_id: Email ID that received a reply.
        from_email: Sender email address.
        subject: Reply subject.
        message_id: Message ID of the reply.

    Returns:
        Dictionary with result.
    """
    async def _run() -> dict[str, Any]:
        from src.services.tracking import TrackingService

        session_factory = get_async_session()

        async with session_factory() as session:
            tracker = TrackingService()

            success = await tracker.record_reply(
                db=session,
                email_id=email_id,
                from_email=from_email,
                subject=subject,
                message_id=message_id,
            )

            return {
                "success": success,
                "email_id": email_id,
                "from_email": from_email,
            }

    return asyncio.run(_run())


@shared_task
def get_tracking_stats_task(days: int = 30) -> dict[str, Any]:
    """Get tracking statistics.

    Args:
        days: Number of days to include.

    Returns:
        Dictionary with stats.
    """
    async def _run() -> dict[str, Any]:
        from src.services.tracking import TrackingService

        session_factory = get_async_session()

        async with session_factory() as session:
            tracker = TrackingService()
            stats = await tracker.get_overall_stats(session, days)

            return {
                "total_sent": stats.total_sent,
                "total_opens": stats.total_opens,
                "unique_opens": stats.unique_opens,
                "total_clicks": stats.total_clicks,
                "unique_clicks": stats.unique_clicks,
                "total_replies": stats.total_replies,
                "total_bounces": stats.total_bounces,
                "open_rate": stats.open_rate,
                "click_rate": stats.click_rate,
                "reply_rate": stats.reply_rate,
                "bounce_rate": stats.bounce_rate,
            }

    return asyncio.run(_run())


@shared_task(bind=True)
def run_scheduled_reply_check(self: Any) -> dict[str, Any]:
    """Scheduled task to check for replies.

    This task is scheduled via beat to run every 30 minutes.

    Returns:
        Dictionary with check results.
    """
    async def _run() -> dict[str, Any]:
        from src.services.tracking import ReplyChecker

        session_factory = get_async_session()
        start_time = datetime.now()

        async with session_factory() as session:
            checker = ReplyChecker()

            # Check if IMAP is configured
            if not checker.host or not checker.user:
                return {
                    "success": True,
                    "message": "IMAP not configured, skipping",
                    "replies_found": 0,
                    "replies_processed": 0,
                }

            try:
                # Check inbox for replies
                replies = await checker.check_inbox(
                    db=session,
                    folder="INBOX",
                    unseen_only=True,
                    limit=100,
                )

                if not replies:
                    return {
                        "success": True,
                        "message": "No new replies found",
                        "replies_found": 0,
                        "replies_processed": 0,
                        "duration_seconds": (datetime.now() - start_time).total_seconds(),
                    }

                # Process the replies
                result = await checker.process_replies(session, replies)

                return {
                    "success": True,
                    "replies_found": len(replies),
                    "replies_processed": result["processed"],
                    "errors": result["errors"][:10] if result["errors"] else [],
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "replies_found": 0,
                    "replies_processed": 0,
                    "duration_seconds": (datetime.now() - start_time).total_seconds(),
                }

    return asyncio.run(_run())


@shared_task(bind=True)
def imap_health_check(self: Any) -> dict[str, Any]:
    """Check IMAP server health.

    Returns:
        Dictionary with health status.
    """
    async def _run() -> dict[str, Any]:
        from src.services.tracking import ReplyChecker

        checker = ReplyChecker()

        if not checker.host or not checker.user:
            return {
                "healthy": False,
                "error": "IMAP not configured",
            }

        healthy = await checker.health_check()

        return {
            "healthy": healthy,
            "host": checker.host,
            "port": checker.port,
        }

    return asyncio.run(_run())
