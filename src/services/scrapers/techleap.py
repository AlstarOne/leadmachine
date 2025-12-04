"""Techleap and Dealroom scrapers for finding funded Dutch startups/scale-ups."""

import asyncio
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScraperType, ScrapeResult


class TechleapScraper(BaseScraper):
    """Scraper for Techleap.nl funded companies database."""

    source = ScraperType.TECHLEAP
    BASE_URL = "https://finder.techleap.nl"

    def __init__(self, rate_limit_seconds: float = 2.0) -> None:
        """Initialize Techleap scraper.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
        """
        super().__init__(rate_limit_seconds)
        self._http_client: Any = None

    async def _get_client(self) -> Any:
        """Get or create HTTP client."""
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/html",
                    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def scrape(
        self,
        keywords: list[str],
        filters: dict[str, Any] | None = None,
        max_pages: int = 10,
    ) -> ScrapeResult:
        """Scrape Techleap for funded companies.

        Args:
            keywords: Search keywords (industries, technologies).
            filters: Optional filters (funding_stage, location).
            max_pages: Maximum pages to scrape.

        Returns:
            ScrapeResult with companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}
        errors: list[str] = []
        pages_scraped = 0

        filters = filters or {}
        client = await self._get_client()

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    url = self._build_search_url(keyword, page, filters)
                    response = await client.get(url)
                    response.raise_for_status()
                    pages_scraped += 1

                    # Try JSON first (API), fallback to HTML
                    try:
                        data = response.json()
                        companies = self._parse_json_response(data)
                    except Exception:
                        companies = await self.parse_listing(response.text)

                    for company in companies:
                        key = company.domain or company.name.lower()
                        if key not in all_companies:
                            all_companies[key] = company

                    # Check for more results
                    if len(companies) < 10:
                        break

                except Exception as e:
                    errors.append(f"Techleap scrape error for '{keyword}': {e!s}")
                    await asyncio.sleep(3)

        companies_list = list(all_companies.values())
        duration = (datetime.now() - start_time).total_seconds()

        return ScrapeResult(
            success=len(companies_list) > 0 or len(errors) == 0,
            companies=companies_list,
            total_found=len(companies_list),
            errors=errors,
            duration_seconds=duration,
            pages_scraped=pages_scraped,
        )

    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse Techleap HTML listing.

        Args:
            html: Raw HTML.

        Returns:
            List of companies.
        """
        soup = BeautifulSoup(html, "html.parser")
        companies: list[CompanyRaw] = []

        # Find company cards
        cards = soup.find_all(
            "div",
            class_=re.compile(r"company-card|startup-item|result-card"),
        )

        for card in cards:
            try:
                company = self._parse_company_card(card)
                if company:
                    companies.append(company)
            except Exception:
                continue

        return companies

    def _parse_company_card(self, card: Any) -> CompanyRaw | None:
        """Parse a company card element.

        Args:
            card: BeautifulSoup element.

        Returns:
            CompanyRaw or None.
        """
        # Find company name
        name_elem = card.find(["h2", "h3", "a"], class_=re.compile(r"name|title"))
        if not name_elem:
            name_elem = card.find("a")
        if not name_elem:
            return None

        company_name = name_elem.get_text(strip=True)
        if not company_name:
            return None

        # Find website/domain
        website_url = None
        domain = None
        website_link = card.find("a", href=re.compile(r"^https?://(?!finder\.techleap)"))
        if website_link:
            website_url = website_link.get("href")
            domain = self._extract_domain(website_url)

        # Find funding info
        has_funding = False
        funding_amount = None
        funding_elem = card.find(string=re.compile(r"€|EUR|\$|funding|raised", re.I))
        if funding_elem:
            has_funding = True
            funding_match = re.search(r"[€$]?\s*(\d+(?:\.\d+)?)\s*[MK]?", str(funding_elem))
            if funding_match:
                funding_amount = funding_match.group(0).strip()

        # Find industry/tags
        industry = None
        tags_elem = card.find(class_=re.compile(r"tags|industry|sector"))
        if tags_elem:
            industry = tags_elem.get_text(strip=True)[:100]

        # Find location
        location = None
        location_elem = card.find(class_=re.compile(r"location|city"))
        if location_elem:
            location = location_elem.get_text(strip=True)

        # Find employee count
        employee_count = None
        emp_elem = card.find(string=re.compile(r"\d+\s*(?:employees|FTE)", re.I))
        if emp_elem:
            employee_count = self._normalize_employee_count(str(emp_elem))

        # Find LinkedIn
        linkedin_url = None
        linkedin_link = card.find("a", href=re.compile(r"linkedin\.com"))
        if linkedin_link:
            linkedin_url = linkedin_link.get("href")

        # Source URL
        source_url = None
        detail_link = card.find("a", href=re.compile(r"/companies?/|/startup/"))
        if detail_link and detail_link.get("href"):
            href = detail_link["href"]
            if href.startswith("/"):
                source_url = f"{self.BASE_URL}{href}"
            else:
                source_url = href

        return CompanyRaw(
            name=company_name,
            source=self.source,
            source_url=source_url,
            domain=domain,
            website_url=website_url,
            linkedin_url=linkedin_url,
            industry=industry,
            employee_count=employee_count,
            location=location,
            has_funding=has_funding,
            funding_amount=funding_amount,
            raw_data={"source_page": "techleap_search"},
        )

    def _parse_json_response(self, data: dict[str, Any]) -> list[CompanyRaw]:
        """Parse Techleap API JSON response.

        Args:
            data: JSON response data.

        Returns:
            List of companies.
        """
        companies: list[CompanyRaw] = []

        # Handle various JSON structures
        results = data.get("results", data.get("companies", data.get("data", [])))
        if isinstance(results, dict):
            results = results.get("items", [])

        for item in results:
            try:
                company = CompanyRaw(
                    name=item.get("name", item.get("company_name", "")),
                    source=self.source,
                    source_url=item.get("url", item.get("techleap_url")),
                    domain=item.get("domain"),
                    website_url=item.get("website", item.get("website_url")),
                    linkedin_url=item.get("linkedin_url", item.get("linkedin")),
                    industry=item.get("industry", item.get("sector")),
                    employee_count=item.get("employees", item.get("employee_count")),
                    location=item.get("city", item.get("location")),
                    has_funding=bool(item.get("funding") or item.get("raised")),
                    funding_amount=item.get("funding_amount", item.get("total_raised")),
                    raw_data=item,
                )
                if company.name:
                    companies.append(company)
            except Exception:
                continue

        return companies

    def _build_search_url(
        self, keyword: str, page: int, filters: dict[str, Any]
    ) -> str:
        """Build Techleap search URL.

        Args:
            keyword: Search keyword.
            page: Page number.
            filters: Search filters.

        Returns:
            Search URL.
        """
        from urllib.parse import quote_plus

        params = [f"q={quote_plus(keyword)}"]

        if page > 0:
            params.append(f"page={page + 1}")

        # Add filters
        if filters.get("funding_stage"):
            params.append(f"stage={filters['funding_stage']}")

        if filters.get("location"):
            params.append(f"city={quote_plus(filters['location'])}")

        return f"{self.BASE_URL}/companies?{'&'.join(params)}"


class DealroomScraper(BaseScraper):
    """Scraper for Dealroom.co startup database."""

    source = ScraperType.DEALROOM
    BASE_URL = "https://dealroom.co"
    API_URL = "https://api.dealroom.co"

    def __init__(
        self,
        rate_limit_seconds: float = 2.0,
        api_key: str | None = None,
    ) -> None:
        """Initialize Dealroom scraper.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
            api_key: Optional Dealroom API key for higher limits.
        """
        super().__init__(rate_limit_seconds)
        self.api_key = api_key
        self._http_client: Any = None

    async def _get_client(self) -> Any:
        """Get or create HTTP client."""
        if self._http_client is None:
            import httpx

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }

            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers=headers,
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def scrape(
        self,
        keywords: list[str],
        filters: dict[str, Any] | None = None,
        max_pages: int = 5,
    ) -> ScrapeResult:
        """Scrape Dealroom for funded companies.

        Args:
            keywords: Search keywords.
            filters: Optional filters (country, funding_stage).
            max_pages: Maximum pages per keyword.

        Returns:
            ScrapeResult with companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}
        errors: list[str] = []
        pages_scraped = 0

        filters = filters or {}
        # Default to Netherlands
        filters.setdefault("country", "Netherlands")

        client = await self._get_client()

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    url = self._build_search_url(keyword, page, filters)
                    response = await client.get(url)
                    response.raise_for_status()
                    pages_scraped += 1

                    # Parse response
                    try:
                        data = response.json()
                        companies = self._parse_api_response(data)
                    except Exception:
                        companies = await self.parse_listing(response.text)

                    for company in companies:
                        key = company.domain or company.name.lower()
                        if key not in all_companies:
                            all_companies[key] = company

                    if len(companies) < 10:
                        break

                except Exception as e:
                    errors.append(f"Dealroom error for '{keyword}': {e!s}")
                    await asyncio.sleep(3)

        companies_list = list(all_companies.values())
        duration = (datetime.now() - start_time).total_seconds()

        return ScrapeResult(
            success=len(companies_list) > 0,
            companies=companies_list,
            total_found=len(companies_list),
            errors=errors,
            duration_seconds=duration,
            pages_scraped=pages_scraped,
        )

    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse Dealroom HTML page.

        Args:
            html: Raw HTML.

        Returns:
            List of companies.
        """
        soup = BeautifulSoup(html, "html.parser")
        companies: list[CompanyRaw] = []

        # Find company cards
        cards = soup.find_all(
            "div",
            class_=re.compile(r"company-row|startup-card|entity-card"),
        )

        for card in cards:
            try:
                company = self._parse_html_card(card)
                if company:
                    companies.append(company)
            except Exception:
                continue

        return companies

    def _parse_html_card(self, card: Any) -> CompanyRaw | None:
        """Parse Dealroom HTML company card.

        Args:
            card: BeautifulSoup element.

        Returns:
            CompanyRaw or None.
        """
        name_elem = card.find(class_=re.compile(r"company-name|title"))
        if not name_elem:
            return None

        company_name = name_elem.get_text(strip=True)
        if not company_name:
            return None

        # Find other fields
        website_url = None
        website_link = card.find("a", href=re.compile(r"^https?://(?!dealroom)"))
        if website_link:
            website_url = website_link.get("href")

        # Funding
        has_funding = False
        funding_amount = None
        funding_elem = card.find(class_=re.compile(r"funding|raised"))
        if funding_elem:
            has_funding = True
            funding_amount = funding_elem.get_text(strip=True)

        return CompanyRaw(
            name=company_name,
            source=self.source,
            website_url=website_url,
            domain=self._extract_domain(website_url),
            has_funding=has_funding,
            funding_amount=funding_amount,
            raw_data={"source_page": "dealroom_search"},
        )

    def _parse_api_response(self, data: dict[str, Any]) -> list[CompanyRaw]:
        """Parse Dealroom API response.

        Args:
            data: JSON response.

        Returns:
            List of companies.
        """
        companies: list[CompanyRaw] = []

        items = data.get("items", data.get("companies", []))

        for item in items:
            try:
                # Parse funding
                funding = item.get("funding", {})
                has_funding = bool(funding.get("total") or funding.get("rounds"))
                funding_amount = None
                if funding.get("total"):
                    funding_amount = f"€{funding['total']}M" if funding.get("currency") == "EUR" else str(funding["total"])

                company = CompanyRaw(
                    name=item.get("name", ""),
                    source=self.source,
                    source_url=item.get("dealroom_url"),
                    domain=item.get("domain"),
                    website_url=item.get("website"),
                    linkedin_url=item.get("linkedin_url"),
                    industry=", ".join(item.get("industries", [])[:3]),
                    employee_count=item.get("employees", {}).get("value"),
                    location=item.get("hq_city", item.get("country")),
                    has_funding=has_funding,
                    funding_amount=funding_amount,
                    description=item.get("tagline", item.get("description", ""))[:500],
                    raw_data=item,
                )
                if company.name:
                    companies.append(company)
            except Exception:
                continue

        return companies

    def _build_search_url(
        self, keyword: str, page: int, filters: dict[str, Any]
    ) -> str:
        """Build Dealroom search URL.

        Args:
            keyword: Search keyword.
            page: Page number.
            filters: Search filters.

        Returns:
            Search URL.
        """
        from urllib.parse import quote_plus

        params = [
            f"q={quote_plus(keyword)}",
            f"page={page + 1}",
        ]

        if filters.get("country"):
            params.append(f"country={quote_plus(filters['country'])}")

        if filters.get("funding_stage"):
            params.append(f"stage={filters['funding_stage']}")

        return f"{self.BASE_URL}/companies?{'&'.join(params)}"
