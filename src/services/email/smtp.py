"""SMTP service for sending emails."""

import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib

from src.config import get_settings


@dataclass
class SendResult:
    """Result of sending an email."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    smtp_response: str | None = None


class SMTPService:
    """Service for sending emails via SMTP."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        use_tls: bool = False,
        use_starttls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        """Initialize SMTP service.

        Args:
            host: SMTP server hostname.
            port: SMTP server port.
            username: SMTP username (optional).
            password: SMTP password (optional).
            from_email: Default from email address.
            use_tls: Use implicit TLS (port 465).
            use_starttls: Use STARTTLS (port 25/587).
            timeout: Connection timeout in seconds.
        """
        settings = get_settings()
        self.host = host or settings.smtp_host
        self.port = port or settings.smtp_port
        self.username = username or settings.smtp_user
        self.password = password or settings.smtp_password
        self.from_email = from_email or settings.smtp_from_email
        self.use_tls = use_tls
        self.use_starttls = use_starttls
        self.timeout = timeout

    def _create_message(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
        from_email: str | None = None,
        reply_to: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MIMEMultipart:
        """Create MIME message.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body_html: HTML body content.
            body_text: Plain text body content.
            from_email: Sender email address.
            reply_to: Reply-to address.
            headers: Additional headers.

        Returns:
            MIME multipart message.
        """
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email or self.from_email
        msg["To"] = to_email

        if reply_to:
            msg["Reply-To"] = reply_to

        # Add custom headers
        if headers:
            for key, value in headers.items():
                msg[key] = value

        # Attach plain text and HTML parts
        part_text = MIMEText(body_text, "plain", "utf-8")
        part_html = MIMEText(body_html, "html", "utf-8")

        msg.attach(part_text)
        msg.attach(part_html)

        return msg

    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
        from_email: str | None = None,
        reply_to: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> SendResult:
        """Send an email.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body_html: HTML body content.
            body_text: Plain text body content.
            from_email: Sender email address.
            reply_to: Reply-to address.
            headers: Additional headers.

        Returns:
            SendResult with success status and message ID.
        """
        msg = self._create_message(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            from_email=from_email,
            reply_to=reply_to,
            headers=headers,
        )

        try:
            # Create SSL context if needed
            tls_context = None
            if self.use_tls or self.use_starttls:
                tls_context = ssl.create_default_context()
                # For development/testing, allow self-signed certificates
                tls_context.check_hostname = False
                tls_context.verify_mode = ssl.CERT_NONE

            # Connect and send
            smtp = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=self.timeout,
                use_tls=self.use_tls,
                tls_context=tls_context if self.use_tls else None,
            )

            await smtp.connect()

            # STARTTLS if configured
            if self.use_starttls and not self.use_tls:
                await smtp.starttls(tls_context=tls_context)

            # Login if credentials provided
            if self.username and self.password:
                await smtp.login(self.username, self.password)

            # Send email
            response = await smtp.send_message(msg)

            await smtp.quit()

            # Extract message ID from response or generate one
            message_id = msg.get("Message-ID", "")
            if not message_id:
                import uuid
                message_id = f"<{uuid.uuid4()}@{self.host}>"

            return SendResult(
                success=True,
                message_id=message_id,
                smtp_response=str(response),
            )

        except aiosmtplib.SMTPAuthenticationError as e:
            return SendResult(
                success=False,
                error=f"Authentication failed: {str(e)}",
            )
        except aiosmtplib.SMTPConnectError as e:
            return SendResult(
                success=False,
                error=f"Connection failed: {str(e)}",
            )
        except aiosmtplib.SMTPRecipientsRefused as e:
            return SendResult(
                success=False,
                error=f"Recipient refused: {str(e)}",
            )
        except Exception as e:
            return SendResult(
                success=False,
                error=f"Send failed: {str(e)}",
            )

    async def health_check(self) -> bool:
        """Check if SMTP server is accessible.

        Returns:
            True if server is accessible, False otherwise.
        """
        try:
            tls_context = None
            if self.use_tls or self.use_starttls:
                tls_context = ssl.create_default_context()
                tls_context.check_hostname = False
                tls_context.verify_mode = ssl.CERT_NONE

            smtp = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=self.timeout,
                use_tls=self.use_tls,
                tls_context=tls_context if self.use_tls else None,
            )

            await smtp.connect()

            if self.use_starttls and not self.use_tls:
                await smtp.starttls(tls_context=tls_context)

            await smtp.quit()
            return True

        except Exception:
            return False

    async def verify_recipient(self, email: str) -> tuple[bool, str]:
        """Verify if recipient email is valid (VRFY command).

        Note: Many servers disable VRFY for security reasons.

        Args:
            email: Email address to verify.

        Returns:
            Tuple of (is_valid, message).
        """
        try:
            tls_context = None
            if self.use_tls or self.use_starttls:
                tls_context = ssl.create_default_context()
                tls_context.check_hostname = False
                tls_context.verify_mode = ssl.CERT_NONE

            smtp = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=self.timeout,
                use_tls=self.use_tls,
                tls_context=tls_context if self.use_tls else None,
            )

            await smtp.connect()

            if self.use_starttls and not self.use_tls:
                await smtp.starttls(tls_context=tls_context)

            # Try VRFY command
            code, message = await smtp.vrfy(email)

            await smtp.quit()

            # Codes 250, 251, 252 indicate success or partial success
            is_valid = code in (250, 251, 252)
            return is_valid, message.decode() if isinstance(message, bytes) else message

        except Exception as e:
            return False, str(e)
