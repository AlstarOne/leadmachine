"""Tests for scraping API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.scrape_job import ScrapeJob, ScrapeJobStatus


class TestScrapeAPI:
    """Tests for scrape API endpoints."""

    @pytest.mark.asyncio
    async def test_list_scraper_sources(self, client: AsyncClient) -> None:
        """Test listing available scraper sources."""
        response = await client.get("/api/scrape/sources")

        assert response.status_code == 200
        data = response.json()

        assert "sources" in data
        assert len(data["sources"]) > 0

        # Check that expected sources are present
        source_names = [s["name"] for s in data["sources"]]
        assert "INDEED" in source_names
        assert "KVK" in source_names
        assert "LINKEDIN" in source_names
        assert "TECHLEAP" in source_names

    @pytest.mark.asyncio
    async def test_list_scrape_jobs_empty(self, client: AsyncClient) -> None:
        """Test listing scrape jobs when empty."""
        response = await client.get("/api/scrape/jobs")

        assert response.status_code == 200
        data = response.json()

        assert "jobs" in data
        assert "total" in data
        assert "page" in data
        assert data["jobs"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_scrape_jobs_with_data(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test listing scrape jobs with existing data."""
        # Create test jobs
        job1 = ScrapeJob(
            source="INDEED",
            keywords=["python", "developer"],
            status=ScrapeJobStatus.COMPLETED,
            results_count=10,
        )
        job2 = ScrapeJob(
            source="KVK",
            keywords=["software"],
            status=ScrapeJobStatus.PENDING,
        )
        db_session.add_all([job1, job2])
        await db_session.commit()

        response = await client.get("/api/scrape/jobs")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 2
        assert len(data["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_list_scrape_jobs_filter_by_source(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test filtering scrape jobs by source."""
        # Create test jobs
        job1 = ScrapeJob(source="INDEED", keywords=["test"], status=ScrapeJobStatus.PENDING)
        job2 = ScrapeJob(source="KVK", keywords=["test"], status=ScrapeJobStatus.PENDING)
        db_session.add_all([job1, job2])
        await db_session.commit()

        response = await client.get("/api/scrape/jobs?source=INDEED")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert data["jobs"][0]["source"] == "INDEED"

    @pytest.mark.asyncio
    async def test_get_scrape_job(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test getting a specific scrape job."""
        job = ScrapeJob(
            source="TECHLEAP",
            keywords=["ai", "startup"],
            status=ScrapeJobStatus.RUNNING,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.get(f"/api/scrape/jobs/{job.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == job.id
        assert data["source"] == "TECHLEAP"
        assert data["keywords"] == ["ai", "startup"]
        assert data["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_get_scrape_job_not_found(self, client: AsyncClient) -> None:
        """Test getting a non-existent scrape job."""
        response = await client.get("/api/scrape/jobs/99999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_scrape_job(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test cancelling a pending scrape job."""
        job = ScrapeJob(
            source="LINKEDIN",
            keywords=["fintech"],
            status=ScrapeJobStatus.PENDING,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.post(f"/api/scrape/jobs/{job.id}/cancel")

        assert response.status_code == 200

        # Verify status changed
        await db_session.refresh(job)
        assert job.status == ScrapeJobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_job_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test that cancelling a completed job fails."""
        job = ScrapeJob(
            source="INDEED",
            keywords=["test"],
            status=ScrapeJobStatus.COMPLETED,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.post(f"/api/scrape/jobs/{job.id}/cancel")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_start_scrape_invalid_source(self, client: AsyncClient) -> None:
        """Test starting a scrape with invalid source."""
        response = await client.post(
            "/api/scrape/start",
            json={
                "source": "INVALID_SOURCE",
                "keywords": ["test"],
            },
        )

        assert response.status_code == 400
        assert "Invalid source" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_scrape_empty_keywords(self, client: AsyncClient) -> None:
        """Test starting a scrape with empty keywords."""
        response = await client.post(
            "/api/scrape/start",
            json={
                "source": "INDEED",
                "keywords": [],
            },
        )

        assert response.status_code == 422  # Validation error


class TestCompaniesAPI:
    """Tests for companies API endpoints."""

    @pytest.mark.asyncio
    async def test_list_companies_empty(self, client: AsyncClient) -> None:
        """Test listing companies when empty."""
        response = await client.get("/api/companies")

        assert response.status_code == 200
        data = response.json()

        assert "companies" in data
        assert "total" in data
        assert data["companies"] == []

    @pytest.mark.asyncio
    async def test_create_company(self, client: AsyncClient) -> None:
        """Test creating a new company."""
        response = await client.post(
            "/api/companies",
            json={
                "name": "Test Company BV",
                "domain": "testcompany.nl",
                "industry": "Software",
                "employee_count": 50,
                "source": "MANUAL",
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Test Company BV"
        assert data["domain"] == "testcompany.nl"
        assert data["status"] == "NEW"

    @pytest.mark.asyncio
    async def test_create_company_duplicate_domain(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test creating company with duplicate domain fails."""
        from src.models.company import Company, CompanySource, CompanyStatus

        # Create existing company
        existing = Company(
            name="Existing",
            domain="existing.nl",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(existing)
        await db_session.commit()

        response = await client.post(
            "/api/companies",
            json={
                "name": "New Company",
                "domain": "existing.nl",
                "source": "MANUAL",
            },
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_get_company(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test getting a specific company."""
        from src.models.company import Company, CompanySource, CompanyStatus

        company = Company(
            name="Test Corp",
            domain="testcorp.com",
            industry="Tech",
            source=CompanySource.INDEED,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)

        response = await client.get(f"/api/companies/{company.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Test Corp"
        assert data["domain"] == "testcorp.com"

    @pytest.mark.asyncio
    async def test_get_company_not_found(self, client: AsyncClient) -> None:
        """Test getting non-existent company."""
        response = await client.get("/api/companies/99999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_company(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test updating a company."""
        from src.models.company import Company, CompanySource, CompanyStatus

        company = Company(
            name="Original Name",
            domain="original.com",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)

        response = await client.patch(
            f"/api/companies/{company.id}",
            json={
                "employee_count": 100,
                "industry": "Fintech",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["employee_count"] == 100
        assert data["industry"] == "Fintech"

    @pytest.mark.asyncio
    async def test_delete_company(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test deleting a company."""
        from src.models.company import Company, CompanySource, CompanyStatus

        company = Company(
            name="To Delete",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)

        response = await client.delete(f"/api/companies/{company.id}")

        assert response.status_code == 204

        # Verify deleted
        deleted = await db_session.get(Company, company.id)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_get_company_stats(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test getting company statistics."""
        from src.models.company import Company, CompanySource, CompanyStatus

        # Create some companies
        companies = [
            Company(
                name="Company 1",
                domain="c1.com",
                source=CompanySource.INDEED,
                status=CompanyStatus.NEW,
            ),
            Company(
                name="Company 2",
                domain="c2.com",
                source=CompanySource.INDEED,
                status=CompanyStatus.ENRICHED,
                has_funding=True,
            ),
            Company(
                name="Company 3",
                source=CompanySource.KVK,
                status=CompanyStatus.NEW,
            ),
        ]
        db_session.add_all(companies)
        await db_session.commit()

        response = await client.get("/api/companies/stats")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 3
        assert "by_status" in data
        assert "by_source" in data
        assert data["with_domain"] == 2
        assert data["with_funding"] == 1

    @pytest.mark.asyncio
    async def test_update_company_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test updating company status."""
        from src.models.company import Company, CompanySource, CompanyStatus

        company = Company(
            name="Test Company",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)

        response = await client.post(
            f"/api/companies/{company.id}/status?new_status=ENRICHING"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ENRICHING"

    @pytest.mark.asyncio
    async def test_update_company_status_invalid_transition(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test invalid status transition."""
        from src.models.company import Company, CompanySource, CompanyStatus

        company = Company(
            name="Test Company",
            source=CompanySource.MANUAL,
            status=CompanyStatus.ARCHIVED,  # Terminal state
        )
        db_session.add(company)
        await db_session.commit()
        await db_session.refresh(company)

        response = await client.post(
            f"/api/companies/{company.id}/status?new_status=NEW"
        )

        assert response.status_code == 400
