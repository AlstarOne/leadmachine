"""Indeed scraper for finding companies with open vacancies."""

import asyncio
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScraperType, ScrapeResult


class IndeedScraper(BaseScraper):
    """Scraper for Indeed.nl job listings to find hiring companies."""

    source = ScraperType.INDEED
    BASE_URL = "https://nl.indeed.com"

    def __init__(
        self,
        rate_limit_seconds: float = 3.0,
        min_vacancies: int = 5,
    ) -> None:
        """Initialize Indeed scraper.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
            min_vacancies: Minimum open vacancies to include company.
        """
        super().__init__(rate_limit_seconds)
        self.min_vacancies = min_vacancies
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
        """Scrape Indeed for companies with job listings.

        Args:
            keywords: Job search keywords.
            filters: Optional filters like location.
            max_pages: Maximum pages to scrape per keyword.

        Returns:
            ScrapeResult with found companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}  # Dedupe by name
        errors: list[str] = []
        pages_scraped = 0

        filters = filters or {}
        location = filters.get("location", "Nederland")

        client = await self._get_client()

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    # Build search URL
                    start = page * 10  # Indeed uses 10 results per page
                    url = self._build_search_url(keyword, location, start)

                    response = await client.get(url)
                    response.raise_for_status()
                    pages_scraped += 1

                    # Parse listings
                    companies = await self.parse_listing(response.text)

                    for company in companies:
                        # Dedupe by name (case-insensitive)
                        key = company.name.lower().strip()
                        if key not in all_companies:
                            all_companies[key] = company
                        else:
                            # Merge vacancy counts
                            all_companies[key].open_vacancies += company.open_vacancies

                    # Check if there are more pages
                    if not self._has_next_page(response.text):
                        break

                except Exception as e:
                    errors.append(f"Error scraping Indeed page {page} for '{keyword}': {e!s}")
                    await asyncio.sleep(5)  # Back off on error

        # Filter by minimum vacancies
        filtered_companies = [
            c for c in all_companies.values() if c.open_vacancies >= self.min_vacancies
        ]

        duration = (datetime.now() - start_time).total_seconds()

        return ScrapeResult(
            success=len(errors) == 0 or len(filtered_companies) > 0,
            companies=filtered_companies,
            total_found=len(filtered_companies),
            errors=errors,
            duration_seconds=duration,
            pages_scraped=pages_scraped,
        )

    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse Indeed search results page.

        Args:
            html: Raw HTML of search results page.

        Returns:
            List of parsed company data.
        """
        soup = BeautifulSoup(html, "html.parser")
        companies: list[CompanyRaw] = []
        seen_companies: set[str] = set()

        # Find job cards - Indeed uses various class names
        job_cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|jobCard"))

        for card in job_cards:
            try:
                company = self._parse_job_card(card)
                if company and company.name.lower() not in seen_companies:
                    companies.append(company)
                    seen_companies.add(company.name.lower())
            except Exception:
                continue

        return companies

    def _parse_job_card(self, card: Any) -> CompanyRaw | None:
        """Parse a single job card to extract company info.

        Args:
            card: BeautifulSoup element for job card.

        Returns:
            CompanyRaw or None if parsing fails.
        """
        # Try to find company name
        company_elem = card.find("span", {"data-testid": "company-name"})
        if not company_elem:
            company_elem = card.find("span", class_=re.compile(r"company"))

        if not company_elem:
            return None

        company_name = company_elem.get_text(strip=True)
        if not company_name:
            return None

        # Try to find location
        location_elem = card.find("div", {"data-testid": "text-location"})
        if not location_elem:
            location_elem = card.find("div", class_=re.compile(r"location"))
        location = location_elem.get_text(strip=True) if location_elem else None

        # Try to find job link to construct company page URL
        job_link = card.find("a", href=re.compile(r"/rc/clk|/company/"))
        source_url = None
        if job_link and job_link.get("href"):
            href = job_link["href"]
            if href.startswith("/"):
                source_url = f"{self.BASE_URL}{href}"
            else:
                source_url = href

        return CompanyRaw(
            name=company_name,
            source=self.source,
            source_url=source_url,
            location=location,
            open_vacancies=1,  # Each job card = 1 vacancy
            raw_data={"source_page": "indeed_search"},
        )

    def _build_search_url(self, keyword: str, location: str, start: int) -> str:
        """Build Indeed search URL.

        Args:
            keyword: Search keyword.
            location: Location filter.
            start: Result offset.

        Returns:
            Formatted search URL.
        """
        from urllib.parse import quote_plus

        params = [
            f"q={quote_plus(keyword)}",
            f"l={quote_plus(location)}",
        ]
        if start > 0:
            params.append(f"start={start}")

        return f"{self.BASE_URL}/jobs?{'&'.join(params)}"

    def _has_next_page(self, html: str) -> bool:
        """Check if there are more pages of results.

        Args:
            html: Page HTML.

        Returns:
            True if next page exists.
        """
        soup = BeautifulSoup(html, "html.parser")
        # Look for next page link or pagination
        next_link = soup.find("a", {"aria-label": re.compile(r"Next|Volgende", re.I)})
        return next_link is not None
