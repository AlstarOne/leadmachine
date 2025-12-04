"""Tests for email sending API endpoints."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.models.lead import Lead, LeadStatus, LeadClassification

CET = ZoneInfo("Europe/Amsterdam")


class TestSendAPIEndpoints:
    """Tests for send API endpoints."""

    @pytest.fixture
    async def sample_company(self, db_session: AsyncSession) -> Company:
        """Create a sample company."""
        company = Company(
            name="Test Company BV",
            domain="testcompany.nl",
            industry="technology",
            location="Amsterdam",
            employee_count=50,
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
    async def test_get_queue_status(
        self, client: AsyncClient, sample_emails: list[Email]
    ) -> None:
        """Test getting queue status."""
        response = await client.get("/api/send/status")
        assert response.status_code == 200

        data = response.json()
        assert "pending_count" in data
        assert "due_count" in data
        assert "daily_limit" in data
        assert "sent_today" in data
        assert "can_send" in data
        assert data["pending_count"] == 2

    @pytest.mark.asyncio
    async def test_get_email_queue(
        self, client: AsyncClient, sample_emails: list[Email]
    ) -> None:
        """Test getting email queue."""
        response = await client.get("/api/send/queue")
        assert response.status_code == 200

        data = response.json()
        assert "emails" in data
        assert "count" in data
        assert data["count"] == 2

        # Check email structure
        email = data["emails"][0]
        assert "id" in email
        assert "subject" in email
        assert "status" in email
        assert "scheduled_at" in email

    @pytest.mark.asyncio
    async def test_get_email_queue_with_filter(
        self, client: AsyncClient, sample_emails: list[Email]
    ) -> None:
        """Test getting email queue with status filter."""
        response = await client.get("/api/send/queue?status_filter=PENDING")
        assert response.status_code == 200

        data = response.json()
        assert data["status_filter"] == "PENDING"
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_get_email_queue_invalid_filter(
        self, client: AsyncClient
    ) -> None:
        """Test getting email queue with invalid status."""
        response = await client.get("/api/send/queue?status_filter=INVALID")
        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_rate_limit_status(
        self, client: AsyncClient
    ) -> None:
        """Test getting rate limit status."""
        response = await client.get("/api/send/rate-limit")
        assert response.status_code == 200

        data = response.json()
        assert "emails_sent_today" in data
        assert "daily_limit" in data
        assert "remaining_today" in data
        assert "can_send" in data
        assert "reset_at" in data

    @pytest.mark.asyncio
    async def test_check_business_hours(
        self, client: AsyncClient
    ) -> None:
        """Test checking business hours."""
        response = await client.get("/api/send/business-hours")
        assert response.status_code == 200

        data = response.json()
        assert "is_business_hours" in data
        assert "current_time" in data
        assert "business_start" in data
        assert "business_end" in data
        assert "business_days" in data

        # Check business days are weekdays
        assert "Monday" in data["business_days"]
        assert "Friday" in data["business_days"]
        assert "Saturday" not in data["business_days"]

    @pytest.mark.asyncio
    async def test_get_send_config(
        self, client: AsyncClient
    ) -> None:
        """Test getting send configuration."""
        response = await client.get("/api/send/config")
        assert response.status_code == 200

        data = response.json()
        assert "daily_limit" in data
        assert "min_delay_seconds" in data
        assert "max_delay_seconds" in data
        assert "business_hours" in data
        assert "timezone" in data

    @pytest.mark.asyncio
    async def test_get_send_stats(
        self, client: AsyncClient, sample_emails: list[Email]
    ) -> None:
        """Test getting send statistics."""
        response = await client.get("/api/send/stats")
        assert response.status_code == 200

        data = response.json()
        assert "by_status" in data
        assert "today" in data
        assert "queue" in data

        # Check status breakdown
        assert "PENDING" in data["by_status"]
        assert data["by_status"]["PENDING"] == 2

    @pytest.mark.asyncio
    @patch("src.api.routes.send.start_send_queue")
    async def test_start_sending(
        self, mock_task: MagicMock, client: AsyncClient
    ) -> None:
        """Test starting the send queue."""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        response = await client.post("/api/send/start")
        assert response.status_code == 200

        data = response.json()
        assert data["job_id"] == "test-task-id"
        assert data["status"] in ["started", "scheduled"]

    @pytest.mark.asyncio
    async def test_pause_sending(
        self, client: AsyncClient
    ) -> None:
        """Test pausing the send queue."""
        response = await client.post("/api/send/pause")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_pause_sequence(
        self, client: AsyncClient, sample_lead: Lead, sample_emails: list[Email]
    ) -> None:
        """Test pausing a lead's sequence."""
        response = await client.post(f"/api/send/pause/{sample_lead.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["lead_id"] == sample_lead.id
        assert data["emails_paused"] == 2

    @pytest.mark.asyncio
    async def test_pause_sequence_lead_not_found(
        self, client: AsyncClient
    ) -> None:
        """Test pausing sequence for non-existent lead."""
        response = await client.post("/api/send/pause/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_sequence(
        self, client: AsyncClient, sample_lead: Lead, sample_emails: list[Email], db_session: AsyncSession
    ) -> None:
        """Test resuming a paused sequence."""
        # First pause
        await client.post(f"/api/send/pause/{sample_lead.id}")

        # Then resume
        response = await client.post(f"/api/send/resume/{sample_lead.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["lead_id"] == sample_lead.id
        assert data["emails_resumed"] == 2

    @pytest.mark.asyncio
    async def test_resume_sequence_lead_not_found(
        self, client: AsyncClient
    ) -> None:
        """Test resuming sequence for non-existent lead."""
        response = await client.post("/api/send/resume/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("src.api.routes.send.schedule_lead_sequence")
    async def test_schedule_sequence(
        self, mock_task: MagicMock, client: AsyncClient, sample_lead: Lead, sample_emails: list[Email]
    ) -> None:
        """Test scheduling a lead's sequence."""
        mock_task.delay.return_value = MagicMock(id="schedule-task-id")

        response = await client.post(f"/api/send/schedule/{sample_lead.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["job_id"] == "schedule-task-id"
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_schedule_sequence_lead_not_found(
        self, client: AsyncClient
    ) -> None:
        """Test scheduling for non-existent lead."""
        response = await client.post("/api/send/schedule/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_schedule_sequence_no_emails(
        self, client: AsyncClient, sample_lead: Lead, db_session: AsyncSession
    ) -> None:
        """Test scheduling when lead has no pending emails."""
        # Lead exists but has no emails
        response = await client.post(f"/api/send/schedule/{sample_lead.id}")
        assert response.status_code == 400
        assert "no pending emails" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("src.api.routes.send.send_batch_task")
    async def test_send_batch(
        self, mock_task: MagicMock, client: AsyncClient
    ) -> None:
        """Test starting batch send."""
        mock_task.delay.return_value = MagicMock(id="batch-task-id")

        response = await client.post("/api/send/batch", json={"limit": 10})
        assert response.status_code == 200

        data = response.json()
        assert data["job_id"] == "batch-task-id"
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_update_config(
        self, client: AsyncClient
    ) -> None:
        """Test updating send configuration."""
        response = await client.put(
            "/api/send/config",
            json={
                "daily_limit": 100,
                "min_delay_seconds": 60,
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert "daily_limit=100" in str(data["changes"])


class TestSendSingleEmail:
    """Tests for sending single emails."""

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
    async def pending_email(
        self, db_session: AsyncSession, sample_lead: Lead
    ) -> Email:
        """Create a pending email."""
        email = Email(
            lead_id=sample_lead.id,
            sequence_step=EmailSequenceStep.INITIAL,
            scheduled_day=0,
            subject="Test email",
            body_text="Hello",
            body_html="<p>Hello</p>",
            status=EmailStatus.PENDING,
        )
        db_session.add(email)
        await db_session.commit()
        await db_session.refresh(email)
        return email

    @pytest.mark.asyncio
    async def test_send_email_not_found(
        self, client: AsyncClient
    ) -> None:
        """Test sending non-existent email."""
        response = await client.post("/api/send/email/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_email_not_pending(
        self, client: AsyncClient, pending_email: Email, db_session: AsyncSession
    ) -> None:
        """Test sending email that's not pending."""
        # Mark as sent
        pending_email.status = EmailStatus.SENT
        pending_email.sent_at = datetime.now()
        db_session.add(pending_email)
        await db_session.commit()

        response = await client.post(f"/api/send/email/{pending_email.id}")
        assert response.status_code == 400
        assert "PENDING" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("src.api.routes.send.EmailSender")
    async def test_send_email_success(
        self, mock_sender_class: MagicMock, client: AsyncClient, pending_email: Email
    ) -> None:
        """Test successful email send."""
        from src.services.email.sender import EmailSendResult

        mock_sender = MagicMock()
        mock_sender_class.return_value = mock_sender

        mock_result = EmailSendResult(
            email_id=pending_email.id,
            success=True,
            message_id="<test@example.com>",
            tracking_id=pending_email.tracking_id,
        )
        mock_sender.send_email = AsyncMock(return_value=mock_result)

        response = await client.post(f"/api/send/email/{pending_email.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["email_id"] == pending_email.id
        assert data["message_id"] == "<test@example.com>"
