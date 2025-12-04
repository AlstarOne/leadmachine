"""Tests for tracking system (Phase 7)."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company, CompanySource
from src.models.lead import Lead, LeadStatus
from src.models.email import Email, EmailStatus
from src.models.event import Event, EventType
from src.services.tracking import TrackingService, TrackingStats, ReplyChecker, Reply


# ============= TrackingService Tests =============


class TestTrackingPixel:
    """Tests for tracking pixel functionality."""

    @pytest.mark.asyncio
    async def test_tracking_pixel_returns_gif(self, client: AsyncClient) -> None:
        """Test that tracking pixel endpoint returns a 1x1 GIF."""
        response = await client.get("/t/o/test-tracking-id.gif")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/gif"
        # Check it's the expected 1x1 transparent GIF
        assert response.content == TrackingService.TRACKING_PIXEL

    @pytest.mark.asyncio
    async def test_tracking_pixel_no_cache_headers(self, client: AsyncClient) -> None:
        """Test that tracking pixel has no-cache headers."""
        response = await client.get("/t/o/test-tracking-id.gif")

        assert response.status_code == 200
        assert "no-store" in response.headers.get("cache-control", "")
        assert "no-cache" in response.headers.get("cache-control", "")

    @pytest.mark.asyncio
    async def test_open_event_logged(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test that an open event is created when tracking pixel is loaded."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="unique-tracking-123",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Request tracking pixel
        response = await client.get(
            "/t/o/unique-tracking-123.gif",
            headers={
                "User-Agent": "TestBrowser/1.0",
                "X-Forwarded-For": "192.168.1.1",
            },
        )

        assert response.status_code == 200

        # Verify event was logged
        from sqlalchemy import select
        stmt = select(Event).where(Event.email_id == email.id)
        result = await db_session.execute(stmt)
        events = list(result.scalars().all())

        assert len(events) >= 1
        open_event = next((e for e in events if e.event_type == EventType.OPEN), None)
        assert open_event is not None
        assert open_event.ip_address == "192.168.1.1"
        assert open_event.user_agent == "TestBrowser/1.0"

    @pytest.mark.asyncio
    async def test_open_updates_email_stats(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test that open event updates email open_count and opened_at."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="tracking-open-test",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Request tracking pixel twice
        await client.get("/t/o/tracking-open-test.gif")
        await client.get("/t/o/tracking-open-test.gif")

        # Refresh email from DB
        await db_session.refresh(email)

        assert email.open_count == 2
        assert email.opened_at is not None


class TestClickTracking:
    """Tests for click tracking functionality."""

    @pytest.mark.asyncio
    async def test_click_redirects_to_url(self, client: AsyncClient) -> None:
        """Test that click endpoint redirects to the original URL."""
        target_url = "https://example.com/page"
        response = await client.get(
            f"/t/c/test-tracking-id?url={target_url}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == target_url

    @pytest.mark.asyncio
    async def test_click_decodes_url(self, client: AsyncClient) -> None:
        """Test that click endpoint properly decodes URL-encoded URLs."""
        target_url = "https://example.com/page?param=value&other=test"
        encoded_url = "https%3A%2F%2Fexample.com%2Fpage%3Fparam%3Dvalue%26other%3Dtest"

        response = await client.get(
            f"/t/c/test-tracking-id?url={encoded_url}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == target_url

    @pytest.mark.asyncio
    async def test_click_event_logged(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test that a click event is created when link is clicked."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="click-tracking-123",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        target_url = "https://example.com/clicked-link"

        # Click the link
        response = await client.get(
            f"/t/c/click-tracking-123?url={target_url}",
            headers={
                "User-Agent": "TestBrowser/1.0",
                "X-Real-IP": "10.0.0.1",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify event was logged
        from sqlalchemy import select
        stmt = select(Event).where(Event.email_id == email.id)
        result = await db_session.execute(stmt)
        events = list(result.scalars().all())

        click_event = next((e for e in events if e.event_type == EventType.CLICK), None)
        assert click_event is not None
        assert click_event.clicked_url == target_url
        assert click_event.ip_address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_click_updates_email_stats(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test that click event updates email click_count and clicked_at."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="click-stats-test",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Click links
        await client.get("/t/c/click-stats-test?url=https://example.com/1", follow_redirects=False)
        await client.get("/t/c/click-stats-test?url=https://example.com/2", follow_redirects=False)
        await client.get("/t/c/click-stats-test?url=https://example.com/3", follow_redirects=False)

        # Refresh email from DB
        await db_session.refresh(email)

        assert email.click_count == 3
        assert email.clicked_at is not None


class TestTrackingStats:
    """Tests for tracking statistics."""

    @pytest.mark.asyncio
    async def test_get_overall_stats(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting overall tracking statistics."""
        # Get stats - just verify endpoint works and returns correct structure
        response = await client.get("/api/tracking/stats?days=30")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "total_sent" in data
        assert "total_opens" in data
        assert "unique_opens" in data
        assert "total_clicks" in data
        assert "unique_clicks" in data
        assert "total_replies" in data
        assert "total_bounces" in data
        assert "open_rate" in data
        assert "click_rate" in data
        assert "reply_rate" in data
        assert "bounce_rate" in data

    @pytest.mark.asyncio
    async def test_get_tracking_summary(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting tracking summary."""
        response = await client.get("/api/tracking/summary")

        assert response.status_code == 200
        data = response.json()

        assert "total_sent" in data
        assert "unique_opens" in data
        assert "unique_clicks" in data
        assert "open_rate" in data
        assert "click_rate" in data

    @pytest.mark.asyncio
    async def test_get_daily_stats(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting daily statistics."""
        response = await client.get("/api/tracking/daily?days=7")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        # Should have entries for each day
        assert len(data) <= 7

    @pytest.mark.asyncio
    async def test_get_top_links(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting top clicked links."""
        response = await client.get("/api/tracking/top-links?limit=10&days=30")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_events(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting tracking events."""
        response = await client.get("/api/tracking/events?limit=50")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_events_by_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting events filtered by type."""
        response = await client.get("/api/tracking/events?event_type=open")

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        for event in data:
            assert event["type"] == "open"

    @pytest.mark.asyncio
    async def test_get_events_invalid_type(
        self,
        client: AsyncClient,
    ) -> None:
        """Test getting events with invalid type returns error."""
        response = await client.get("/api/tracking/events?event_type=invalid")

        assert response.status_code == 400


class TestLeadEngagement:
    """Tests for lead engagement tracking."""

    @pytest.mark.asyncio
    async def test_get_lead_engagement(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting engagement data for a lead."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="engagement-test",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
            open_count=5,
            click_count=2,
        )
        db_session.add(email)
        await db_session.commit()

        # Get engagement
        response = await client.get(f"/api/tracking/lead/{lead.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["lead_id"] == lead.id
        assert data["lead_name"] == "Test User"
        assert data["emails_sent"] >= 1
        assert data["opens"] >= 5
        assert data["clicks"] >= 2

    @pytest.mark.asyncio
    async def test_get_lead_engagement_not_found(
        self,
        client: AsyncClient,
    ) -> None:
        """Test getting engagement for non-existent lead returns 404."""
        response = await client.get("/api/tracking/lead/99999")

        assert response.status_code == 404


class TestEmailTracking:
    """Tests for individual email tracking."""

    @pytest.mark.asyncio
    async def test_get_email_tracking(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test getting tracking data for a specific email."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="test@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="email-tracking-test",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Get email tracking
        response = await client.get(f"/api/tracking/email/{email.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["email_id"] == email.id
        assert data["tracking_id"] == "email-tracking-test"
        assert data["status"] == "SENT"
        assert "events" in data

    @pytest.mark.asyncio
    async def test_get_email_tracking_not_found(
        self,
        client: AsyncClient,
    ) -> None:
        """Test getting tracking for non-existent email returns 404."""
        response = await client.get("/api/tracking/email/99999")

        assert response.status_code == 404


# ============= ReplyChecker Tests =============


class TestReplyChecker:
    """Tests for reply checking functionality."""

    def test_reply_dataclass(self) -> None:
        """Test Reply dataclass creation."""
        reply = Reply(
            message_id="<test@example.com>",
            from_email="sender@example.com",
            from_name="Sender Name",
            subject="Re: Test Subject",
            in_reply_to="<original@example.com>",
            references=["<original@example.com>"],
            date=datetime.now(),
            body_preview="Test reply content",
        )

        assert reply.message_id == "<test@example.com>"
        assert reply.from_email == "sender@example.com"
        assert reply.subject == "Re: Test Subject"

    @pytest.mark.asyncio
    async def test_reply_checker_initialization(self) -> None:
        """Test ReplyChecker initializes with settings."""
        with patch("src.services.tracking.reply_checker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                imap_host="imap.example.com",
                imap_port=993,
                imap_user="test@example.com",
                imap_password="password",
            )

            checker = ReplyChecker()

            assert checker.host == "imap.example.com"
            assert checker.port == 993
            assert checker.user == "test@example.com"

    @pytest.mark.asyncio
    async def test_reply_matcher_by_in_reply_to(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test matching reply by In-Reply-To header."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="recipient@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="reply-match-test",
            message_id="<original-message@example.com>",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Create reply that references the original message
        reply = Reply(
            message_id="<reply@example.com>",
            from_email="recipient@test.com",
            from_name="Test User",
            subject="Re: Test Subject",
            in_reply_to="<original-message@example.com>",
            references=["<original-message@example.com>"],
            date=datetime.now(),
            body_preview="Thanks for reaching out!",
        )

        checker = ReplyChecker()
        matched = await checker._match_reply(db_session, reply)

        assert matched is True
        assert reply.matched_email_id == email.id

    @pytest.mark.asyncio
    async def test_reply_matcher_by_sender_email(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test matching reply by sender email address."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="unique-lead@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="sender-match-test",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Create reply without in-reply-to but from the lead's email
        reply = Reply(
            message_id="<reply2@example.com>",
            from_email="unique-lead@test.com",
            from_name="Test User",
            subject="Thanks!",
            in_reply_to=None,
            references=[],
            date=datetime.now(),
            body_preview="Thanks for your email!",
        )

        checker = ReplyChecker()
        matched = await checker._match_reply(db_session, reply)

        assert matched is True
        assert reply.matched_lead_id == lead.id

    @pytest.mark.asyncio
    async def test_process_reply_updates_email_status(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test that processing a reply updates email status to REPLIED."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="reply-status@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="reply-status-test",
            message_id="<reply-status-msg@example.com>",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(email)
        await db_session.commit()

        # Process reply - first match it, then process
        reply = Reply(
            message_id="<reply-received@example.com>",
            from_email="reply-status@test.com",
            from_name="Test User",
            subject="Re: Test Subject",
            in_reply_to="<reply-status-msg@example.com>",
            references=["<reply-status-msg@example.com>"],
            date=datetime.now(),
            body_preview="I'm interested!",
        )

        checker = ReplyChecker()
        # First match the reply to set matched_email_id
        await checker._match_reply(db_session, reply)
        # Then process it
        result = await checker.process_replies(db_session, [reply])

        assert result["processed"] == 1

        # Refresh and check email status
        await db_session.refresh(email)
        assert email.status == EmailStatus.REPLIED
        assert email.replied_at is not None

    @pytest.mark.asyncio
    async def test_process_reply_stops_sequence(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test that a reply stops the email sequence (cancels pending emails)."""
        # Create test data
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.OTHER,
        )
        db_session.add(company)
        await db_session.flush()

        lead = Lead(
            company_id=company.id,
            first_name="Test",
            last_name="User",
            email="stop-sequence@test.com",
            status=LeadStatus.SEQUENCED,
        )
        db_session.add(lead)
        await db_session.flush()

        # Create multiple emails in sequence
        sent_email = Email(
            lead_id=lead.id,
            sequence_step=1,
            subject="Test Subject 1",
            body_text="Test body",
            body_html="<p>Test body</p>",
            tracking_id="stop-seq-1",
            message_id="<stop-seq-msg@example.com>",
            status=EmailStatus.SENT,
            sent_at=datetime.now(),
        )
        db_session.add(sent_email)

        pending_email = Email(
            lead_id=lead.id,
            sequence_step=2,
            subject="Test Subject 2",
            body_text="Follow up",
            body_html="<p>Follow up</p>",
            tracking_id="stop-seq-2",
            status=EmailStatus.PENDING,
            scheduled_at=datetime.now() + timedelta(days=3),
        )
        db_session.add(pending_email)

        scheduled_email = Email(
            lead_id=lead.id,
            sequence_step=3,
            subject="Test Subject 3",
            body_text="Final follow up",
            body_html="<p>Final follow up</p>",
            tracking_id="stop-seq-3",
            status=EmailStatus.PENDING,
            scheduled_at=datetime.now() + timedelta(days=7),
        )
        db_session.add(scheduled_email)

        await db_session.commit()

        # Process reply - first match it, then process
        reply = Reply(
            message_id="<stop-reply@example.com>",
            from_email="stop-sequence@test.com",
            from_name="Test User",
            subject="Re: Test Subject 1",
            in_reply_to="<stop-seq-msg@example.com>",
            references=["<stop-seq-msg@example.com>"],
            date=datetime.now(),
            body_preview="Please stop emailing me!",
        )

        checker = ReplyChecker()
        # First match the reply to set matched_email_id
        await checker._match_reply(db_session, reply)
        # Then process it
        await checker.process_replies(db_session, [reply])

        # Refresh and check statuses
        await db_session.refresh(pending_email)
        await db_session.refresh(scheduled_email)
        await db_session.refresh(lead)

        # Pending emails should be cancelled
        assert pending_email.status == EmailStatus.CANCELLED
        assert scheduled_email.status == EmailStatus.CANCELLED

        # Lead status should be updated to REPLIED
        assert lead.status == LeadStatus.REPLIED

    @pytest.mark.asyncio
    async def test_health_check_no_config(self) -> None:
        """Test health check returns False when IMAP not configured."""
        with patch("src.services.tracking.reply_checker.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                imap_host=None,
                imap_port=993,
                imap_user=None,
                imap_password=None,
            )

            checker = ReplyChecker()
            result = await checker.health_check()

            assert result is False


# ============= TrackingService Unit Tests =============


class TestTrackingServiceUnit:
    """Unit tests for TrackingService."""

    def test_tracking_pixel_is_valid_gif(self) -> None:
        """Test that TRACKING_PIXEL is a valid GIF."""
        pixel = TrackingService.TRACKING_PIXEL

        # GIF magic number
        assert pixel[:6] == b"GIF89a"

        # Should be small (1x1 transparent)
        assert len(pixel) < 100

    @pytest.mark.asyncio
    async def test_record_open_with_invalid_tracking_id(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test recording open with non-existent tracking ID."""
        tracker = TrackingService()

        # Should not raise, just silently ignore
        await tracker.record_open(
            db=db_session,
            tracking_id="non-existent-id",
            ip_address="127.0.0.1",
            user_agent="Test",
        )

    @pytest.mark.asyncio
    async def test_record_click_with_invalid_tracking_id(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test recording click with non-existent tracking ID."""
        tracker = TrackingService()

        # Should not raise, just silently ignore
        await tracker.record_click(
            db=db_session,
            tracking_id="non-existent-id",
            url="https://example.com",
            ip_address="127.0.0.1",
            user_agent="Test",
        )

    @pytest.mark.asyncio
    async def test_stats_calculation(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Test that stats service works correctly."""
        tracker = TrackingService()
        stats = await tracker.get_overall_stats(db_session, days=30)

        # Verify stats structure and types
        assert isinstance(stats.total_sent, int)
        assert isinstance(stats.total_opens, int)
        assert isinstance(stats.unique_opens, int)
        assert isinstance(stats.total_clicks, int)
        assert isinstance(stats.unique_clicks, int)
        assert isinstance(stats.total_replies, int)
        assert isinstance(stats.total_bounces, int)

        # Verify rates are percentages
        assert 0 <= stats.open_rate <= 100
        assert 0 <= stats.click_rate <= 100
        assert 0 <= stats.reply_rate <= 100
        assert 0 <= stats.bounce_rate <= 100
