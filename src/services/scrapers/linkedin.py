"""LinkedIn scraper for finding companies and their employees."""

import asyncio
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScraperType, ScrapeResult
from src.services.scrapers.proxy_manager import ProxyManager


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn company pages.

    Note: LinkedIn heavily restricts scraping. This scraper:
    - Uses proxy rotation to avoid IP blocks
    - Implements aggressive rate limiting
    - Scrapes public company pages only
    - May require Playwright for JavaScript rendering
    """

    source = ScraperType.LINKEDIN
    BASE_URL = "https://www.linkedin.com"
    COMPANY_SEARCH_URL = "https://www.linkedin.com/search/results/companies/"

    def __init__(
        self,
        rate_limit_seconds: float = 10.0,  # Higher rate limit for LinkedIn
        proxy_manager: ProxyManager | None = None,
        use_playwright: bool = True,
    ) -> None:
        """Initialize LinkedIn scraper.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
            proxy_manager: Optional proxy manager for rotation.
            use_playwright: Use Playwright for JS rendering.
        """
        super().__init__(rate_limit_seconds)
        self.proxy_manager = proxy_manager
        self.use_playwright = use_playwright
        self._http_client: Any = None
        self._playwright: Any = None
        self._browser: Any = None

    async def _get_client(self) -> Any:
        """Get HTTP client (httpx for simple requests)."""
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
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
                },
                follow_redirects=True,
            )
        return self._http_client

    async def _get_browser(self) -> Any:
        """Get Playwright browser instance."""
        if not self.use_playwright:
            return None

        if self._playwright is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        return self._browser

    async def close(self) -> None:
        """Close all connections."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def scrape(
        self,
        keywords: list[str],
        filters: dict[str, Any] | None = None,
        max_pages: int = 3,
    ) -> ScrapeResult:
        """Scrape LinkedIn for companies.

        Args:
            keywords: Search keywords.
            filters: Optional filters (location, company_size, etc).
            max_pages: Maximum pages to scrape.

        Returns:
            ScrapeResult with companies.
        """
        start_time = datetime.now()
        all_companies: dict[str, CompanyRaw] = {}
        errors: list[str] = []
        pages_scraped = 0

        filters = filters or {}

        for keyword in keywords:
            for page in range(max_pages):
                try:
                    await self._wait_for_rate_limit()

                    # Get proxy if available
                    proxy = None
                    if self.proxy_manager:
                        proxy = await self.proxy_manager.get_proxy()

                    html = await self._fetch_search_page(keyword, page, filters, proxy)
                    if not html:
                        errors.append(f"Failed to fetch LinkedIn page {page} for '{keyword}'")
                        continue

                    pages_scraped += 1
                    companies = await self.parse_listing(html)

                    # Mark proxy as successful if we got results
                    if proxy and self.proxy_manager:
                        await self.proxy_manager.mark_proxy_result(
                            proxy, success=len(companies) > 0
                        )

                    for company in companies:
                        key = company.linkedin_url or company.name.lower()
                        if key not in all_companies:
                            all_companies[key] = company

                    # Small page count means no more results
                    if len(companies) < 5:
                        break

                except Exception as e:
                    errors.append(f"LinkedIn scrape error: {e!s}")
                    if proxy and self.proxy_manager:
                        await self.proxy_manager.mark_proxy_result(proxy, success=False)
                    await asyncio.sleep(10)  # Longer backoff for LinkedIn

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

    async def _fetch_search_page(
        self,
        keyword: str,
        page: int,
        filters: dict[str, Any],
        proxy: Any | None,
    ) -> str | None:
        """Fetch a LinkedIn search results page.

        Args:
            keyword: Search keyword.
            page: Page number.
            filters: Search filters.
            proxy: Proxy to use.

        Returns:
            HTML content or None on failure.
        """
        url = self._build_search_url(keyword, page, filters)

        if self.use_playwright:
            return await self._fetch_with_playwright(url, proxy)
        else:
            return await self._fetch_with_httpx(url, proxy)

    async def _fetch_with_playwright(self, url: str, proxy: Any | None) -> str | None:
        """Fetch page using Playwright (handles JavaScript).

        Args:
            url: URL to fetch.
            proxy: Proxy configuration.

        Returns:
            Page HTML or None.
        """
        try:
            browser = await self._get_browser()
            if not browser:
                return None

            context_options: dict[str, Any] = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1920, "height": 1080},
                "locale": "en-US",
            }

            if proxy:
                context_options["proxy"] = {"server": proxy.url}

            context = await browser.new_context(**context_options)
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait for content to load
                await page.wait_for_timeout(2000)

                # Scroll to trigger lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(1000)

                html = await page.content()
                return html

            finally:
                await context.close()

        except Exception:
            return None

    async def _fetch_with_httpx(self, url: str, proxy: Any | None) -> str | None:
        """Fetch page using httpx (simple HTTP).

        Args:
            url: URL to fetch.
            proxy: Proxy configuration.

        Returns:
            HTML or None.
        """
        try:
            import httpx

            client_kwargs: dict[str, Any] = {
                "timeout": 30.0,
                "headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
                "follow_redirects": True,
            }

            if proxy:
                client_kwargs["proxy"] = proxy.url

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text

        except Exception:
            return None

    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse LinkedIn search results.

        Args:
            html: Raw HTML.

        Returns:
            List of companies.
        """
        soup = BeautifulSoup(html, "html.parser")
        companies: list[CompanyRaw] = []

        # Find company cards in search results
        # LinkedIn uses various selectors
        cards = soup.find_all(
            "div",
            class_=re.compile(r"search-result|entity-result|reusable-search"),
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
        """Parse a company search result card.

        Args:
            card: BeautifulSoup element.

        Returns:
            CompanyRaw or None.
        """
        # Find company name
        name_elem = card.find(
            ["span", "a"],
            class_=re.compile(r"entity-result__title|company-name"),
        )
        if not name_elem:
            return None

        company_name = name_elem.get_text(strip=True)
        if not company_name:
            return None

        # Find LinkedIn URL
        linkedin_url = None
        link = card.find("a", href=re.compile(r"/company/"))
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                linkedin_url = f"{self.BASE_URL}{href}"
            else:
                linkedin_url = href.split("?")[0]  # Remove query params

        # Find industry
        industry = None
        industry_elem = card.find(
            class_=re.compile(r"entity-result__primary-subtitle|industry")
        )
        if industry_elem:
            industry = industry_elem.get_text(strip=True)

        # Find location
        location = None
        location_elem = card.find(
            class_=re.compile(r"entity-result__secondary-subtitle|location")
        )
        if location_elem:
            location = location_elem.get_text(strip=True)

        # Find employee count from snippet
        employee_count = None
        snippet = card.find(class_=re.compile(r"entity-result__summary|snippet"))
        if snippet:
            text = snippet.get_text()
            emp_match = re.search(r"(\d+(?:,\d+)?)\s*(?:employees|werknemers)", text, re.I)
            if emp_match:
                employee_count = self._normalize_employee_count(emp_match.group(1))

        return CompanyRaw(
            name=company_name,
            source=self.source,
            linkedin_url=linkedin_url,
            industry=industry,
            location=location,
            employee_count=employee_count,
            raw_data={"source_page": "linkedin_search"},
        )

    def _build_search_url(
        self, keyword: str, page: int, filters: dict[str, Any]
    ) -> str:
        """Build LinkedIn company search URL.

        Args:
            keyword: Search keyword.
            page: Page number.
            filters: Search filters.

        Returns:
            Formatted search URL.
        """
        from urllib.parse import quote_plus

        params = [f"keywords={quote_plus(keyword)}"]

        if page > 0:
            params.append(f"page={page + 1}")

        # Add filters
        if filters.get("company_size"):
            # LinkedIn uses company size codes
            params.append(f"companySize={filters['company_size']}")

        if filters.get("location"):
            params.append(f"geoUrn={quote_plus(filters['location'])}")

        return f"{self.COMPANY_SEARCH_URL}?{'&'.join(params)}"

    async def scrape_company_page(self, linkedin_url: str) -> CompanyRaw | None:
        """Scrape detailed company info from company page.

        Args:
            linkedin_url: LinkedIn company page URL.

        Returns:
            CompanyRaw with detailed info or None.
        """
        try:
            await self._wait_for_rate_limit()

            proxy = None
            if self.proxy_manager:
                proxy = await self.proxy_manager.get_proxy()

            if self.use_playwright:
                html = await self._fetch_with_playwright(linkedin_url, proxy)
            else:
                html = await self._fetch_with_httpx(linkedin_url, proxy)

            if not html:
                return None

            return self._parse_company_page(html, linkedin_url)

        except Exception:
            return None

    def _parse_company_page(self, html: str, linkedin_url: str) -> CompanyRaw | None:
        """Parse LinkedIn company about page.

        Args:
            html: Page HTML.
            linkedin_url: Company LinkedIn URL.

        Returns:
            CompanyRaw with details.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Find company name
        name_elem = soup.find("h1", class_=re.compile(r"org-top-card"))
        if not name_elem:
            name_elem = soup.find("h1")
        if not name_elem:
            return None

        company_name = name_elem.get_text(strip=True)

        # Find website
        website_url = None
        website_link = soup.find("a", {"data-tracking-control-name": re.compile(r"website")})
        if website_link:
            website_url = website_link.get("href")

        # Find employee count
        employee_count = None
        emp_elem = soup.find(string=re.compile(r"\d+.*employees", re.I))
        if emp_elem:
            employee_count = self._normalize_employee_count(emp_elem)

        # Find industry
        industry = None
        industry_elem = soup.find(class_=re.compile(r"org-top-card.*industry"))
        if industry_elem:
            industry = industry_elem.get_text(strip=True)

        # Find description
        description = None
        desc_elem = soup.find(class_=re.compile(r"org-about.*text"))
        if desc_elem:
            description = desc_elem.get_text(strip=True)[:500]  # Truncate

        return CompanyRaw(
            name=company_name,
            source=self.source,
            linkedin_url=linkedin_url,
            website_url=website_url,
            domain=self._extract_domain(website_url),
            industry=industry,
            employee_count=employee_count,
            description=description,
            raw_data={"source_page": "linkedin_company"},
        )
