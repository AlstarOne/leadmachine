"""Tests for email sending services."""

from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.models.lead import Lead, LeadStatus, LeadClassification
from src.services.email.scheduler import SchedulerService, SendSlot, RateLimitStatus, CET
from src.services.email.sender import EmailSender, EmailSendResult
from src.services.email.smtp import SMTPService, SendResult


class TestSMTPService:
    """Tests for SMTP service."""

    def test_smtp_service_init_defaults(self) -> None:
        """Test SMTP service initialization with defaults."""
        with patch("src.services.email.smtp.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_user="user@test.com",
                smtp_password="password123",
                smtp_from_email="noreply@test.com",
            )
            service = SMTPService()

            assert service.host == "smtp.test.com"
            assert service.port == 587
            assert service.username == "user@test.com"
            assert service.from_email == "noreply@test.com"

    def test_smtp_service_init_custom(self) -> None:
        """Test SMTP service with custom values."""
        with patch("src.services.email.smtp.get_settings"):
            service = SMTPService(
                host="custom.smtp.com",
                port=465,
                username="custom@test.com",
                password="custompass",
                from_email="custom@test.com",
                use_tls=True,
            )

            assert service.host == "custom.smtp.com"
            assert service.port == 465
            assert service.use_tls is True

    def test_create_message(self) -> None:
        """Test MIME message creation."""
        with patch("src.services.email.smtp.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_user="",
                smtp_password="",
                smtp_from_email="noreply@test.com",
            )
            service = SMTPService()

            msg = service._create_message(
                to_email="recipient@test.com",
                subject="Test Subject",
                body_html="<p>Hello</p>",
                body_text="Hello",
                headers={"X-Custom": "value"},
            )

            assert msg["To"] == "recipient@test.com"
            assert msg["Subject"] == "Test Subject"
            assert msg["From"] == "noreply@test.com"
            assert msg["X-Custom"] == "value"

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        """Test successful email send."""
        with patch("src.services.email.smtp.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_user="user@test.com",
                smtp_password="password",
                smtp_from_email="noreply@test.com",
            )

            with patch("src.services.email.smtp.aiosmtplib.SMTP") as mock_smtp:
                mock_client = AsyncMock()
                mock_smtp.return_value = mock_client
                mock_client.send_message.return_value = (250, "OK")

                service = SMTPService()
                result = await service.send(
                    to_email="test@example.com",
                    subject="Test",
                    body_html="<p>Test</p>",
                    body_text="Test",
                )

                assert result.success is True
                assert result.message_id is not None

    @pytest.mark.asyncio
    async def test_send_auth_failure(self) -> None:
        """Test email send with authentication failure."""
        with patch("src.services.email.smtp.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_user="user@test.com",
                smtp_password="wrong",
                smtp_from_email="noreply@test.com",
            )

            with patch("src.services.email.smtp.aiosmtplib.SMTP") as mock_smtp:
                import aiosmtplib

                mock_client = AsyncMock()
                mock_smtp.return_value = mock_client
                mock_client.login.side_effect = aiosmtplib.SMTPAuthenticationError(
                    535, "Authentication failed"
                )

                service = SMTPService()
                result = await service.send(
                    to_email="test@example.com",
                    subject="Test",
                    body_html="<p>Test</p>",
                    body_text="Test",
                )

                assert result.success is False
                assert "Authentication" in result.error


class TestEmailSender:
    """Tests for email sender service."""

    def test_inject_tracking_pixel_with_body(self) -> None:
        """Test tracking pixel injection with body tag."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            html = "<html><body><p>Hello</p></body></html>"
            result = sender.inject_tracking_pixel(html, "test-track-123")

            assert "test-track-123.gif" in result
            assert '/t/o/test-track-123.gif"' in result
            assert 'width="1"' in result
            assert 'height="1"' in result

    def test_inject_tracking_pixel_without_body(self) -> None:
        """Test tracking pixel injection without body tag."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            html = "<p>Hello</p>"
            result = sender.inject_tracking_pixel(html, "test-track-456")

            assert "test-track-456.gif" in result

    def test_wrap_links(self) -> None:
        """Test link wrapping for click tracking."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            html = '<a href="https://example.com/page">Link</a>'
            result = sender.wrap_links(html, "track-123")

            assert "/t/c/track-123" in result
            assert "url=https%3A%2F%2Fexample.com%2Fpage" in result

    def test_wrap_links_excludes_mailto(self) -> None:
        """Test that mailto links are not wrapped."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            html = '<a href="mailto:test@example.com">Email</a>'
            result = sender.wrap_links(html, "track-123")

            assert "mailto:test@example.com" in result
            assert "/t/c/" not in result

    def test_wrap_links_excludes_tel(self) -> None:
        """Test that tel links are not wrapped."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            html = '<a href="tel:+31612345678">Call</a>'
            result = sender.wrap_links(html, "track-123")

            assert "tel:+31612345678" in result
            assert "/t/c/" not in result

    def test_text_to_html(self) -> None:
        """Test plain text to HTML conversion."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            text = "Hello\n\nThis is a test."
            result = sender._text_to_html(text)

            assert "<html>" in result
            assert "<p>Hello</p>" in result
            assert "<p>This is a test.</p>" in result

    def test_text_to_html_escapes_html(self) -> None:
        """Test that HTML characters are escaped."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )
            sender = EmailSender()

            text = "Test <script>alert('xss')</script>"
            result = sender._text_to_html(text)

            assert "&lt;script&gt;" in result
            assert "<script>" not in result


class TestSchedulerService:
    """Tests for scheduler service."""

    def test_is_business_hours_weekday_during_hours(self) -> None:
        """Test business hours check during weekday business hours."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Wednesday 10:00 CET
            dt = datetime(2024, 1, 10, 10, 0, tzinfo=CET)
            assert scheduler.is_business_hours(dt) is True

    def test_is_business_hours_weekday_outside_hours(self) -> None:
        """Test business hours check outside business hours."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Wednesday 20:00 CET
            dt = datetime(2024, 1, 10, 20, 0, tzinfo=CET)
            assert scheduler.is_business_hours(dt) is False

    def test_is_business_hours_weekend(self) -> None:
        """Test business hours check on weekend."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Saturday 10:00 CET
            dt = datetime(2024, 1, 13, 10, 0, tzinfo=CET)
            assert scheduler.is_business_hours(dt) is False

    def test_get_next_business_hour_during_hours(self) -> None:
        """Test getting next business hour when currently in business hours."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Wednesday 10:00 CET
            dt = datetime(2024, 1, 10, 10, 0, tzinfo=CET)
            result = scheduler.get_next_business_hour(dt)

            # Should return the same time since we're in business hours
            assert result == dt

    def test_get_next_business_hour_after_hours(self) -> None:
        """Test getting next business hour when after business hours."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Wednesday 18:00 CET (after 17:00)
            dt = datetime(2024, 1, 10, 18, 0, tzinfo=CET)
            result = scheduler.get_next_business_hour(dt)

            # Should be next day at 9:00
            assert result.day == 11
            assert result.hour == 9
            assert result.minute == 0

    def test_get_next_business_hour_friday_evening(self) -> None:
        """Test getting next business hour from Friday evening."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Friday 18:00 CET
            dt = datetime(2024, 1, 12, 18, 0, tzinfo=CET)
            result = scheduler.get_next_business_hour(dt)

            # Should be Monday at 9:00
            assert result.day == 15  # Monday
            assert result.weekday() == 0  # Monday
            assert result.hour == 9

    def test_get_next_send_slot_with_delay(self) -> None:
        """Test getting next send slot adds random delay."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Wednesday 10:00 CET
            dt = datetime(2024, 1, 10, 10, 0, tzinfo=CET)
            slot = scheduler.get_next_send_slot(dt, respect_business_hours=False)

            # Should be at least min_delay_seconds later
            delay = (slot.datetime - dt).total_seconds()
            assert delay >= 120
            assert delay <= 300

    def test_get_random_delay(self) -> None:
        """Test random delay generation."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # Run multiple times to verify range
            for _ in range(20):
                delay = scheduler.get_random_delay()
                assert 120 <= delay <= 300


class TestSchedulerServiceAsync:
    """Async tests for scheduler service."""

    @pytest.fixture
    async def sample_company(self, db_session: AsyncSession) -> Company:
        """Create a sample company."""
        company = Company(
            name="Test Company BV",
            domain="testcompany.nl",
            industry="technology",
            location="Amsterdam",
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)
        return company

    @pytest.fixture
    async def sample_lead(
        self, db_session: AsyncSession, sample_company: Company
    ) -> Lead:
        """Create a sample lead."""
        lead = Lead(
            company_id=sample_company.id,
            first_name="Jan",
            last_name="de Vries",
            email="jan@testcompany.nl",
            job_title="CTO",
            status=LeadStatus.SEQUENCED,
            icp_score=75,
            classification=LeadClassification.HOT,
        )
        db_session.add(lead)
        await db_session.commit()
        await db_session.refresh(lead)
        return lead

    @pytest.fixture
    async def sample_emails(
        self, db_session: AsyncSession, sample_lead: Lead
    ) -> list[Email]:
        """Create sample emails."""
        now = datetime.now(CET)
        emails = [
            Email(
                lead_id=sample_lead.id,
                sequence_step=EmailSequenceStep.INITIAL,
                scheduled_day=0,
                subject="Initial email",
                body_text="Hello",
                body_html="<p>Hello</p>",
                status=EmailStatus.PENDING,
                scheduled_at=now - timedelta(minutes=5),
            ),
            Email(
                lead_id=sample_lead.id,
                sequence_step=EmailSequenceStep.FOLLOWUP_1,
                scheduled_day=3,
                subject="Follow-up 1",
                body_text="Following up",
                body_html="<p>Following up</p>",
                status=EmailStatus.PENDING,
                scheduled_at=now + timedelta(days=3),
            ),
        ]
        for email in emails:
            db_session.add(email)
        await db_session.commit()
        return emails

    @pytest.mark.asyncio
    async def test_check_daily_limit_under_limit(
        self, db_session: AsyncSession
    ) -> None:
        """Test rate limit check when under limit."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            status = await scheduler.check_daily_limit(db_session)

            assert status.can_send is True
            assert status.remaining_today == 50
            assert status.emails_sent_today == 0

    @pytest.mark.asyncio
    async def test_get_emails_to_send(
        self, db_session: AsyncSession, sample_emails: list[Email]
    ) -> None:
        """Test getting emails ready to send."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            emails = await scheduler.get_emails_to_send(db_session)

            # Only the first email should be due (scheduled in past)
            assert len(emails) == 1
            assert emails[0].sequence_step == EmailSequenceStep.INITIAL

    @pytest.mark.asyncio
    async def test_pause_sequence(
        self, db_session: AsyncSession, sample_lead: Lead, sample_emails: list[Email]
    ) -> None:
        """Test pausing email sequence."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            count = await scheduler.pause_sequence(db_session, sample_lead.id)

            assert count == 2

            # Verify emails are cancelled
            for email in sample_emails:
                await db_session.refresh(email)
                assert email.status == EmailStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_resume_sequence(
        self, db_session: AsyncSession, sample_lead: Lead, sample_emails: list[Email]
    ) -> None:
        """Test resuming paused sequence."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            # First pause
            await scheduler.pause_sequence(db_session, sample_lead.id)

            # Then resume
            count = await scheduler.resume_sequence(db_session, sample_lead.id)

            assert count == 2

            # Verify emails are pending again
            for email in sample_emails:
                await db_session.refresh(email)
                assert email.status == EmailStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_queue_status(
        self, db_session: AsyncSession, sample_emails: list[Email]
    ) -> None:
        """Test getting queue status."""
        with patch("src.services.email.scheduler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                email_daily_limit=50,
                email_min_delay_seconds=120,
                email_max_delay_seconds=300,
            )
            scheduler = SchedulerService()

            status = await scheduler.get_queue_status(db_session)

            assert status["pending_count"] == 2
            assert status["due_count"] == 1
            assert status["daily_limit"] == 50


class TestEmailSenderAsync:
    """Async tests for email sender."""

    @pytest.fixture
    async def sample_company(self, db_session: AsyncSession) -> Company:
        """Create a sample company."""
        company = Company(
            name="Test Company BV",
            domain="testcompany.nl",
            industry="technology",
            location="Amsterdam",
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)
        return company

    @pytest.fixture
    async def sample_lead(
        self, db_session: AsyncSession, sample_company: Company
    ) -> Lead:
        """Create a sample lead."""
        lead = Lead(
            company_id=sample_company.id,
            first_name="Jan",
            last_name="de Vries",
            email="jan@testcompany.nl",
            job_title="CTO",
            status=LeadStatus.SEQUENCED,
            icp_score=75,
            classification=LeadClassification.HOT,
        )
        db_session.add(lead)
        await db_session.commit()
        await db_session.refresh(lead)
        return lead

    @pytest.fixture
    async def sample_email(
        self, db_session: AsyncSession, sample_lead: Lead
    ) -> Email:
        """Create a sample email."""
        email = Email(
            lead_id=sample_lead.id,
            sequence_step=EmailSequenceStep.INITIAL,
            scheduled_day=0,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            status=EmailStatus.PENDING,
        )
        db_session.add(email)
        await db_session.commit()
        await db_session.refresh(email)
        return email

    @pytest.mark.asyncio
    async def test_send_email_lead_not_found(
        self, db_session: AsyncSession
    ) -> None:
        """Test sending email when lead not found."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            # Create a mock email with invalid lead_id (not in DB)
            mock_email = MagicMock()
            mock_email.id = 1
            mock_email.lead_id = 99999
            mock_email.status = EmailStatus.PENDING

            sender = EmailSender()
            result = await sender.send_email(db_session, mock_email)

            assert result.success is False
            assert "Lead not found" in result.error

    @pytest.mark.asyncio
    async def test_send_email_no_email_address(
        self, db_session: AsyncSession, sample_email: Email, sample_lead: Lead
    ) -> None:
        """Test sending email when lead has no email."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            # Remove email from lead
            sample_lead.email = None
            db_session.add(sample_lead)
            await db_session.commit()

            sender = EmailSender()
            result = await sender.send_email(db_session, sample_email, sample_lead)

            assert result.success is False
            assert "no email address" in result.error

    @pytest.mark.asyncio
    async def test_send_email_not_pending(
        self, db_session: AsyncSession, sample_email: Email, sample_lead: Lead
    ) -> None:
        """Test sending email that's not in PENDING status."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            # Change status to SENT
            sample_email.status = EmailStatus.SENT
            sample_email.sent_at = datetime.now()
            db_session.add(sample_email)
            await db_session.commit()

            sender = EmailSender()
            result = await sender.send_email(db_session, sample_email, sample_lead)

            assert result.success is False
            assert "PENDING" in result.error

    @pytest.mark.asyncio
    async def test_record_open(
        self, db_session: AsyncSession, sample_email: Email
    ) -> None:
        """Test recording email open."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            # Set email to SENT status first
            sample_email.status = EmailStatus.SENT
            sample_email.sent_at = datetime.now()
            db_session.add(sample_email)
            await db_session.commit()

            sender = EmailSender()
            result = await sender.record_open(
                db_session,
                sample_email.tracking_id,
                ip_address="127.0.0.1",
                user_agent="Test Browser",
            )

            assert result is True

            # Check email was updated
            await db_session.refresh(sample_email)
            assert sample_email.open_count >= 1
            assert sample_email.opened_at is not None

    @pytest.mark.asyncio
    async def test_record_open_not_found(
        self, db_session: AsyncSession
    ) -> None:
        """Test recording open for non-existent email."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            sender = EmailSender()
            result = await sender.record_open(
                db_session,
                "nonexistent-tracking-id",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_record_click(
        self, db_session: AsyncSession, sample_email: Email
    ) -> None:
        """Test recording link click."""
        with patch("src.services.email.sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                tracking_base_url="https://track.example.com",
            )

            # Set email to SENT status first
            sample_email.status = EmailStatus.SENT
            sample_email.sent_at = datetime.now()
            db_session.add(sample_email)
            await db_session.commit()

            sender = EmailSender()
            url = await sender.record_click(
                db_session,
                sample_email.tracking_id,
                url="https://example.com/page",
                ip_address="127.0.0.1",
            )

            assert url == "https://example.com/page"

            # Check email was updated
            await db_session.refresh(sample_email)
            assert sample_email.click_count >= 1
            assert sample_email.clicked_at is not None
