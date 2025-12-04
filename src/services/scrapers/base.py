"""Base scraper interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ScraperType(str, Enum):
    """Types of scrapers available."""

    INDEED = "INDEED"
    KVK = "KVK"
    LINKEDIN = "LINKEDIN"
    TECHLEAP = "TECHLEAP"
    DEALROOM = "DEALROOM"


@dataclass
class CompanyRaw:
    """Raw company data from scraping before normalization."""

    name: str
    source: ScraperType
    source_url: str | None = None
    domain: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    open_vacancies: int = 0
    location: str | None = None
    description: str | None = None
    has_funding: bool = False
    funding_amount: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "name": self.name,
            "source": self.source.value,
            "source_url": self.source_url,
            "domain": self.domain,
            "website_url": self.website_url,
            "linkedin_url": self.linkedin_url,
            "industry": self.industry,
            "employee_count": self.employee_count,
            "open_vacancies": self.open_vacancies,
            "location": self.location,
            "description": self.description,
            "has_funding": self.has_funding,
            "funding_amount": self.funding_amount,
            "raw_data": self.raw_data,
        }


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""

    success: bool
    companies: list[CompanyRaw] = field(default_factory=list)
    total_found: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    pages_scraped: int = 0

    @property
    def error_count(self) -> int:
        """Get number of errors."""
        return len(self.errors)


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    source: ScraperType

    def __init__(self, rate_limit_seconds: float = 2.0) -> None:
        """Initialize scraper with rate limiting.

        Args:
            rate_limit_seconds: Minimum seconds between requests.
        """
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_time: datetime | None = None

    @abstractmethod
    async def scrape(
        self,
        keywords: list[str],
        filters: dict[str, Any] | None = None,
        max_pages: int = 5,
    ) -> ScrapeResult:
        """Scrape companies from the source.

        Args:
            keywords: Search keywords to use.
            filters: Optional filters (location, industry, etc).
            max_pages: Maximum pages to scrape.

        Returns:
            ScrapeResult with found companies.
        """
        pass

    @abstractmethod
    async def parse_listing(self, html: str) -> list[CompanyRaw]:
        """Parse a listing page HTML into company data.

        Args:
            html: Raw HTML of the listing page.

        Returns:
            List of parsed CompanyRaw objects.
        """
        pass

    async def _wait_for_rate_limit(self) -> None:
        """Wait if needed to respect rate limiting."""
        import asyncio

        if self._last_request_time is not None:
            elapsed = (datetime.now() - self._last_request_time).total_seconds()
            if elapsed < self.rate_limit_seconds:
                await asyncio.sleep(self.rate_limit_seconds - elapsed)

        self._last_request_time = datetime.now()

    def _extract_domain(self, url: str | None) -> str | None:
        """Extract domain from URL.

        Args:
            url: Full URL string.

        Returns:
            Domain without www prefix, or None if invalid.
        """
        if not url:
            return None

        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            # Remove www prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain.lower() if domain else None
        except Exception:
            return None

    def _normalize_employee_count(self, text: str | None) -> int | None:
        """Normalize employee count from various formats.

        Args:
            text: Employee count text like "50-100", "1000+", "~500".

        Returns:
            Estimated employee count as integer.
        """
        if not text:
            return None

        import re

        text = text.strip().lower()

        # First, normalize the text by removing commas (thousands separator)
        normalized = text.replace(",", "")

        # Handle ranges like "50-100" or "50 - 100"
        range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", normalized)
        if range_match:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            return (low + high) // 2

        # Handle "1000+" or "500+"
        plus_match = re.search(r"(\d+)\+", normalized)
        if plus_match:
            return int(plus_match.group(1))

        # Handle approximate like "~500" or "circa 500"
        approx_match = re.search(r"[~≈]?\s*(\d+)", normalized)
        if approx_match:
            return int(approx_match.group(1))

        # Try direct number
        try:
            return int(normalized.replace(".", ""))
        except ValueError:
            return None
