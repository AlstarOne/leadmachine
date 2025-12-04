"""Tests for enrichment orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company, CompanySource, CompanyStatus
from src.models.lead import Lead, LeadStatus
from src.services.enrichment.enricher import (
    EnrichmentOrchestrator,
    EnrichmentResult,
    LeadEnrichmentResult,
)
from src.services.enrichment.website import Person, ContactInfo


@pytest.fixture
async def company_for_enrichment(db_session: AsyncSession) -> Company:
    """Create a company for enrichment testing."""
    company = Company(
        name="Test Enrichment BV",
        domain="testenrichment.nl",
        website_url="https://testenrichment.nl",
        source=CompanySource.MANUAL,
        status=CompanyStatus.NEW,
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company


@pytest.fixture
async def lead_for_enrichment(
    db_session: AsyncSession, company_for_enrichment: Company
) -> Lead:
    """Create a lead for enrichment testing."""
    lead = Lead(
        company_id=company_for_enrichment.id,
        first_name="Test",
        last_name="Person",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


class TestEnrichmentOrchestrator:
    """Tests for EnrichmentOrchestrator."""

    @pytest.mark.asyncio
    async def test_enrich_company_no_domain(
        self, db_session: AsyncSession
    ) -> None:
        """Test enriching company without domain fails gracefully."""
        company = Company(
            name="No Domain Inc",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()

        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock domain service to not find domain
        orchestrator.domain_service = MagicMock()
        orchestrator.domain_service.extract_from_url.return_value = None
        orchestrator.domain_service.guess_company_domain.return_value = []

        result = await orchestrator.enrich_company(company)
        await orchestrator.close()

        assert result.success is False
        assert "Could not find or verify domain" in result.errors

        # Verify company status updated
        await db_session.refresh(company)
        assert company.status == CompanyStatus.NO_CONTACT

    @pytest.mark.asyncio
    async def test_enrich_company_with_team_members(
        self, db_session: AsyncSession, company_for_enrichment: Company
    ) -> None:
        """Test enriching company finds team members."""
        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock services
        orchestrator.domain_service = MagicMock()
        orchestrator.domain_service.get_domain_info = AsyncMock(
            return_value=MagicMock(
                has_mx=True,
                has_website=True,
                redirects_to=None,
            )
        )

        # Mock website scraper to return team members
        mock_person = Person(
            first_name="Jan",
            last_name="Janssen",
            full_name="Jan Janssen",
            job_title="CEO",
            email="jan@testenrichment.nl",
        )
        orchestrator.website_scraper = MagicMock()
        orchestrator.website_scraper.find_team_members = AsyncMock(
            return_value=[mock_person]
        )
        orchestrator.website_scraper.find_contact_info = AsyncMock(
            return_value=ContactInfo(emails=["info@testenrichment.nl"])
        )
        orchestrator.website_scraper.close = AsyncMock()

        # Mock email finder
        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.detect_pattern.return_value = "first"

        result = await orchestrator.enrich_company(company_for_enrichment)
        await orchestrator.close()

        assert result.success is True
        assert result.team_members_found == 1
        assert result.leads_created >= 1
        assert result.emails_found >= 1

        # Verify company status updated
        await db_session.refresh(company_for_enrichment)
        assert company_for_enrichment.status == CompanyStatus.ENRICHED

    @pytest.mark.asyncio
    async def test_enrich_company_no_team_members(
        self, db_session: AsyncSession, company_for_enrichment: Company
    ) -> None:
        """Test enriching company with no team members found."""
        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock services
        orchestrator.domain_service = MagicMock()
        orchestrator.domain_service.get_domain_info = AsyncMock(
            return_value=MagicMock(
                has_mx=True,
                has_website=True,
                redirects_to=None,
            )
        )

        orchestrator.website_scraper = MagicMock()
        orchestrator.website_scraper.find_team_members = AsyncMock(return_value=[])
        orchestrator.website_scraper.find_contact_info = AsyncMock(
            return_value=ContactInfo()
        )
        orchestrator.website_scraper.close = AsyncMock()

        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.detect_pattern.return_value = None

        result = await orchestrator.enrich_company(company_for_enrichment)
        await orchestrator.close()

        assert result.success is True
        assert result.team_members_found == 0
        assert result.leads_created == 0
        assert result.emails_found == 0

        # Company should be NO_CONTACT since no emails found
        await db_session.refresh(company_for_enrichment)
        assert company_for_enrichment.status == CompanyStatus.NO_CONTACT

    @pytest.mark.asyncio
    async def test_enrich_lead_finds_email(
        self,
        db_session: AsyncSession,
        lead_for_enrichment: Lead,
        company_for_enrichment: Company,
    ) -> None:
        """Test enriching lead finds email."""
        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock email finder
        from src.services.enrichment.email_finder import EmailFinderResult

        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.find_email = AsyncMock(
            return_value=EmailFinderResult(
                candidates=[],
                best_email="test.person@testenrichment.nl",
                best_confidence=85,
                domain_has_mx=True,
            )
        )

        result = await orchestrator.enrich_lead(lead_for_enrichment, company_for_enrichment)
        await orchestrator.close()

        assert result.success is True
        assert result.email_found is True
        assert result.email == "test.person@testenrichment.nl"
        assert result.email_confidence == 85

        # Verify lead updated
        await db_session.refresh(lead_for_enrichment)
        assert lead_for_enrichment.email == "test.person@testenrichment.nl"
        assert lead_for_enrichment.status == LeadStatus.ENRICHED

    @pytest.mark.asyncio
    async def test_enrich_lead_no_email_found(
        self,
        db_session: AsyncSession,
        lead_for_enrichment: Lead,
        company_for_enrichment: Company,
    ) -> None:
        """Test enriching lead when no email found."""
        orchestrator = EnrichmentOrchestrator(db_session)

        from src.services.enrichment.email_finder import EmailFinderResult

        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.find_email = AsyncMock(
            return_value=EmailFinderResult(
                candidates=[],
                best_email=None,
                best_confidence=0,
                domain_has_mx=True,
            )
        )

        result = await orchestrator.enrich_lead(lead_for_enrichment, company_for_enrichment)
        await orchestrator.close()

        assert result.success is True
        assert result.email_found is False

        # Lead should be NO_EMAIL status
        await db_session.refresh(lead_for_enrichment)
        assert lead_for_enrichment.status == LeadStatus.NO_EMAIL

    @pytest.mark.asyncio
    async def test_enrich_lead_no_company_domain(
        self, db_session: AsyncSession, lead_for_enrichment: Lead
    ) -> None:
        """Test enriching lead when company has no domain."""
        # Create company without domain
        company = Company(
            name="No Domain Co",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(company)
        await db_session.commit()

        lead_for_enrichment.company_id = company.id
        db_session.add(lead_for_enrichment)
        await db_session.commit()

        orchestrator = EnrichmentOrchestrator(db_session)
        result = await orchestrator.enrich_lead(lead_for_enrichment, company)
        await orchestrator.close()

        assert result.success is False
        assert "Company has no domain" in result.errors

    @pytest.mark.asyncio
    async def test_enrich_batch(
        self, db_session: AsyncSession
    ) -> None:
        """Test batch enrichment."""
        # Create multiple companies
        companies = []
        for i in range(3):
            company = Company(
                name=f"Batch Company {i}",
                domain=f"batch{i}.nl",
                source=CompanySource.MANUAL,
                status=CompanyStatus.NEW,
            )
            db_session.add(company)
            companies.append(company)
        await db_session.commit()

        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock all services for quick execution
        orchestrator.domain_service = MagicMock()
        orchestrator.domain_service.get_domain_info = AsyncMock(
            return_value=MagicMock(has_mx=True, has_website=True, redirects_to=None)
        )
        orchestrator.website_scraper = MagicMock()
        orchestrator.website_scraper.find_team_members = AsyncMock(return_value=[])
        orchestrator.website_scraper.find_contact_info = AsyncMock(
            return_value=ContactInfo()
        )
        orchestrator.website_scraper.close = AsyncMock()
        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.detect_pattern.return_value = None

        results = await orchestrator.enrich_batch(companies, max_concurrent=2)
        await orchestrator.close()

        assert len(results) == 3
        assert all(isinstance(r, EnrichmentResult) for r in results)

    @pytest.mark.asyncio
    async def test_create_or_update_lead_new(
        self, db_session: AsyncSession, company_for_enrichment: Company
    ) -> None:
        """Test creating new lead from person."""
        orchestrator = EnrichmentOrchestrator(db_session)

        # Mock email finder
        from src.services.enrichment.email_finder import EmailFinderResult

        orchestrator.email_finder = MagicMock()
        orchestrator.email_finder.find_email = AsyncMock(
            return_value=EmailFinderResult(
                candidates=[],
                best_email="new.person@testenrichment.nl",
                best_confidence=90,
                domain_has_mx=True,
            )
        )

        person = Person(
            first_name="New",
            last_name="Person",
            job_title="Developer",
        )

        result = await orchestrator._create_or_update_lead(
            company=company_for_enrichment,
            person=person,
            known_pattern=None,
        )
        await orchestrator.close()

        assert result.success is True
        assert result.lead_id > 0  # Positive ID means new lead
        assert result.email_found is True
        assert result.email == "new.person@testenrichment.nl"

    @pytest.mark.asyncio
    async def test_create_or_update_lead_existing(
        self,
        db_session: AsyncSession,
        company_for_enrichment: Company,
    ) -> None:
        """Test updating existing lead."""
        # Create existing lead with email
        existing = Lead(
            company_id=company_for_enrichment.id,
            first_name="Existing",
            last_name="Person",
            email="existing@testenrichment.nl",
            status=LeadStatus.ENRICHED,
        )
        db_session.add(existing)
        await db_session.commit()

        orchestrator = EnrichmentOrchestrator(db_session)

        person = Person(
            first_name="Existing",
            last_name="Person",
            email="existing@testenrichment.nl",
            job_title="New Title",
            linkedin_url="https://linkedin.com/in/existing",
        )

        result = await orchestrator._create_or_update_lead(
            company=company_for_enrichment,
            person=person,
            known_pattern=None,
        )
        await orchestrator.close()

        assert result.success is True
        assert result.lead_id < 0  # Negative ID means update

        # Verify lead was updated
        await db_session.refresh(existing)
        assert existing.linkedin_url == "https://linkedin.com/in/existing"


class TestEnrichmentResult:
    """Tests for EnrichmentResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = EnrichmentResult(company_id=1, success=True)
        assert result.leads_created == 0
        assert result.leads_updated == 0
        assert result.errors == []

    def test_with_values(self) -> None:
        """Test with custom values."""
        result = EnrichmentResult(
            company_id=1,
            success=True,
            leads_created=5,
            emails_found=3,
            duration_seconds=10.5,
        )
        assert result.leads_created == 5
        assert result.emails_found == 3
        assert result.duration_seconds == 10.5


class TestLeadEnrichmentResult:
    """Tests for LeadEnrichmentResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = LeadEnrichmentResult(lead_id=1, success=True)
        assert result.email_found is False
        assert result.email is None
        assert result.errors == []

    def test_with_email(self) -> None:
        """Test with email found."""
        result = LeadEnrichmentResult(
            lead_id=1,
            success=True,
            email_found=True,
            email="test@example.com",
            email_confidence=90,
        )
        assert result.email_found is True
        assert result.email == "test@example.com"
        assert result.email_confidence == 90
