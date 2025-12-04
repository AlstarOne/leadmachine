"""Tests for enrichment API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch, MagicMock

from src.models.company import Company, CompanySource, CompanyStatus
from src.models.lead import Lead, LeadStatus


@pytest.fixture
async def sample_company(db_session: AsyncSession) -> Company:
    """Create a sample company for testing."""
    company = Company(
        name="Test Company BV",
        domain="testcompany.nl",
        website_url="https://testcompany.nl",
        source=CompanySource.MANUAL,
        status=CompanyStatus.NEW,
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company


@pytest.fixture
async def enriched_company(db_session: AsyncSession) -> Company:
    """Create an enriched company."""
    company = Company(
        name="Enriched Corp",
        domain="enriched.nl",
        website_url="https://enriched.nl",
        source=CompanySource.INDEED,
        status=CompanyStatus.ENRICHED,
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company


@pytest.fixture
async def sample_lead(db_session: AsyncSession, sample_company: Company) -> Lead:
    """Create a sample lead for testing."""
    lead = Lead(
        company_id=sample_company.id,
        first_name="Jan",
        last_name="Jansen",
        job_title="CEO",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


class TestEnrichmentAPI:
    """Tests for enrichment endpoints."""

    @pytest.mark.asyncio
    async def test_enrich_company_endpoint(
        self, client: AsyncClient, sample_company: Company
    ) -> None:
        """Test starting company enrichment."""
        with patch("src.workers.enrich_tasks.enrich_company_task.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "test-task-id-123"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/enrich/company",
                json={"company_id": sample_company.id},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-task-id-123"
            assert data["status"] == "started"
            mock_delay.assert_called_once_with(sample_company.id)

    @pytest.mark.asyncio
    async def test_enrich_company_not_found(self, client: AsyncClient) -> None:
        """Test enrichment of non-existent company."""
        with patch("src.workers.enrich_tasks.enrich_company_task.delay"):
            response = await client.post(
                "/api/enrich/company",
                json={"company_id": 99999},
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_enrich_lead_endpoint(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test starting lead enrichment."""
        with patch("src.workers.enrich_tasks.enrich_lead_task.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "lead-task-id-456"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/enrich/lead",
                json={"lead_id": sample_lead.id},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "lead-task-id-456"
            assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_enrich_lead_not_found(self, client: AsyncClient) -> None:
        """Test enrichment of non-existent lead."""
        with patch("src.workers.enrich_tasks.enrich_lead_task.delay"):
            response = await client.post(
                "/api/enrich/lead",
                json={"lead_id": 99999},
            )

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_enrich_batch_endpoint(self, client: AsyncClient) -> None:
        """Test batch enrichment."""
        with patch("src.workers.enrich_tasks.run_enrichment_batch.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "batch-task-id"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/enrich/batch",
                json={"limit": 25},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            mock_delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_batch_with_company_ids(
        self, client: AsyncClient, sample_company: Company
    ) -> None:
        """Test batch enrichment with specific company IDs."""
        with patch("src.workers.enrich_tasks.run_enrichment_batch.delay") as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "batch-task-id"
            mock_delay.return_value = mock_task

            response = await client.post(
                "/api/enrich/batch",
                json={"company_ids": [sample_company.id], "limit": 10},
            )

            assert response.status_code == 200
            mock_delay.assert_called_once_with(
                company_ids=[sample_company.id],
                status_filter=None,
                limit=10,
            )

    @pytest.mark.asyncio
    async def test_enrich_leads_without_email(self, client: AsyncClient) -> None:
        """Test enriching leads without email."""
        with patch(
            "src.workers.enrich_tasks.enrich_leads_without_email.delay"
        ) as mock_delay:
            mock_task = MagicMock()
            mock_task.id = "email-task-id"
            mock_delay.return_value = mock_task

            response = await client.post("/api/enrich/leads-without-email?limit=30")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            mock_delay.assert_called_once_with(limit=30)

    @pytest.mark.asyncio
    async def test_get_enrichment_job_status(self, client: AsyncClient) -> None:
        """Test getting enrichment job status."""
        with patch("src.api.routes.enrich.AsyncResult") as mock_result_class:
            mock_result = MagicMock()
            mock_result.status = "SUCCESS"
            mock_result.ready.return_value = True
            mock_result.successful.return_value = True
            mock_result.result = {"success": True, "leads_created": 5}
            mock_result_class.return_value = mock_result

            response = await client.get("/api/enrich/jobs/test-job-id")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-id"
            assert data["status"] == "SUCCESS"
            assert data["ready"] is True
            assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_enrichment_job_pending(self, client: AsyncClient) -> None:
        """Test getting pending job status."""
        with patch("src.api.routes.enrich.AsyncResult") as mock_result_class:
            mock_result = MagicMock()
            mock_result.status = "PENDING"
            mock_result.ready.return_value = False
            mock_result_class.return_value = mock_result

            response = await client.get("/api/enrich/jobs/pending-job-id")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "PENDING"
            assert data["ready"] is False
            assert "result" not in data

    @pytest.mark.asyncio
    async def test_get_enrichment_stats(
        self,
        client: AsyncClient,
        sample_company: Company,
        enriched_company: Company,
        sample_lead: Lead,
    ) -> None:
        """Test getting enrichment statistics."""
        response = await client.get("/api/enrich/stats")

        assert response.status_code == 200
        data = response.json()
        assert "total_companies" in data
        assert data["total_companies"] >= 2
        assert "enriched_companies" in data
        assert "total_leads" in data

    @pytest.mark.asyncio
    async def test_get_ready_to_enrich(
        self, client: AsyncClient, sample_company: Company
    ) -> None:
        """Test getting companies ready for enrichment."""
        response = await client.get("/api/enrich/ready-to-enrich?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert "companies" in data
        assert "total" in data
        # sample_company has status NEW and domain
        assert data["total"] >= 1


class TestLeadsAPI:
    """Tests for leads endpoints."""

    @pytest.mark.asyncio
    async def test_list_leads(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test listing leads."""
        response = await client.get("/api/leads")

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data
        assert "total" in data
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_leads_with_filters(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test listing leads with filters."""
        response = await client.get(
            "/api/leads",
            params={"status_filter": "NEW", "has_email": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data

    @pytest.mark.asyncio
    async def test_list_leads_by_company(
        self, client: AsyncClient, sample_lead: Lead, sample_company: Company
    ) -> None:
        """Test listing leads filtered by company."""
        response = await client.get(
            "/api/leads", params={"company_id": sample_company.id}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_lead_stats(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test getting lead statistics."""
        response = await client.get("/api/leads/stats")

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "by_status" in data
        assert "by_classification" in data
        assert "with_email" in data

    @pytest.mark.asyncio
    async def test_get_single_lead(
        self, client: AsyncClient, sample_lead: Lead, sample_company: Company
    ) -> None:
        """Test getting a single lead."""
        response = await client.get(f"/api/leads/{sample_lead.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_lead.id
        assert data["first_name"] == "Jan"
        assert data["last_name"] == "Jansen"
        assert data["company_name"] == sample_company.name

    @pytest.mark.asyncio
    async def test_get_lead_not_found(self, client: AsyncClient) -> None:
        """Test getting non-existent lead."""
        response = await client.get("/api/leads/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_lead(
        self, client: AsyncClient, sample_company: Company
    ) -> None:
        """Test creating a new lead."""
        response = await client.post(
            "/api/leads",
            json={
                "company_id": sample_company.id,
                "first_name": "Pieter",
                "last_name": "Peters",
                "email": "pieter@testcompany.nl",
                "job_title": "CTO",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["first_name"] == "Pieter"
        assert data["email"] == "pieter@testcompany.nl"
        assert data["company_id"] == sample_company.id

    @pytest.mark.asyncio
    async def test_create_lead_duplicate_email(
        self, client: AsyncClient, sample_company: Company, db_session: AsyncSession
    ) -> None:
        """Test creating lead with duplicate email fails."""
        # Create first lead with email
        lead = Lead(
            company_id=sample_company.id,
            first_name="Test",
            last_name="User",
            email="duplicate@test.nl",
        )
        db_session.add(lead)
        await db_session.commit()

        # Try to create another with same email
        response = await client.post(
            "/api/leads",
            json={
                "company_id": sample_company.id,
                "first_name": "Another",
                "last_name": "User",
                "email": "duplicate@test.nl",
            },
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_lead(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test updating a lead."""
        response = await client.patch(
            f"/api/leads/{sample_lead.id}",
            json={"job_title": "Managing Director"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["job_title"] == "Managing Director"

    @pytest.mark.asyncio
    async def test_delete_lead(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test deleting a lead."""
        response = await client.delete(f"/api/leads/{sample_lead.id}")
        assert response.status_code == 204

        # Verify deleted
        response = await client.get(f"/api/leads/{sample_lead.id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_lead_status(
        self, client: AsyncClient, sample_lead: Lead
    ) -> None:
        """Test updating lead status."""
        response = await client.post(
            f"/api/leads/{sample_lead.id}/status",
            params={"new_status": "ENRICHED"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ENRICHED"

    @pytest.mark.asyncio
    async def test_list_enriched_leads(
        self, client: AsyncClient, sample_lead: Lead, db_session: AsyncSession
    ) -> None:
        """Test listing enriched leads."""
        # Update lead to enriched
        sample_lead.status = LeadStatus.ENRICHED
        sample_lead.email = "jan@testcompany.nl"
        db_session.add(sample_lead)
        await db_session.commit()

        response = await client.get("/api/leads/enriched")

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data

    @pytest.mark.asyncio
    async def test_list_qualified_leads(
        self, client: AsyncClient, sample_lead: Lead, db_session: AsyncSession
    ) -> None:
        """Test listing qualified leads."""
        # Update lead with score
        sample_lead.icp_score = 75
        sample_lead.status = LeadStatus.QUALIFIED
        db_session.add(sample_lead)
        await db_session.commit()

        response = await client.get("/api/leads/qualified?min_score=60")

        assert response.status_code == 200
        data = response.json()
        assert "leads" in data
        assert data["min_score"] == 60
