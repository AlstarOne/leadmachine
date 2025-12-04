"""Tests for scoring API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch, MagicMock

from src.models.company import Company, CompanySource, CompanyStatus
from src.models.lead import Lead, LeadClassification, LeadStatus


@pytest.fixture
async def sample_company_for_scoring(db_session: AsyncSession) -> Company:
    """Create a sample company with scoring-relevant data."""
    company = Company(
        name="Tech Startup BV",
        domain="techstartup.nl",
        website_url="https://techstartup.nl",
        industry="SaaS",
        employee_count=30,
        open_vacancies=5,
        has_funding=True,
        location="Amsterdam, Netherlands",
        source=CompanySource.MANUAL,
        status=CompanyStatus.ENRICHED,
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company


@pytest.fixture
async def sample_lead_for_scoring(
    db_session: AsyncSession, sample_company_for_scoring: Company
) -> Lead:
    """Create a sample lead for scoring tests."""
    lead = Lead(
        company_id=sample_company_for_scoring.id,
        first_name="Jan",
        last_name="Jansen",
        email="jan@techstartup.nl",
        job_title="CEO",
        linkedin_url="https://linkedin.com/in/janjansen",
        linkedin_posts_30d=5,
        status=LeadStatus.ENRICHED,
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


@pytest.fixture
async def scored_lead(
    db_session: AsyncSession, sample_company_for_scoring: Company
) -> Lead:
    """Create a pre-scored lead."""
    lead = Lead(
        company_id=sample_company_for_scoring.id,
        first_name="Pieter",
        last_name="Peters",
        email="pieter@techstartup.nl",
        job_title="CTO",
        status=LeadStatus.QUALIFIED,
        icp_score=85,
        classification=LeadClassification.HOT,
        score_breakdown={
            "company_size": {"score": 30, "reason": "30 employees (ideal size)"},
            "industry": {"score": 25, "reason": "Target industry: SaaS"},
            "growth": {"score": 12, "reason": "5 open vacancies; Has funding"},
            "activity": {"score": 8, "reason": "Has LinkedIn profile; 5 LinkedIn posts (30d)"},
            "location": {"score": 10, "reason": "Randstad location: Amsterdam"},
            "total": 85,
        },
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


class TestScoringAPI:
    """Tests for scoring endpoints."""

    @pytest.mark.asyncio
    async def test_calculate_score_endpoint(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test calculating score for a lead."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == sample_lead_for_scoring.id
        assert "score" in data
        assert "classification" in data
        assert "qualified" in data
        assert "breakdown" in data
        assert data["score"] > 0  # Should have a positive score

    @pytest.mark.asyncio
    async def test_calculate_score_by_id(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test calculating score via path parameter."""
        response = await client.post(
            f"/api/score/calculate/{sample_lead_for_scoring.id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == sample_lead_for_scoring.id
        assert data["score"] > 0

    @pytest.mark.asyncio
    async def test_calculate_score_not_found(self, client: AsyncClient) -> None:
        """Test scoring non-existent lead."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": 99999},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_calculate_score_ideal_company(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test scoring with ideal company characteristics."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200
        data = response.json()

        # Company has: SaaS industry, 30 employees, Amsterdam location
        # Lead has: LinkedIn profile, 5 posts
        # Should get a high score
        assert data["score"] >= 60  # Should be qualified
        assert data["qualified"] is True
        assert data["classification"] in ["HOT", "WARM"]

    @pytest.mark.asyncio
    async def test_score_batch_endpoint(self, client: AsyncClient) -> None:
        """Test starting batch scoring job."""
        with patch("src.workers.score_tasks.score_batch_task.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "batch-score-task-123"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/score/batch",
                json={"limit": 50},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "batch-score-task-123"
            assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_score_batch_with_lead_ids(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test batch scoring with specific lead IDs."""
        with patch("src.workers.score_tasks.score_batch_task.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "batch-score-task-456"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/score/batch",
                json={"lead_ids": [sample_lead_for_scoring.id], "limit": 10},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_get_scoring_stats(
        self, client: AsyncClient, scored_lead: Lead
    ) -> None:
        """Test getting scoring statistics."""
        response = await client.get("/api/score/stats")

        assert response.status_code == 200
        data = response.json()
        assert "total_leads" in data
        assert "scored_leads" in data
        assert "unscored_leads" in data
        assert "by_classification" in data
        assert "qualified_count" in data

    @pytest.mark.asyncio
    async def test_get_qualified_leads(
        self, client: AsyncClient, scored_lead: Lead
    ) -> None:
        """Test getting qualified leads."""
        response = await client.get("/api/score/qualified?min_score=60")

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data
        assert "total" in data
        assert "min_score" in data
        assert data["min_score"] == 60

    @pytest.mark.asyncio
    async def test_get_qualified_leads_custom_score(
        self, client: AsyncClient, scored_lead: Lead
    ) -> None:
        """Test getting qualified leads with custom min score."""
        response = await client.get("/api/score/qualified?min_score=80")

        assert response.status_code == 200
        data = response.json()
        # scored_lead has score 85, should be included
        assert any(lead["icp_score"] >= 80 for lead in data["leads"])

    @pytest.mark.asyncio
    async def test_get_unscored_leads(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test getting unscored leads."""
        response = await client.get("/api/score/unscored?limit=50")

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_get_scoring_config(self, client: AsyncClient) -> None:
        """Test getting scoring configuration."""
        response = await client.get("/api/score/config")

        assert response.status_code == 200
        data = response.json()
        assert "weights" in data
        assert "thresholds" in data
        assert data["weights"]["company_size"] == 30
        assert data["weights"]["industry"] == 25
        assert data["weights"]["growth"] == 20
        assert data["weights"]["activity"] == 15
        assert data["weights"]["location"] == 10

    @pytest.mark.asyncio
    async def test_update_scoring_config(self, client: AsyncClient) -> None:
        """Test updating scoring configuration."""
        response = await client.put(
            "/api/score/config",
            json={
                "weights": {"company_size": 35},
                "thresholds": {"hot": 80},
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Note: In-memory config update, may not persist across requests
        assert "weights" in data
        assert "thresholds" in data

    @pytest.mark.asyncio
    async def test_get_lead_score_scored(
        self, client: AsyncClient, scored_lead: Lead
    ) -> None:
        """Test getting score for a scored lead."""
        response = await client.get(f"/api/score/lead/{scored_lead.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == scored_lead.id
        assert data["scored"] is True
        assert data["score"] == 85
        assert data["classification"] == "HOT"
        assert "breakdown" in data

    @pytest.mark.asyncio
    async def test_get_lead_score_unscored(
        self, client: AsyncClient, sample_lead_for_scoring: Lead
    ) -> None:
        """Test getting score for an unscored lead."""
        response = await client.get(f"/api/score/lead/{sample_lead_for_scoring.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == sample_lead_for_scoring.id
        assert data["scored"] is False
        assert "message" in data

    @pytest.mark.asyncio
    async def test_get_lead_score_not_found(self, client: AsyncClient) -> None:
        """Test getting score for non-existent lead."""
        response = await client.get("/api/score/lead/99999")

        assert response.status_code == 404


class TestScoringIntegration:
    """Integration tests for scoring workflow."""

    @pytest.mark.asyncio
    async def test_score_updates_lead_status(
        self, client: AsyncClient, sample_lead_for_scoring: Lead, db_session: AsyncSession
    ) -> None:
        """Test that scoring updates lead status correctly."""
        # Score the lead
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200
        data = response.json()

        # Refresh lead from database
        await db_session.refresh(sample_lead_for_scoring)

        # Check status was updated based on qualification
        if data["qualified"]:
            assert sample_lead_for_scoring.status == LeadStatus.QUALIFIED
        else:
            assert sample_lead_for_scoring.status == LeadStatus.DISQUALIFIED

    @pytest.mark.asyncio
    async def test_score_saves_breakdown(
        self, client: AsyncClient, sample_lead_for_scoring: Lead, db_session: AsyncSession
    ) -> None:
        """Test that scoring saves breakdown to database."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200

        # Refresh lead from database
        await db_session.refresh(sample_lead_for_scoring)

        # Check breakdown was saved
        assert sample_lead_for_scoring.icp_score is not None
        assert sample_lead_for_scoring.score_breakdown is not None
        assert "company_size" in sample_lead_for_scoring.score_breakdown
        assert "industry" in sample_lead_for_scoring.score_breakdown

    @pytest.mark.asyncio
    async def test_score_sets_classification(
        self, client: AsyncClient, sample_lead_for_scoring: Lead, db_session: AsyncSession
    ) -> None:
        """Test that scoring sets classification correctly."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200
        data = response.json()

        # Refresh lead from database
        await db_session.refresh(sample_lead_for_scoring)

        # Check classification matches response
        assert sample_lead_for_scoring.classification.value == data["classification"]

    @pytest.mark.asyncio
    async def test_score_sets_scored_at(
        self, client: AsyncClient, sample_lead_for_scoring: Lead, db_session: AsyncSession
    ) -> None:
        """Test that scoring sets scored_at timestamp."""
        response = await client.post(
            "/api/score/calculate",
            json={"lead_id": sample_lead_for_scoring.id},
        )

        assert response.status_code == 200

        # Refresh lead from database
        await db_session.refresh(sample_lead_for_scoring)

        # Check scored_at was set
        assert sample_lead_for_scoring.scored_at is not None
