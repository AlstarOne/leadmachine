"""Scraper services for various data sources."""

from src.services.scrapers.base import BaseScraper, CompanyRaw, ScrapeResult
from src.services.scrapers.indeed import IndeedScraper
from src.services.scrapers.kvk import KvKScraper
from src.services.scrapers.linkedin import LinkedInScraper
from src.services.scrapers.techleap import TechleapScraper

__all__ = [
    "BaseScraper",
    "CompanyRaw",
    "ScrapeResult",
    "IndeedScraper",
    "KvKScraper",
    "LinkedInScraper",
    "TechleapScraper",
]
