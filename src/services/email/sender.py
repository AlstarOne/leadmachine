"""Email sender service with tracking injection."""

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.email import Email, EmailStatus
from src.models.lead import Lead, LeadStatus
from src.services.email.smtp import SMTPService, SendResult


@dataclass
class EmailSendResult:
    """Result of sending an email."""

    email_id: int
    success: bool
    message_id: str | None = None
    error: str | None = None
    tracking_id: str | None = None


class EmailSender:
    """Service for sending emails with tracking."""

    def __init__(
        self,
        smtp_service: SMTPService | None = None,
        tracking_base_url: str | None = None,
    ) -> None:
        """Initialize email sender.

        Args:
            smtp_service: SMTP service instance.
            tracking_base_url: Base URL for tracking endpoints.
        """
        settings = get_settings()
        self.smtp = smtp_service or SMTPService()
        self.tracking_base_url = tracking_base_url or settings.tracking_base_url

    def inject_tracking_pixel(self, html: str, tracking_id: str) -> str:
        """Inject tracking pixel into HTML email.

        Args:
            html: HTML email body.
            tracking_id: Unique tracking ID.

        Returns:
            HTML with tracking pixel injected.
        """
        # Create tracking pixel URL
        pixel_url = f"{self.tracking_base_url}/t/o/{tracking_id}.gif"

        # Create invisible tracking pixel
        tracking_pixel = f'<img src="{pixel_url}" width="1" height="1" style="display:none;" alt="" />'

        # Try to inject before </body> tag
        if "</body>" in html.lower():
            # Find </body> case-insensitively
            pattern = re.compile(r"(</body>)", re.IGNORECASE)
            html = pattern.sub(f"{tracking_pixel}\\1", html, count=1)
        else:
            # Append to end if no body tag
            html += tracking_pixel

        return html

    def wrap_links(self, html: str, tracking_id: str) -> str:
        """Wrap links in HTML for click tracking.

        Args:
            html: HTML email body.
            tracking_id: Unique tracking ID.

        Returns:
            HTML with links wrapped for tracking.
        """
        # Pattern to match href attributes in anchor tags
        # Excludes mailto: and tel: links
        pattern = re.compile(
            r'<a\s+([^>]*?)href=["\'](?!mailto:|tel:)([^"\']+)["\']([^>]*)>',
            re.IGNORECASE,
        )

        def replace_link(match: re.Match) -> str:
            before_href = match.group(1)
            original_url = match.group(2)
            after_href = match.group(3)

            # Skip if already wrapped or is tracking URL
            if "/t/c/" in original_url:
                return match.group(0)

            # Encode the original URL
            encoded_url = urllib.parse.quote(original_url, safe="")

            # Create tracking URL
            tracking_url = f"{self.tracking_base_url}/t/c/{tracking_id}?url={encoded_url}"

            return f'<a {before_href}href="{tracking_url}"{after_href}>'

        return pattern.sub(replace_link, html)

    def prepare_email_for_sending(self, email: Email) -> tuple[str, str]:
        """Prepare email content with tracking.

        Args:
            email: Email model instance.

        Returns:
            Tuple of (html_with_tracking, text_body).
        """
        html = email.body_html or self._text_to_html(email.body_text)

        # Inject tracking pixel
        html = self.inject_tracking_pixel(html, email.tracking_id)

        # Wrap links for click tracking
        html = self.wrap_links(html, email.tracking_id)

        return html, email.body_text

    def _text_to_html(self, text: str) -> str:
        """Convert plain text to basic HTML.

        Args:
            text: Plain text content.

        Returns:
            Basic HTML version.
        """
        # Escape HTML characters
        html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Convert newlines to paragraphs
        paragraphs = html.split("\n\n")
        html_paragraphs = [f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip()]

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    {''.join(html_paragraphs)}
</body>
</html>"""

    async def send_email(
        self,
        db: AsyncSession,
        email: Email,
        lead: Lead | None = None,
    ) -> EmailSendResult:
        """Send a single email.

        Args:
            db: Database session.
            email: Email to send.
            lead: Associated lead (loaded if not provided).

        Returns:
            EmailSendResult with status.
        """
        # Load lead if not provided
        if lead is None:
            lead = await db.get(Lead, email.lead_id)
            if not lead:
                return EmailSendResult(
                    email_id=email.id,
                    success=False,
                    error="Lead not found",
                )

        # Check if lead has email address
        if not lead.email:
            return EmailSendResult(
                email_id=email.id,
                success=False,
                error="Lead has no email address",
            )

        # Check email status
        if email.status != EmailStatus.PENDING:
            return EmailSendResult(
                email_id=email.id,
                success=False,
                error=f"Email status is {email.status.value}, not PENDING",
            )

        # Prepare email content with tracking
        html_body, text_body = self.prepare_email_for_sending(email)

        # Update status to SENDING
        email.status = EmailStatus.SENDING
        db.add(email)
        await db.commit()

        # Send email
        result = await self.smtp.send(
            to_email=lead.email,
            subject=email.subject,
            body_html=html_body,
            body_text=text_body,
            headers={
                "X-Tracking-ID": email.tracking_id,
            },
        )

        if result.success:
            # Update email status to SENT
            email.status = EmailStatus.SENT
            email.sent_at = datetime.now()
            email.message_id = result.message_id

            # Update lead status
            if lead.status in (LeadStatus.QUALIFIED, LeadStatus.SEQUENCED):
                lead.status = LeadStatus.CONTACTED
                lead.last_contacted_at = datetime.now()
                db.add(lead)

            db.add(email)
            await db.commit()

            return EmailSendResult(
                email_id=email.id,
                success=True,
                message_id=result.message_id,
                tracking_id=email.tracking_id,
            )
        else:
            # Check if it's a bounce
            if "refused" in result.error.lower() or "rejected" in result.error.lower():
                email.status = EmailStatus.BOUNCED
                email.bounced_at = datetime.now()
                lead.status = LeadStatus.BOUNCED
                db.add(lead)
            else:
                # Reset to PENDING for retry
                email.status = EmailStatus.PENDING

            db.add(email)
            await db.commit()

            return EmailSendResult(
                email_id=email.id,
                success=False,
                error=result.error,
            )

    async def send_batch(
        self,
        db: AsyncSession,
        emails: list[Email],
        delay_between: int = 0,
    ) -> list[EmailSendResult]:
        """Send multiple emails.

        Args:
            db: Database session.
            emails: Emails to send.
            delay_between: Delay between sends in seconds.

        Returns:
            List of EmailSendResult for each email.
        """
        import asyncio

        results = []

        for i, email in enumerate(emails):
            result = await self.send_email(db, email)
            results.append(result)

            # Delay between sends (except for last email)
            if delay_between > 0 and i < len(emails) - 1:
                await asyncio.sleep(delay_between)

        return results

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
        from sqlalchemy import select
        from src.models.event import Event

        # Find email by tracking ID
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await db.execute(stmt)
        email = result.scalar_one_or_none()

        if not email:
            return False

        # Record open
        email.record_open()

        # Create event
        event = Event(
            email_id=email.id,
            event_type="open",
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
        from sqlalchemy import select
        from src.models.event import Event

        # Find email by tracking ID
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await db.execute(stmt)
        email = result.scalar_one_or_none()

        if not email:
            return None

        # Record click
        email.record_click()

        # Create event
        event = Event(
            email_id=email.id,
            event_type="click",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"url": url},
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

    async def record_bounce(
        self,
        db: AsyncSession,
        message_id: str,
        bounce_type: str = "hard",
        reason: str | None = None,
    ) -> bool:
        """Record an email bounce event.

        Args:
            db: Database session.
            message_id: SMTP message ID.
            bounce_type: Type of bounce (hard/soft).
            reason: Bounce reason.

        Returns:
            True if bounce was recorded successfully.
        """
        from sqlalchemy import select
        from src.models.event import Event

        # Find email by message ID
        stmt = select(Email).where(Email.message_id == message_id)
        result = await db.execute(stmt)
        email = result.scalar_one_or_none()

        if not email:
            return False

        # Record bounce
        email.record_bounce()

        # Create event
        event = Event(
            email_id=email.id,
            event_type="bounce",
            metadata={"bounce_type": bounce_type, "reason": reason},
        )
        db.add(event)

        # Update lead status
        lead = await db.get(Lead, email.lead_id)
        if lead:
            lead.status = LeadStatus.BOUNCED
            db.add(lead)

        db.add(email)
        await db.commit()

        return True
