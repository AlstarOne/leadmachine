"""Tests for enrichment services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.enrichment.domain import DomainService, DomainInfo
from src.services.enrichment.email_finder import EmailFinder, EmailCandidate
from src.services.enrichment.website import WebsiteScraper, Person, ContactInfo


class TestDomainService:
    """Tests for DomainService."""

    @pytest.fixture
    def service(self) -> DomainService:
        """Create DomainService instance."""
        return DomainService()

    def test_normalize_simple_domain(self, service: DomainService) -> None:
        """Test normalizing a simple domain."""
        assert service.normalize("example.com") == "example.com"

    def test_normalize_with_www(self, service: DomainService) -> None:
        """Test removing www prefix."""
        assert service.normalize("www.example.com") == "example.com"

    def test_normalize_https_url(self, service: DomainService) -> None:
        """Test normalizing full URL."""
        assert service.normalize("https://www.example.com/path") == "example.com"

    def test_normalize_http_url(self, service: DomainService) -> None:
        """Test normalizing HTTP URL."""
        assert service.normalize("http://example.com") == "example.com"

    def test_normalize_uppercase(self, service: DomainService) -> None:
        """Test converting to lowercase."""
        assert service.normalize("EXAMPLE.COM") == "example.com"

    def test_normalize_with_subdomain(self, service: DomainService) -> None:
        """Test preserving subdomain (not www)."""
        assert service.normalize("blog.example.com") == "blog.example.com"

    def test_normalize_trailing_dot(self, service: DomainService) -> None:
        """Test removing trailing dot."""
        assert service.normalize("example.com.") == "example.com"

    def test_normalize_invalid_domain(self, service: DomainService) -> None:
        """Test invalid domain returns None."""
        assert service.normalize("") is None
        assert service.normalize("not-a-domain") is None

    def test_is_company_domain_valid(self, service: DomainService) -> None:
        """Test valid company domains."""
        assert service.is_company_domain("techcorp.nl")
        assert service.is_company_domain("example.com")

    def test_is_company_domain_email_provider(self, service: DomainService) -> None:
        """Test email provider domains are not company domains."""
        assert not service.is_company_domain("gmail.com")
        assert not service.is_company_domain("outlook.com")
        assert not service.is_company_domain("hotmail.nl")

    def test_extract_from_email(self, service: DomainService) -> None:
        """Test extracting domain from email."""
        assert service.extract_from_email("user@example.com") == "example.com"
        assert service.extract_from_email("user@gmail.com") is None  # Email provider
        assert service.extract_from_email("invalid") is None

    def test_extract_from_url(self, service: DomainService) -> None:
        """Test extracting domain from URL."""
        assert service.extract_from_url("https://www.example.com/page") == "example.com"
        assert service.extract_from_url("http://example.nl") == "example.nl"

    def test_guess_company_domain(self, service: DomainService) -> None:
        """Test guessing company domain from name."""
        guesses = service.guess_company_domain("Tech Corp BV")
        # After removing BV suffix, "Tech Corp" becomes "techcorp" (no spaces)
        assert "techcorp.nl" in guesses
        assert "techcorp.com" in guesses
        # Should also try first word only
        assert "tech.nl" in guesses
        assert len(guesses) > 0

    def test_guess_company_domain_complex_name(self, service: DomainService) -> None:
        """Test guessing domain from complex company name."""
        guesses = service.guess_company_domain("Van der Berg & Zn.")
        assert len(guesses) > 0
        # Should include variations
        assert any("vanderberg" in g for g in guesses)

    @pytest.mark.asyncio
    async def test_check_mx_records_mock(self, service: DomainService) -> None:
        """Test MX record check with mock."""
        with patch("dns.resolver.resolve") as mock_resolve:
            mock_mx = MagicMock()
            mock_mx.exchange.to_text.return_value = "mx.example.com"
            mock_resolve.return_value = [mock_mx]

            has_mx, records = await service.check_mx_records("example.com")
            assert has_mx is True
            assert len(records) > 0

    @pytest.mark.asyncio
    async def test_check_mx_records_no_records(self, service: DomainService) -> None:
        """Test MX check when no records exist."""
        import dns.resolver
        with patch("dns.resolver.resolve", side_effect=dns.resolver.NXDOMAIN):
            has_mx, records = await service.check_mx_records("nonexistent.example.com")
            assert has_mx is False
            assert records == []


class TestEmailFinder:
    """Tests for EmailFinder."""

    @pytest.fixture
    def finder(self) -> EmailFinder:
        """Create EmailFinder instance."""
        return EmailFinder(verify_emails=False)

    def test_generate_patterns(self, finder: EmailFinder) -> None:
        """Test email pattern generation."""
        candidates = finder.generate_patterns("John", "Doe", "example.com")

        assert len(candidates) > 0
        emails = [c.email for c in candidates]

        # Check common patterns are generated
        assert "john.doe@example.com" in emails
        assert "johndoe@example.com" in emails
        assert "jdoe@example.com" in emails
        assert "john@example.com" in emails

    def test_generate_patterns_normalized(self, finder: EmailFinder) -> None:
        """Test names are normalized in patterns."""
        candidates = finder.generate_patterns("JOHN", "DOE", "example.com")

        emails = [c.email for c in candidates]
        assert "john.doe@example.com" in emails

    def test_generate_patterns_accents(self, finder: EmailFinder) -> None:
        """Test accents are removed."""
        candidates = finder.generate_patterns("José", "García", "example.com")

        emails = [c.email for c in candidates]
        assert any("jose" in e for e in emails)
        assert any("garcia" in e for e in emails)

    def test_generate_patterns_empty(self, finder: EmailFinder) -> None:
        """Test empty input returns empty list."""
        assert finder.generate_patterns("", "Doe", "example.com") == []
        assert finder.generate_patterns("John", "", "example.com") == []
        assert finder.generate_patterns("John", "Doe", "") == []

    def test_pattern_confidence(self, finder: EmailFinder) -> None:
        """Test patterns have correct confidence weights."""
        candidates = finder.generate_patterns("John", "Doe", "example.com")

        # first.last should have highest confidence
        first_last = next(c for c in candidates if c.pattern_name == "first.last")
        assert first_last.confidence == 95

        # flast should be lower
        flast = next(c for c in candidates if c.pattern_name == "flast")
        assert flast.confidence < first_last.confidence

    @pytest.mark.asyncio
    async def test_find_email_no_mx(self, finder: EmailFinder) -> None:
        """Test find_email when domain has no MX records."""
        finder.domain_service = MagicMock()
        finder.domain_service.check_mx_records = AsyncMock(return_value=(False, []))

        result = await finder.find_email("John", "Doe", "nomx.example.com")

        assert result.domain_has_mx is False
        assert result.best_email is None
        assert len(result.candidates) == 0

    @pytest.mark.asyncio
    async def test_find_email_with_known_pattern(self, finder: EmailFinder) -> None:
        """Test find_email boosts known pattern."""
        finder.domain_service = MagicMock()
        finder.domain_service.check_mx_records = AsyncMock(
            return_value=(True, ["mx.example.com"])
        )
        finder.domain_service.normalize.return_value = "example.com"

        result = await finder.find_email(
            "John", "Doe", "example.com", known_pattern="firstlast"
        )

        # firstlast pattern should be boosted
        firstlast = next(
            (c for c in result.candidates if c.pattern_name == "firstlast"), None
        )
        assert firstlast is not None
        # It should have 20 added to base confidence (85 + 20 = 105, but after sorting)
        assert result.best_email is not None

    def test_detect_pattern_first_dot_last(self, finder: EmailFinder) -> None:
        """Test detecting first.last pattern."""
        emails = ["john.doe@example.com", "jane.smith@example.com"]
        pattern = finder.detect_pattern(emails, "example.com")
        assert pattern == "first.last"

    def test_detect_pattern_firstlast(self, finder: EmailFinder) -> None:
        """Test detecting firstlast pattern."""
        emails = ["johndoe@example.com", "janesmith@example.com"]
        pattern = finder.detect_pattern(emails, "example.com")
        assert pattern == "firstlast"

    def test_detect_pattern_empty(self, finder: EmailFinder) -> None:
        """Test empty emails returns None."""
        assert finder.detect_pattern([], "example.com") is None

    def test_valid_email_format(self, finder: EmailFinder) -> None:
        """Test email format validation."""
        assert finder._is_valid_format("user@example.com")
        assert finder._is_valid_format("user.name@example.co.uk")
        assert not finder._is_valid_format("invalid")
        assert not finder._is_valid_format("@example.com")


class TestWebsiteScraper:
    """Tests for WebsiteScraper."""

    @pytest.fixture
    def scraper(self) -> WebsiteScraper:
        """Create WebsiteScraper instance."""
        return WebsiteScraper()

    def test_split_name_simple(self, scraper: WebsiteScraper) -> None:
        """Test splitting simple name."""
        first, last = scraper._split_name("John Doe")
        assert first == "John"
        assert last == "Doe"

    def test_split_name_dutch_prefix(self, scraper: WebsiteScraper) -> None:
        """Test splitting Dutch name with prefix."""
        first, last = scraper._split_name("Jan van den Berg")
        assert first == "Jan"
        assert last == "van den Berg"

    def test_split_name_single(self, scraper: WebsiteScraper) -> None:
        """Test splitting single name."""
        first, last = scraper._split_name("Madonna")
        assert first == "Madonna"
        assert last is None

    def test_split_name_empty(self, scraper: WebsiteScraper) -> None:
        """Test splitting empty name."""
        first, last = scraper._split_name("")
        assert first is None
        assert last is None

    def test_is_decision_maker(self, scraper: WebsiteScraper) -> None:
        """Test decision maker detection."""
        assert scraper._is_decision_maker("CEO")
        assert scraper._is_decision_maker("Chief Executive Officer")
        assert scraper._is_decision_maker("Founder & CEO")
        assert scraper._is_decision_maker("Managing Director")
        assert scraper._is_decision_maker("Head of Engineering")
        assert not scraper._is_decision_maker("Software Developer")
        assert not scraper._is_decision_maker("Junior Designer")

    def test_is_valid_email(self, scraper: WebsiteScraper) -> None:
        """Test email validation."""
        assert scraper._is_valid_email("user@company.nl")
        assert not scraper._is_valid_email("user@example.com")  # Test domain
        assert not scraper._is_valid_email("image.png@site.com")

    def test_extract_contact_info(self, scraper: WebsiteScraper) -> None:
        """Test extracting contact info from HTML."""
        html = """
        <html>
        <body>
            <a href="mailto:info@company.nl">Contact us</a>
            <p>Phone: +31 20 123 4567</p>
            <a href="https://linkedin.com/company/testco">LinkedIn</a>
            <a href="https://twitter.com/testco">Twitter</a>
        </body>
        </html>
        """
        info = ContactInfo()
        scraper._extract_contact_info(html, info)

        assert "info@company.nl" in info.emails
        assert any("+31" in p or "020" in p for p in info.phones)
        assert "linkedin" in info.social_links
        assert "twitter" in info.social_links

    def test_parse_team_card(self, scraper: WebsiteScraper) -> None:
        """Test parsing team member card."""
        from bs4 import BeautifulSoup

        html = """
        <div class="team-member">
            <h3 class="name">John Doe</h3>
            <p class="title">CEO & Founder</p>
            <a href="mailto:john@company.nl">Email</a>
            <a href="https://linkedin.com/in/johndoe">LinkedIn</a>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div", class_="team-member")

        person = scraper._parse_team_card(card)

        assert person is not None
        assert person.full_name == "John Doe"
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.job_title == "CEO & Founder"
        assert person.email == "john@company.nl"
        assert "linkedin.com" in person.linkedin_url

    def test_parse_team_card_no_name(self, scraper: WebsiteScraper) -> None:
        """Test parsing card without name returns None."""
        from bs4 import BeautifulSoup

        html = """
        <div class="team-member">
            <p class="title">Some Role</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.find("div", class_="team-member")

        person = scraper._parse_team_card(card)
        assert person is None

    @pytest.mark.asyncio
    async def test_find_team_pages(self, scraper: WebsiteScraper) -> None:
        """Test finding team page URLs."""
        scraper._page_exists = AsyncMock(side_effect=lambda url: "/team" in url or "/about" in url)
        scraper._fetch_page = AsyncMock(return_value="<html></html>")

        pages = await scraper._find_team_pages("https://example.com")

        assert any("/team" in p for p in pages) or any("/about" in p for p in pages)


class TestPerson:
    """Tests for Person dataclass."""

    def test_name_property_full(self) -> None:
        """Test name property with full name."""
        person = Person(full_name="John Doe")
        assert person.name == "John Doe"

    def test_name_property_parts(self) -> None:
        """Test name property from parts."""
        person = Person(first_name="John", last_name="Doe")
        assert person.name == "John Doe"

    def test_name_property_unknown(self) -> None:
        """Test name property with no name."""
        person = Person()
        assert person.name == "Unknown"

    def test_confidence_default(self) -> None:
        """Test default confidence."""
        person = Person()
        assert person.confidence == 50
