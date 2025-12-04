"""Tests for email API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.models.lead import Lead, LeadStatus, LeadClassification


class TestEmailAPIEndpoints:
    """Tests for email API endpoints."""

    @pytest.fixture
    async def sample_company(self, db_session: AsyncSession) -> Company:
        """Create a sample company."""
        company = Company(
            name="Test Company BV",
            domain="testcompany.nl",
            industry="technology",
            location="Amsterdam",
            employee_count=50,
            open_vacancies=5,
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
            status=LeadStatus.QUALIFIED,
            icp_score=75,
            classification=LeadClassification.HOT,
        )
        db_session.add(lead)
        await db_session.commit()
        await db_session.refresh(lead)
        return lead

    @pytest.fixture
    async def lead_with_emails(
        self, db_session: AsyncSession, sample_lead: Lead
    ) -> Lead:
        """Create a lead with email sequence."""
        emails = [
            Email(
                lead_id=sample_lead.id,
                sequence_step=EmailSequenceStep.INITIAL,
                scheduled_day=0,
                subject="Initial subject",
                body_text="Initial body text.",
                body_html="<p>Initial body text.</p>",
                status=EmailStatus.PENDING,
            ),
            Email(
                lead_id=sample_lead.id,
                sequence_step=EmailSequenceStep.FOLLOWUP_1,
                scheduled_day=3,
                subject="Follow-up 1 subject",
                body_text="Follow-up 1 body text.",
                body_html="<p>Follow-up 1 body text.</p>",
                status=EmailStatus.PENDING,
            ),
        ]
        for email in emails:
            db_session.add(email)
        await db_session.commit()
        return sample_lead

    @pytest.mark.asyncio
    async def test_get_templates(self, client: AsyncClient) -> None:
        """Test getting email templates."""
        response = await client.get("/api/emails/templates/list")
        assert response.status_code == 200

        data = response.json()
        assert "templates" in data
        assert len(data["templates"]) == 4
        assert "sequence_schedule" in data
        assert len(data["sequence_schedule"]) == 4
        assert "value_propositions" in data

        # Check template types
        template_types = [t["email_type"] for t in data["templates"]]
        assert "initial" in template_types
        assert "followup1" in template_types
        assert "followup2" in template_types
        assert "breakup" in template_types

    @pytest.mark.asyncio
    async def test_get_email_stats_empty(self, client: AsyncClient) -> None:
        """Test getting email statistics with no emails."""
        response = await client.get("/api/emails/stats")
        assert response.status_code == 200

        data = response.json()
        assert data["total_emails"] == 0
        assert data["leads_sequenced"] == 0

    @pytest.mark.asyncio
    async def test_get_email_stats_with_data(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test getting email statistics with emails."""
        response = await client.get("/api/emails/stats")
        assert response.status_code == 200

        data = response.json()
        assert data["total_emails"] == 2
        assert "by_status" in data
        assert data["by_status"]["PENDING"] == 2

    @pytest.mark.asyncio
    async def test_get_lead_emails(
        self, client: AsyncClient, lead_with_emails: Lead
    ) -> None:
        """Test getting emails for a lead."""
        response = await client.get(f"/api/emails/lead/{lead_with_emails.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["lead_id"] == lead_with_emails.id
        assert data["lead_name"] == "Jan de Vries"
        assert len(data["emails"]) == 2
        assert data["total_emails"] == 2

    @pytest.mark.asyncio
    async def test_get_lead_emails_not_found(self, client: AsyncClient) -> None:
        """Test getting emails for non-existent lead."""
        response = await client.get("/api/emails/lead/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_email_by_id(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test getting a specific email."""
        # Get email from database
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        response = await client.get(f"/api/emails/{email.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == email.id
        assert data["subject"] == email.subject

    @pytest.mark.asyncio
    async def test_get_email_not_found(self, client: AsyncClient) -> None:
        """Test getting non-existent email."""
        response = await client.get("/api/emails/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_email(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test updating an email."""
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        response = await client.put(
            f"/api/emails/{email.id}",
            json={
                "subject": "Updated subject",
                "body_text": "Updated body text.",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["subject"] == "Updated subject"
        assert data["body_text"] == "Updated body text."

    @pytest.mark.asyncio
    async def test_update_email_not_pending(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test that sent emails cannot be updated."""
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        # Mark as sent
        email.status = EmailStatus.SENT
        email.sent_at = datetime.now()
        db_session.add(email)
        await db_session.commit()

        response = await client.put(
            f"/api/emails/{email.id}",
            json={"subject": "New subject"},
        )
        assert response.status_code == 400
        assert "PENDING" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_email(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test deleting a pending email."""
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()
        email_id = email.id

        response = await client.delete(f"/api/emails/{email_id}")
        assert response.status_code == 200

        # Verify deleted
        response = await client.get(f"/api/emails/{email_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_email_not_pending(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test that sent emails cannot be deleted."""
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        # Mark as sent
        email.status = EmailStatus.SENT
        email.sent_at = datetime.now()
        db_session.add(email)
        await db_session.commit()

        response = await client.delete(f"/api/emails/{email.id}")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_pending_emails(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test getting pending emails (leads without sequences)."""
        response = await client.get("/api/emails/pending")
        assert response.status_code == 200

        data = response.json()
        assert "leads" in data
        assert "count" in data
        # The sample_lead has score 75 and status SCORED, should be included
        assert data["count"] >= 1

    @pytest.mark.asyncio
    async def test_generate_sequence_lead_not_found(
        self, client: AsyncClient
    ) -> None:
        """Test generating sequence for non-existent lead."""
        response = await client.post(
            "/api/emails/generate/99999",
            json={},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_generate_sequence_lead_already_has_emails(
        self, client: AsyncClient, lead_with_emails: Lead
    ) -> None:
        """Test generating sequence when lead already has emails."""
        response = await client.post(
            f"/api/emails/generate/{lead_with_emails.id}",
            json={},
        )
        assert response.status_code == 400
        assert "already has" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("src.api.routes.emails.EmailGenerator")
    async def test_generate_sequence_success(
        self,
        mock_generator_class: MagicMock,
        client: AsyncClient,
        sample_lead: Lead,
        sample_company: Company,
    ) -> None:
        """Test successful sequence generation."""
        from src.services.email.generator import GeneratedEmail, EmailSequence
        from src.services.llm.openai_service import GenerationResult

        # Setup mock
        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator

        result = GenerationResult(
            text="{}",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4o-mini",
            finish_reason="stop",
            success=True,
        )

        mock_sequence = EmailSequence(
            lead_id=sample_lead.id,
            emails=[
                GeneratedEmail(
                    subject="Test subject",
                    body="Test body",
                    preview_text="Preview",
                    email_type="initial",
                    sequence_step=1,
                    word_count=2,
                    generation_result=result,
                    scheduled_for=datetime.now(),
                )
            ],
            total_tokens=150,
            estimated_cost=0.001,
            success=True,
            errors=[],
        )
        mock_generator.generate_and_save_sequence = AsyncMock(return_value=mock_sequence)

        response = await client.post(
            f"/api/emails/generate/{sample_lead.id}",
            json={"additional_context": "Extra context"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["lead_id"] == sample_lead.id
        assert data["success"] is True
        assert len(data["emails"]) == 1

    @pytest.mark.asyncio
    @patch("src.api.routes.emails.EmailGenerator")
    async def test_regenerate_email(
        self,
        mock_generator_class: MagicMock,
        client: AsyncClient,
        lead_with_emails: Lead,
        db_session: AsyncSession,
    ) -> None:
        """Test regenerating an email."""
        from sqlalchemy import select
        from src.models.email import Email
        from src.services.email.generator import GeneratedEmail
        from src.services.llm.openai_service import GenerationResult

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        # Setup mock
        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator

        gen_result = GenerationResult(
            text="{}",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4o-mini",
            finish_reason="stop",
            success=True,
        )

        mock_generated = GeneratedEmail(
            subject="Regenerated subject",
            body="Regenerated body",
            preview_text="New preview",
            email_type="initial",
            sequence_step=1,
            word_count=2,
            generation_result=gen_result,
        )
        mock_generator.regenerate_email = AsyncMock(return_value=mock_generated)

        response = await client.post(f"/api/emails/{email.id}/regenerate")
        assert response.status_code == 200

        data = response.json()
        assert data["subject"] == "Regenerated subject"

    @pytest.mark.asyncio
    async def test_regenerate_email_not_pending(
        self, client: AsyncClient, lead_with_emails: Lead, db_session: AsyncSession
    ) -> None:
        """Test that sent emails cannot be regenerated."""
        from sqlalchemy import select
        from src.models.email import Email

        stmt = select(Email).where(Email.lead_id == lead_with_emails.id).limit(1)
        result = await db_session.execute(stmt)
        email = result.scalar_one()

        # Mark as sent
        email.status = EmailStatus.SENT
        email.sent_at = datetime.now()
        db_session.add(email)
        await db_session.commit()

        response = await client.post(f"/api/emails/{email.id}/regenerate")
        assert response.status_code == 400
        assert "PENDING" in response.json()["detail"]


class TestEmailSequenceSchedule:
    """Tests for email sequence scheduling."""

    @pytest.mark.asyncio
    async def test_sequence_schedule_days(self, client: AsyncClient) -> None:
        """Test that sequence schedule has correct day offsets."""
        response = await client.get("/api/emails/templates/list")
        assert response.status_code == 200

        data = response.json()
        schedule = data["sequence_schedule"]

        # Check expected schedule
        assert schedule[0]["email_type"] == "initial"
        assert schedule[0]["days_after_start"] == 0

        assert schedule[1]["email_type"] == "followup1"
        assert schedule[1]["days_after_start"] == 3

        assert schedule[2]["email_type"] == "followup2"
        assert schedule[2]["days_after_start"] == 7

        assert schedule[3]["email_type"] == "breakup"
        assert schedule[3]["days_after_start"] == 14


class TestEmailTemplateConfiguration:
    """Tests for email template configuration."""

    @pytest.mark.asyncio
    async def test_template_word_limits(self, client: AsyncClient) -> None:
        """Test that templates have appropriate word limits."""
        response = await client.get("/api/emails/templates/list")
        assert response.status_code == 200

        data = response.json()
        templates = {t["email_type"]: t for t in data["templates"]}

        # Check word limits
        assert templates["initial"]["max_words"] == 100
        assert templates["followup1"]["max_words"] == 80
        assert templates["followup2"]["max_words"] == 70
        assert templates["breakup"]["max_words"] == 60

    @pytest.mark.asyncio
    async def test_templates_are_dutch(self, client: AsyncClient) -> None:
        """Test that templates are configured for Dutch."""
        response = await client.get("/api/emails/templates/list")
        assert response.status_code == 200

        data = response.json()
        for template in data["templates"]:
            assert template["language"] == "dutch"

    @pytest.mark.asyncio
    async def test_value_propositions_available(self, client: AsyncClient) -> None:
        """Test that value propositions are available."""
        response = await client.get("/api/emails/templates/list")
        assert response.status_code == 200

        data = response.json()
        props = data["value_propositions"]

        assert "saas" in props
        assert "technology" in props
        assert "recruitment" in props
        assert "marketing" in props
        assert "default" in props
