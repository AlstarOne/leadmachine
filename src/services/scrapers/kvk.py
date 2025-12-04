"""KvK (Kamer van Koophandel) scraper for finding newly registered companies."""

import asyncio
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScraperType, ScrapeResult


class KvKScraper(BaseScraper):
    """Scraper for KvK handelsregister to find new Dutch companies."""

    source = ScraperType.KVK
    BASE_URL = "https://www.kvk.nl"
    SEARCH_URL = "https://www.kvk.nl/zoeken/handelsregister/"

    # Relevant SBI codes for tech/software companies
    TECH_SBI_CODES = [
        "6201",  # Computer programming
        "6202",  # Computer consultancy
        "6209",  # Other IT services
        "6311",  # Data processing
        "6312",  # Web portals
        "7022",  # Business/management consultancy
        "7112",  # Engineering
    ]

    def __init__(
        self,
        rate_limit_seconds: float = 3.0,
        target_sbi_codes: list[str] | None = None,
    ) -> None:
        """Initialize KvK scraper.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
            target_sbi_codes: SBI codes to filter by (default: tech companies).
        """
        super().__init__(rate_limit_seconds)
        self.target_sbi_codes = target_sbi_codes or self.TECH_SBI_CODES
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
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        max_pages: int = 5,
    ) -> ScrapeResult:
        """Scrape KvK for newly registered companies.

        Args:
            keywords: Search keywords (company types, industries).
            filters: Optional filters like legal_form, location.
            max_pages: Maximum pages to scrape per keyword.

        Returns:
            ScrapeResult with found companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}  # Dedupe by KvK number
        errors: list[str] = []
        pages_scraped = 0

        filters = filters or {}
        legal_form = filters.get("legal_form", "BV")  # Focus on BVs

        client = await self._get_client()

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    url = self._build_search_url(keyword, legal_form, page)
                    response = await client.get(url)
                    response.raise_for_status()
                    pages_scraped += 1

                    companies = await self.parse_listing(response.text)

                    for company in companies:
                        # Dedupe by domain or name
                        key = company.domain or company.name.lower().strip()
                        if key not in all_companies:
                            all_companies[key] = company

                    # Check for more pages
                    if not self._has_next_page(response.text):
                        break

                except Exception as e:
                    errors.append(f"Error scraping KvK page {page} for '{keyword}': {e!s}")
                    await asyncio.sleep(5)

        companies_list = list(all_companies.values())
        duration = (datetime.now() - start_time).total_seconds()

        return ScrapeResult(
            success=len(errors) == 0 or len(companies_list) > 0,
            companies=companies_list,
            total_found=len(companies_list),
            errors=errors,
            duration_seconds=duration,
            pages_scraped=pages_scraped,
        )

    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse KvK search results page.

        Args:
            html: Raw HTML of search results.

        Returns:
            List of parsed companies.
        """
        soup = BeautifulSoup(html, "html.parser")
        companies: list[CompanyRaw] = []

        # Find company result cards
        results = soup.find_all("li", class_=re.compile(r"search-result|result-item"))

        for result in results:
            try:
                company = self._parse_result_card(result)
                if company:
                    companies.append(company)
            except Exception:
                continue

        return companies

    def _parse_result_card(self, card: Any) -> CompanyRaw | None:
        """Parse a KvK result card.

        Args:
            card: BeautifulSoup element.

        Returns:
            CompanyRaw or None.
        """
        # Find company name (usually in h3 or strong)
        name_elem = card.find(["h3", "strong", "a"], class_=re.compile(r"name|title"))
        if not name_elem:
            name_elem = card.find("a")

        if not name_elem:
            return None

        company_name = name_elem.get_text(strip=True)
        if not company_name or len(company_name) < 2:
            return None

        # Try to find KvK number
        kvk_number = None
        kvk_elem = card.find(string=re.compile(r"KVK|kvk"))
        if kvk_elem:
            kvk_match = re.search(r"(\d{8})", kvk_elem)
            if kvk_match:
                kvk_number = kvk_match.group(1)

        # Find location
        location = None
        location_elem = card.find(class_=re.compile(r"location|address|plaats"))
        if location_elem:
            location = location_elem.get_text(strip=True)

        # Find industry/activity
        industry = None
        activity_elem = card.find(class_=re.compile(r"activity|activiteit|sbi"))
        if activity_elem:
            industry = activity_elem.get_text(strip=True)

        # Find link to detail page
        source_url = None
        link = card.find("a", href=re.compile(r"/orderstraat/|/zoeken/"))
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                source_url = f"{self.BASE_URL}{href}"
            else:
                source_url = href

        return CompanyRaw(
            name=company_name,
            source=self.source,
            source_url=source_url,
            location=location,
            industry=industry,
            raw_data={
                "kvk_number": kvk_number,
                "source_page": "kvk_search",
            },
        )

    def _build_search_url(self, keyword: str, legal_form: str, page: int) -> str:
        """Build KvK search URL.

        Args:
            keyword: Search keyword.
            legal_form: Legal form filter (BV, NV, etc).
            page: Page number.

        Returns:
            Formatted search URL.
        """
        from urllib.parse import quote_plus

        params = [
            f"handelsnaam={quote_plus(keyword)}",
            f"rechtsvorm={quote_plus(legal_form)}",
            "hoofdvestiging=1",  # Only main establishments
        ]
        if page > 0:
            params.append(f"pagina={page + 1}")

        return f"{self.SEARCH_URL}?{'&'.join(params)}"

    def _has_next_page(self, html: str) -> bool:
        """Check if there are more results pages.

        Args:
            html: Page HTML.

        Returns:
            True if next page exists.
        """
        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.find("a", {"rel": "next"})
        if not next_link:
            next_link = soup.find("a", class_=re.compile(r"next|volgende"))
        return next_link is not None


class KvKApiScraper(BaseScraper):
    """Alternative scraper using KvK API (requires API key)."""

    source = ScraperType.KVK
    API_BASE_URL = "https://api.kvk.nl/api/v1"

    def __init__(
        self,
        api_key: str,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        """Initialize KvK API scraper.

        Args:
            api_key: KvK API key.
            rate_limit_seconds: Minimum seconds between requests.
        """
        super().__init__(rate_limit_seconds)
        self.api_key = api_key
        self._http_client: Any = None

    async def _get_client(self) -> Any:
        """Get or create HTTP client with API auth."""
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "apikey": self.api_key,
                    "Accept": "application/json",
                },
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
        """Scrape KvK via API.

        Args:
            keywords: Search keywords.
            filters: Optional filters.
            max_pages: Maximum pages per keyword.

        Returns:
            ScrapeResult with companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}
        errors: list[str] = []
        pages_scraped = 0

        client = await self._get_client()

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    params = {
                        "handelsnaam": keyword,
                        "pagina": page + 1,
                        "resultatenPerPagina": 10,
                    }

                    response = await client.get(
                        f"{self.API_BASE_URL}/zoeken", params=params
                    )
                    response.raise_for_status()
                    pages_scraped += 1

                    data = response.json()
                    companies = self._parse_api_response(data)

                    for company in companies:
                        key = company.domain or company.name.lower()
                        if key not in all_companies:
                            all_companies[key] = company

                    # Check for more pages
                    if not data.get("resultaten") or len(data["resultaten"]) < 10:
                        break

                except Exception as e:
                    errors.append(f"KvK API error for '{keyword}': {e!s}")
                    await asyncio.sleep(2)

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
        """Not used for API scraper."""
        return []

    def _parse_api_response(self, data: dict[str, Any]) -> list[CompanyRaw]:
        """Parse KvK API response.

        Args:
            data: JSON response data.

        Returns:
            List of companies.
        """
        companies: list[CompanyRaw] = []

        for result in data.get("resultaten", []):
            try:
                company = CompanyRaw(
                    name=result.get("handelsnaam", ""),
                    source=self.source,
                    source_url=result.get("links", [{}])[0].get("href"),
                    location=result.get("adres", {}).get("plaats"),
                    industry=result.get("sbiActiviteiten", [{}])[0].get("sbiOmschrijving"),
                    raw_data={
                        "kvk_number": result.get("kvkNummer"),
                        "vestigingsnummer": result.get("vestigingsnummer"),
                        "type": result.get("type"),
                    },
                )
                if company.name:
                    companies.append(company)
            except Exception:
                continue

        return companies
