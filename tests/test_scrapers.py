"""Tests for scraper services."""

import pytest

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScraperType, ScrapeResult


class TestCompanyRaw:
    """Tests for CompanyRaw dataclass."""

    def test_company_raw_creation(self) -> None:
        """Test creating a CompanyRaw instance."""
        company = CompanyRaw(
            name="Test Company",
            source=ScraperType.INDEED,
            domain="testcompany.com",
            location="Amsterdam",
            open_vacancies=5,
        )

        assert company.name == "Test Company"
        assert company.source == ScraperType.INDEED
        assert company.domain == "testcompany.com"
        assert company.open_vacancies == 5

    def test_company_raw_to_dict(self) -> None:
        """Test converting CompanyRaw to dictionary."""
        company = CompanyRaw(
            name="Test Company",
            source=ScraperType.KVK,
            industry="Software",
            employee_count=50,
        )

        data = company.to_dict()

        assert data["name"] == "Test Company"
        assert data["source"] == "KVK"
        assert data["industry"] == "Software"
        assert data["employee_count"] == 50

    def test_company_raw_defaults(self) -> None:
        """Test default values."""
        company = CompanyRaw(
            name="Minimal Company",
            source=ScraperType.LINKEDIN,
        )

        assert company.domain is None
        assert company.open_vacancies == 0
        assert company.has_funding is False
        assert company.raw_data == {}


class TestScrapeResult:
    """Tests for ScrapeResult dataclass."""

    def test_scrape_result_success(self) -> None:
        """Test successful scrape result."""
        result = ScrapeResult(
            success=True,
            companies=[
                CompanyRaw(name="Company A", source=ScraperType.INDEED),
                CompanyRaw(name="Company B", source=ScraperType.INDEED),
            ],
            total_found=2,
            pages_scraped=3,
            duration_seconds=10.5,
        )

        assert result.success is True
        assert len(result.companies) == 2
        assert result.error_count == 0

    def test_scrape_result_with_errors(self) -> None:
        """Test scrape result with errors."""
        result = ScrapeResult(
            success=False,
            errors=["Connection timeout", "Rate limited"],
        )

        assert result.success is False
        assert result.error_count == 2


class TestBaseScraper:
    """Tests for BaseScraper base class."""

    def test_extract_domain_from_url(self) -> None:
        """Test domain extraction from URLs."""
        # Create a concrete implementation for testing
        class TestScraper(BaseScraper):
            source = ScraperType.INDEED

            async def scrape(self, keywords, filters=None, max_pages=5):
                return ScrapeResult(success=True)

            async def parse_listing(self, html):
                return []

        scraper = TestScraper()

        # Test various URL formats
        assert scraper._extract_domain("https://www.example.com") == "example.com"
        assert scraper._extract_domain("http://example.com/page") == "example.com"
        assert scraper._extract_domain("https://subdomain.example.com") == "subdomain.example.com"
        assert scraper._extract_domain("www.example.nl") == "example.nl"
        assert scraper._extract_domain(None) is None
        assert scraper._extract_domain("") is None

    def test_normalize_employee_count(self) -> None:
        """Test employee count normalization."""
        class TestScraper(BaseScraper):
            source = ScraperType.INDEED

            async def scrape(self, keywords, filters=None, max_pages=5):
                return ScrapeResult(success=True)

            async def parse_listing(self, html):
                return []

        scraper = TestScraper()

        # Test various formats
        assert scraper._normalize_employee_count("50-100") == 75
        assert scraper._normalize_employee_count("100+") == 100
        assert scraper._normalize_employee_count("~500") == 500
        assert scraper._normalize_employee_count("1,000") == 1000
        assert scraper._normalize_employee_count(None) is None


class TestIndeedScraper:
    """Tests for Indeed scraper HTML parsing."""

    def test_parse_job_card_html(self) -> None:
        """Test parsing Indeed job card HTML."""
        from src.services.scrapers.indeed import IndeedScraper

        scraper = IndeedScraper()

        # Sample Indeed-like HTML structure
        html = """
        <div class="job_seen_beacon">
            <span data-testid="company-name">Tech Company BV</span>
            <div data-testid="text-location">Amsterdam</div>
            <a href="/rc/clk?jk=abc123">View Job</a>
        </div>
        <div class="job_seen_beacon">
            <span data-testid="company-name">Another Company</span>
            <div data-testid="text-location">Rotterdam</div>
        </div>
        """

        import asyncio
        companies = asyncio.run(scraper.parse_listing(html))

        assert len(companies) == 2
        assert companies[0].name == "Tech Company BV"
        assert companies[0].location == "Amsterdam"
        assert companies[0].source == ScraperType.INDEED

    def test_build_search_url(self) -> None:
        """Test Indeed search URL building."""
        from src.services.scrapers.indeed import IndeedScraper

        scraper = IndeedScraper()
        url = scraper._build_search_url("python developer", "Amsterdam", 0)

        assert "nl.indeed.com" in url
        assert "python" in url.lower()
        assert "amsterdam" in url.lower()


class TestKvKScraper:
    """Tests for KvK scraper."""

    def test_build_search_url(self) -> None:
        """Test KvK search URL building."""
        from src.services.scrapers.kvk import KvKScraper

        scraper = KvKScraper()
        url = scraper._build_search_url("software", "BV", 0)

        assert "kvk.nl" in url
        assert "software" in url.lower()
        assert "bv" in url.lower()


class TestLinkedInScraper:
    """Tests for LinkedIn scraper."""

    def test_build_search_url(self) -> None:
        """Test LinkedIn search URL building."""
        from src.services.scrapers.linkedin import LinkedInScraper

        scraper = LinkedInScraper(use_playwright=False)
        url = scraper._build_search_url("fintech", 0, {})

        assert "linkedin.com" in url
        assert "fintech" in url.lower()


class TestProxyManager:
    """Tests for proxy manager."""

    def test_add_proxy(self) -> None:
        """Test adding a proxy."""
        from src.services.scrapers.proxy_manager import ProxyManager

        manager = ProxyManager()
        manager.add_proxy("proxy.example.com", 8080, "user", "pass")

        assert manager.total_count == 1
        assert manager.available_count == 1

    def test_parse_proxy_string(self) -> None:
        """Test parsing proxy strings."""
        from src.services.scrapers.proxy_manager import ProxyManager

        manager = ProxyManager()

        # Test various formats
        proxy = manager._parse_proxy_string("host:8080")
        assert proxy is not None
        assert proxy.host == "host"
        assert proxy.port == 8080

        proxy = manager._parse_proxy_string("http://user:pass@host:8080")
        assert proxy is not None
        assert proxy.username == "user"
        assert proxy.password == "pass"

        proxy = manager._parse_proxy_string("host:8080:user:pass")
        assert proxy is not None
        assert proxy.username == "user"

    def test_proxy_success_rate(self) -> None:
        """Test proxy success rate calculation."""
        from src.services.scrapers.proxy_manager import Proxy

        proxy = Proxy(host="test", port=8080)

        # Initial rate should be 1.0
        assert proxy.success_rate == 1.0

        # Mark some successes and failures
        proxy.mark_success()
        proxy.mark_success()
        proxy.mark_failure()

        assert proxy.success_count == 2
        assert proxy.fail_count == 1
        assert proxy.success_rate == pytest.approx(2 / 3)

    def test_proxy_blocking(self) -> None:
        """Test proxy blocking on failures."""
        from src.services.scrapers.proxy_manager import Proxy

        proxy = Proxy(host="test", port=8080)

        # Should block after 3 failures
        proxy.mark_failure()
        proxy.mark_failure()
        assert not proxy.is_blocked

        proxy.mark_failure()
        assert proxy.is_blocked
        assert proxy.blocked_until is not None

    @pytest.mark.asyncio
    async def test_get_proxy_rotation(self) -> None:
        """Test proxy rotation."""
        from src.services.scrapers.proxy_manager import ProxyManager

        manager = ProxyManager(min_delay_between_uses=0)
        manager.add_proxy("proxy1.example.com", 8080)
        manager.add_proxy("proxy2.example.com", 8080)

        # Should return one of the proxies
        proxy = await manager.get_proxy()
        assert proxy is not None
        assert proxy.host in ["proxy1.example.com", "proxy2.example.com"]


class TestTechleapScraper:
    """Tests for Techleap scraper."""

    def test_build_search_url(self) -> None:
        """Test Techleap search URL building."""
        from src.services.scrapers.techleap import TechleapScraper

        scraper = TechleapScraper()
        url = scraper._build_search_url("ai", 0, {})

        assert "techleap" in url.lower()
        assert "ai" in url.lower()

    def test_parse_json_response(self) -> None:
        """Test parsing Techleap JSON API response."""
        from src.services.scrapers.techleap import TechleapScraper

        scraper = TechleapScraper()

        # Mock API response
        data = {
            "results": [
                {
                    "name": "AI Startup",
                    "domain": "aistartup.com",
                    "city": "Amsterdam",
                    "funding_amount": "€5M",
                },
                {
                    "name": "Tech Company",
                    "website": "https://techcompany.nl",
                    "employees": 50,
                },
            ]
        }

        companies = scraper._parse_json_response(data)

        assert len(companies) == 2
        assert companies[0].name == "AI Startup"
        assert companies[0].domain == "aistartup.com"
        assert companies[1].employee_count == 50
