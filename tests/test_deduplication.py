"""Tests for deduplication service."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company, CompanySource, CompanyStatus
from src.services.deduplication import DeduplicationService
from src.services.scrapers.base import CompanyRaw, ScraperType


class TestDeduplicationService:
    """Tests for DeduplicationService."""

    @pytest.fixture
    async def dedup_service(self, db_session: AsyncSession) -> DeduplicationService:
        """Create deduplication service with test session."""
        return DeduplicationService(db_session)

    def test_normalize_domain(self, db_session: AsyncSession) -> None:
        """Test domain normalization."""
        service = DeduplicationService(db_session)

        # Test various domain formats
        assert service._normalize_domain("www.example.com") == "example.com"
        assert service._normalize_domain("https://www.example.com") == "example.com"
        assert service._normalize_domain("http://example.com/page") == "example.com"
        assert service._normalize_domain("EXAMPLE.COM") == "example.com"
        assert service._normalize_domain("  example.com  ") == "example.com"

    def test_normalize_company_name(self, db_session: AsyncSession) -> None:
        """Test company name normalization."""
        service = DeduplicationService(db_session)

        # Test suffix removal
        assert service._normalize_company_name("Test Company B.V.") == "test company"
        assert service._normalize_company_name("Another Corp.") == "another"
        assert service._normalize_company_name("Tech Ltd") == "tech"
        assert service._normalize_company_name("Startup GmbH") == "startup"

        # Test whitespace normalization
        assert service._normalize_company_name("  Multiple   Spaces  ") == "multiple spaces"

    def test_calculate_name_similarity(self, db_session: AsyncSession) -> None:
        """Test name similarity calculation."""
        service = DeduplicationService(db_session)

        # Identical names
        assert service._calculate_name_similarity("test company", "test company") == 1.0

        # Similar names
        similarity = service._calculate_name_similarity("test company", "test companny")
        assert similarity > 0.8

        # Different names
        similarity = service._calculate_name_similarity("test company", "other business")
        assert similarity < 0.5

    def test_names_are_similar(self, db_session: AsyncSession) -> None:
        """Test name similarity threshold check."""
        service = DeduplicationService(db_session)

        # Should be similar (above 0.85 threshold)
        assert service._names_are_similar("tech company", "tech companny")

        # Should not be similar
        assert not service._names_are_similar("abc company", "xyz corporation")

    @pytest.mark.asyncio
    async def test_find_by_domain(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test finding company by domain."""
        # Create existing company
        existing = Company(
            name="Existing Company",
            domain="existing.com",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(existing)
        await db_session.commit()

        # Create raw company with same domain
        raw = CompanyRaw(
            name="Some Name",
            source=ScraperType.INDEED,
            domain="existing.com",
        )

        found = await dedup_service._find_by_domain(raw)
        assert found is not None
        assert found.id == existing.id

    @pytest.mark.asyncio
    async def test_find_by_domain_not_found(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test domain lookup returns None when not found."""
        raw = CompanyRaw(
            name="New Company",
            source=ScraperType.KVK,
            domain="newcompany.com",
        )

        found = await dedup_service._find_by_domain(raw)
        assert found is None

    @pytest.mark.asyncio
    async def test_find_or_create_new_company(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test creating a new company when no match found."""
        raw = CompanyRaw(
            name="Brand New Company",
            source=ScraperType.TECHLEAP,
            domain="brandnew.nl",
            location="Amsterdam",
            employee_count=50,
        )

        company, is_new = await dedup_service.find_or_create_company(raw)

        assert is_new is True
        assert company.id is not None
        assert company.name == "Brand New Company"
        assert company.domain == "brandnew.nl"
        assert company.employee_count == 50

    @pytest.mark.asyncio
    async def test_find_or_create_existing_company(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test finding existing company by domain."""
        # Create existing company
        existing = Company(
            name="Original Name",
            domain="company.com",
            source=CompanySource.KVK,
            status=CompanyStatus.NEW,
        )
        db_session.add(existing)
        await db_session.commit()
        existing_id = existing.id

        # Try to create company with same domain
        raw = CompanyRaw(
            name="Different Name",
            source=ScraperType.INDEED,
            domain="company.com",
            employee_count=100,  # New data to merge
        )

        company, is_new = await dedup_service.find_or_create_company(raw)

        assert is_new is False
        assert company.id == existing_id
        # Employee count should be updated
        assert company.employee_count == 100

    @pytest.mark.asyncio
    async def test_merge_company_data(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test merging new data into existing company."""
        # Create existing company with minimal data
        existing = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(existing)
        await db_session.commit()

        # New data with more information
        raw = CompanyRaw(
            name="Test Company",
            source=ScraperType.LINKEDIN,
            linkedin_url="https://linkedin.com/company/test",
            employee_count=75,
            industry="Software",
            location="Rotterdam",
            has_funding=True,
            funding_amount="€2M",
        )

        await dedup_service._merge_company_data(existing, raw)

        # Verify merged data
        assert existing.linkedin_url == "https://linkedin.com/company/test"
        assert existing.employee_count == 75
        assert existing.industry == "Software"
        assert existing.location == "Rotterdam"
        assert existing.has_funding is True
        assert existing.funding_amount == "€2M"

    @pytest.mark.asyncio
    async def test_dedupe_input_list(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test deduplicating input list before database check."""
        companies = [
            CompanyRaw(name="Company A", source=ScraperType.INDEED, domain="companya.com"),
            CompanyRaw(name="Company A", source=ScraperType.KVK, domain="companya.com"),  # Duplicate
            CompanyRaw(name="Company B", source=ScraperType.INDEED, domain="companyb.com"),
            CompanyRaw(name="Company A BV", source=ScraperType.INDEED),  # Similar name
        ]

        unique = dedup_service._dedupe_input_list(companies)

        # Should have 2-3 unique companies depending on fuzzy matching
        assert len(unique) < len(companies)
        assert len(unique) >= 2

    @pytest.mark.asyncio
    async def test_deduplicate_batch(
        self, db_session: AsyncSession, dedup_service: DeduplicationService
    ) -> None:
        """Test full deduplication of a batch of companies."""
        # Create one existing company
        existing = Company(
            name="Existing Corp",
            domain="existing.nl",
            source=CompanySource.MANUAL,
            status=CompanyStatus.NEW,
        )
        db_session.add(existing)
        await db_session.commit()

        # Batch with mix of new and existing
        companies = [
            CompanyRaw(name="Brand New", source=ScraperType.INDEED, domain="brandnew.com"),
            CompanyRaw(name="Existing Corp", source=ScraperType.KVK, domain="existing.nl"),  # Existing
            CompanyRaw(name="Another New", source=ScraperType.LINKEDIN, domain="anothernew.nl"),
        ]

        result = await dedup_service.deduplicate(companies, update_existing=True)

        assert len(result.new_companies) == 2
        assert len(result.existing_companies) == 1
        assert result.merged_count == 1
