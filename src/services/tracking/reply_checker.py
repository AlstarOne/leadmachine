"""IMAP reply checker service."""

import asyncio
import email
import re
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.email import Email, EmailStatus
from src.models.lead import Lead


@dataclass
class Reply:
    """Parsed reply from inbox."""

    message_id: str
    from_email: str
    from_name: str | None
    subject: str
    in_reply_to: str | None
    references: list[str]
    date: datetime | None
    body_preview: str

    # Matched data
    matched_email_id: int | None = None
    matched_lead_id: int | None = None


class ReplyChecker:
    """Service for checking inbox for replies."""

    def __init__(
        self,
        imap_host: str | None = None,
        imap_port: int | None = None,
        imap_user: str | None = None,
        imap_password: str | None = None,
        imap_ssl: bool = True,
    ) -> None:
        """Initialize reply checker.

        Args:
            imap_host: IMAP server hostname.
            imap_port: IMAP server port.
            imap_user: IMAP username.
            imap_password: IMAP password.
            imap_ssl: Use SSL for IMAP.
        """
        settings = get_settings()
        self.host = imap_host or settings.imap_host
        self.port = imap_port or settings.imap_port
        self.user = imap_user or settings.imap_user
        self.password = imap_password or settings.imap_password
        self.use_ssl = imap_ssl

    def _decode_header_value(self, header_value: str | None) -> str:
        """Decode email header value."""
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
                except (LookupError, TypeError):
                    decoded_parts.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(part)

        return " ".join(decoded_parts)

    def _parse_email_address(self, header: str | None) -> tuple[str, str | None]:
        """Parse email address from header.

        Args:
            header: Email header value.

        Returns:
            Tuple of (email_address, display_name).
        """
        if not header:
            return "", None

        decoded = self._decode_header_value(header)

        # Try to extract email from "Name <email@example.com>" format
        match = re.search(r"<([^>]+)>", decoded)
        if match:
            email_addr = match.group(1).strip()
            name_part = decoded[:match.start()].strip().strip('"').strip("'")
            return email_addr, name_part if name_part else None

        # Just an email address
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", decoded)
        if email_match:
            return email_match.group(0), None

        return decoded, None

    def _parse_references(self, references: str | None) -> list[str]:
        """Parse References header into list of message IDs."""
        if not references:
            return []

        # Extract all message IDs (format: <message-id@domain>)
        return re.findall(r"<[^>]+>", references)

    def _get_body_preview(self, msg: email.message.Message, max_length: int = 200) -> str:
        """Extract body preview from email message."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        try:
                            body = payload.decode("utf-8", errors="replace")
                        except Exception:
                            body = str(payload)
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    body = payload.decode("utf-8", errors="replace")
                except Exception:
                    body = str(payload)

        # Clean up and truncate
        body = " ".join(body.split())  # Normalize whitespace
        if len(body) > max_length:
            body = body[:max_length] + "..."

        return body

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Parse email date header."""
        if not date_str:
            return None

        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return None

    async def check_inbox(
        self,
        db: AsyncSession,
        folder: str = "INBOX",
        unseen_only: bool = True,
        limit: int = 50,
    ) -> list[Reply]:
        """Check inbox for new replies.

        Args:
            db: Database session.
            folder: IMAP folder to check.
            unseen_only: Only check unseen messages.
            limit: Maximum messages to process.

        Returns:
            List of Reply objects for matched replies.
        """
        try:
            import aioimaplib
        except ImportError:
            # Fallback to sync imaplib if aioimaplib not available
            return await self._check_inbox_sync(db, folder, unseen_only, limit)

        replies: list[Reply] = []

        try:
            # Connect to IMAP
            if self.use_ssl:
                client = aioimaplib.IMAP4_SSL(host=self.host, port=self.port or 993)
            else:
                client = aioimaplib.IMAP4(host=self.host, port=self.port or 143)

            await client.wait_hello_from_server()

            # Login
            await client.login(self.user, self.password)

            # Select folder
            await client.select(folder)

            # Search for messages
            search_criteria = "UNSEEN" if unseen_only else "ALL"
            _, data = await client.search(search_criteria)

            if not data or not data[0]:
                await client.logout()
                return []

            message_nums = data[0].split()[-limit:]  # Get latest messages

            for num in message_nums:
                try:
                    _, msg_data = await client.fetch(num.decode(), "(RFC822)")
                    if not msg_data:
                        continue

                    raw_email = msg_data[1]
                    if isinstance(raw_email, tuple):
                        raw_email = raw_email[1]

                    msg = email.message_from_bytes(raw_email)

                    reply = self._parse_message(msg)
                    if reply:
                        # Try to match to our emails
                        matched = await self._match_reply(db, reply)
                        if matched:
                            replies.append(reply)

                except Exception:
                    continue

            await client.logout()

        except Exception as e:
            # Log error but don't raise
            print(f"IMAP error: {e}")

        return replies

    async def _check_inbox_sync(
        self,
        db: AsyncSession,
        folder: str = "INBOX",
        unseen_only: bool = True,
        limit: int = 50,
    ) -> list[Reply]:
        """Sync fallback for checking inbox."""
        import imaplib

        replies: list[Reply] = []

        try:
            # Connect to IMAP
            if self.use_ssl:
                client = imaplib.IMAP4_SSL(self.host, self.port or 993)
            else:
                client = imaplib.IMAP4(self.host, self.port or 143)

            # Login
            client.login(self.user, self.password)

            # Select folder
            client.select(folder)

            # Search for messages
            search_criteria = "UNSEEN" if unseen_only else "ALL"
            _, data = client.search(None, search_criteria)

            if not data or not data[0]:
                client.logout()
                return []

            message_nums = data[0].split()[-limit:]

            for num in message_nums:
                try:
                    _, msg_data = client.fetch(num, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    reply = self._parse_message(msg)
                    if reply:
                        matched = await self._match_reply(db, reply)
                        if matched:
                            replies.append(reply)

                except Exception:
                    continue

            client.logout()

        except Exception as e:
            print(f"IMAP error: {e}")

        return replies

    def _parse_message(self, msg: email.message.Message) -> Reply | None:
        """Parse email message into Reply object."""
        message_id = msg.get("Message-ID", "")
        from_header = msg.get("From", "")
        subject = self._decode_header_value(msg.get("Subject", ""))
        in_reply_to = msg.get("In-Reply-To", "")
        references = self._parse_references(msg.get("References", ""))
        date = self._parse_date(msg.get("Date"))

        from_email, from_name = self._parse_email_address(from_header)

        if not from_email:
            return None

        body_preview = self._get_body_preview(msg)

        return Reply(
            message_id=message_id,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            in_reply_to=in_reply_to,
            references=references,
            date=date,
            body_preview=body_preview,
        )

    async def _match_reply(self, db: AsyncSession, reply: Reply) -> bool:
        """Try to match a reply to our sent emails.

        Args:
            db: Database session.
            reply: Reply object.

        Returns:
            True if matched to one of our emails.
        """
        # Method 1: Match by In-Reply-To header
        if reply.in_reply_to:
            stmt = select(Email).where(Email.message_id == reply.in_reply_to)
            result = await db.execute(stmt)
            email_obj = result.scalar_one_or_none()

            if email_obj:
                reply.matched_email_id = email_obj.id
                reply.matched_lead_id = email_obj.lead_id
                return True

        # Method 2: Match by References header
        for ref in reply.references:
            stmt = select(Email).where(Email.message_id == ref)
            result = await db.execute(stmt)
            email_obj = result.scalar_one_or_none()

            if email_obj:
                reply.matched_email_id = email_obj.id
                reply.matched_lead_id = email_obj.lead_id
                return True

        # Method 3: Match by sender email to our leads
        stmt = select(Lead).where(Lead.email == reply.from_email)
        result = await db.execute(stmt)
        lead = result.scalar_one_or_none()

        if lead:
            # Find most recent sent email to this lead
            email_stmt = (
                select(Email)
                .where(
                    Email.lead_id == lead.id,
                    Email.status == EmailStatus.SENT,
                )
                .order_by(Email.sent_at.desc())
                .limit(1)
            )
            email_result = await db.execute(email_stmt)
            email_obj = email_result.scalar_one_or_none()

            if email_obj:
                reply.matched_email_id = email_obj.id
                reply.matched_lead_id = lead.id
                return True

        return False

    async def process_replies(
        self,
        db: AsyncSession,
        replies: list[Reply],
    ) -> dict[str, Any]:
        """Process matched replies.

        Args:
            db: Database session.
            replies: List of Reply objects.

        Returns:
            Dictionary with processing results.
        """
        from src.services.tracking.tracker import TrackingService

        tracker = TrackingService()
        processed = 0
        errors = []

        for reply in replies:
            if not reply.matched_email_id:
                continue

            try:
                success = await tracker.record_reply(
                    db=db,
                    email_id=reply.matched_email_id,
                    from_email=reply.from_email,
                    subject=reply.subject,
                    message_id=reply.message_id,
                )

                if success:
                    processed += 1

            except Exception as e:
                errors.append(f"Error processing reply from {reply.from_email}: {str(e)}")

        return {
            "processed": processed,
            "total": len(replies),
            "errors": errors,
        }

    async def health_check(self) -> bool:
        """Check if IMAP server is accessible.

        Returns:
            True if server is accessible, False otherwise.
        """
        try:
            import imaplib

            if self.use_ssl:
                client = imaplib.IMAP4_SSL(self.host, self.port or 993)
            else:
                client = imaplib.IMAP4(self.host, self.port or 143)

            client.login(self.user, self.password)
            client.logout()
            return True

        except Exception:
            return False
