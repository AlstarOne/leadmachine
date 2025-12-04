"""Deduplication service for merging scraped company data."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.services.scrapers.base import CompanyRaw


@dataclass
class DeduplicationResult:
    """Result of deduplication process."""

    new_companies: list[CompanyRaw]
    existing_companies: list[tuple[CompanyRaw, Company]]  # (new_data, existing_record)
    merged_count: int
    skipped_count: int


class DeduplicationService:
    """Service for deduplicating and merging company data."""

    # Similarity threshold for fuzzy name matching (0-1)
    NAME_SIMILARITY_THRESHOLD = 0.85

    # Common company suffixes to normalize
    COMPANY_SUFFIXES = [
        r"\s+b\.?v\.?$",
        r"\s+n\.?v\.?$",
        r"\s+v\.?o\.?f\.?$",
        r"\s+gmbh$",
        r"\s+ltd\.?$",
        r"\s+limited$",
        r"\s+inc\.?$",
        r"\s+corp\.?$",
        r"\s+corporation$",
        r"\s+llc$",
        r"\s+holding$",
        r"\s+group$",
    ]

    def __init__(self, db: AsyncSession) -> None:
        """Initialize deduplication service.

        Args:
            db: Database session.
        """
        self.db = db

    async def deduplicate(
        self,
        companies: list[CompanyRaw],
        update_existing: bool = True,
    ) -> DeduplicationResult:
        """Deduplicate and merge company data.

        Args:
            companies: List of scraped companies to process.
            update_existing: Whether to update existing records with new data.

        Returns:
            DeduplicationResult with categorized companies.
        """
        new_companies: list[CompanyRaw] = []
        existing_companies: list[tuple[CompanyRaw, Company]] = []
        merged_count = 0
        skipped_count = 0

        # First, dedupe within the input list
        unique_companies = self._dedupe_input_list(companies)
        skipped_count = len(companies) - len(unique_companies)

        for company in unique_companies:
            # Try to find existing company by domain first (most reliable)
            existing = await self._find_by_domain(company)

            if not existing:
                # Try fuzzy name matching
                existing = await self._find_by_name(company)

            if existing:
                existing_companies.append((company, existing))
                if update_existing:
                    await self._merge_company_data(existing, company)
                    merged_count += 1
            else:
                new_companies.append(company)

        return DeduplicationResult(
            new_companies=new_companies,
            existing_companies=existing_companies,
            merged_count=merged_count,
            skipped_count=skipped_count,
        )

    def _dedupe_input_list(self, companies: list[CompanyRaw]) -> list[CompanyRaw]:
        """Remove duplicates within the input list.

        Args:
            companies: Input company list.

        Returns:
            Deduplicated list.
        """
        seen_domains: set[str] = set()
        seen_names: set[str] = set()
        unique: list[CompanyRaw] = []

        for company in companies:
            # Check domain first
            if company.domain:
                normalized_domain = self._normalize_domain(company.domain)
                if normalized_domain in seen_domains:
                    continue
                seen_domains.add(normalized_domain)

            # Check normalized name
            normalized_name = self._normalize_company_name(company.name)
            if normalized_name in seen_names:
                # Same name but different domain - might be same company
                # Use fuzzy matching to decide
                is_duplicate = False
                for seen_name in seen_names:
                    if self._names_are_similar(normalized_name, seen_name):
                        is_duplicate = True
                        break
                if is_duplicate:
                    continue

            seen_names.add(normalized_name)
            unique.append(company)

        return unique

    async def _find_by_domain(self, company: CompanyRaw) -> Company | None:
        """Find existing company by domain.

        Args:
            company: Company to match.

        Returns:
            Existing Company or None.
        """
        if not company.domain:
            return None

        normalized = self._normalize_domain(company.domain)

        result = await self.db.execute(
            select(Company).where(Company.domain == normalized)
        )
        return result.scalar_one_or_none()

    async def _find_by_name(self, company: CompanyRaw) -> Company | None:
        """Find existing company by fuzzy name match.

        Args:
            company: Company to match.

        Returns:
            Existing Company or None.
        """
        normalized_name = self._normalize_company_name(company.name)

        # Get potential matches (companies without domains or with similar-length names)
        result = await self.db.execute(
            select(Company).where(
                Company.domain.is_(None)  # Only match nameless-domain companies
            )
        )
        candidates = result.scalars().all()

        best_match: Company | None = None
        best_score = 0.0

        for candidate in candidates:
            candidate_name = self._normalize_company_name(candidate.name)
            score = self._calculate_name_similarity(normalized_name, candidate_name)

            if score > best_score and score >= self.NAME_SIMILARITY_THRESHOLD:
                best_score = score
                best_match = candidate

        return best_match

    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain for comparison.

        Args:
            domain: Domain string.

        Returns:
            Normalized domain.
        """
        domain = domain.lower().strip()

        # Remove protocol if present
        if "://" in domain:
            parsed = urlparse(domain)
            domain = parsed.netloc or parsed.path

        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]

        # Remove trailing slashes/paths
        domain = domain.split("/")[0]

        return domain

    def _normalize_company_name(self, name: str) -> str:
        """Normalize company name for comparison.

        Args:
            name: Company name.

        Returns:
            Normalized name.
        """
        name = name.lower().strip()

        # Remove common suffixes
        for suffix_pattern in self.COMPANY_SUFFIXES:
            name = re.sub(suffix_pattern, "", name, flags=re.IGNORECASE)

        # Remove punctuation except hyphens
        name = re.sub(r"[^\w\s-]", "", name)

        # Normalize whitespace
        name = re.sub(r"\s+", " ", name).strip()

        return name

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two company names.

        Args:
            name1: First name.
            name2: Second name.

        Returns:
            Similarity score between 0 and 1.
        """
        # Use sequence matcher for fuzzy matching
        return SequenceMatcher(None, name1, name2).ratio()

    def _names_are_similar(self, name1: str, name2: str) -> bool:
        """Check if two names are similar enough to be duplicates.

        Args:
            name1: First normalized name.
            name2: Second normalized name.

        Returns:
            True if names are similar.
        """
        return self._calculate_name_similarity(name1, name2) >= self.NAME_SIMILARITY_THRESHOLD

    async def _merge_company_data(
        self, existing: Company, new_data: CompanyRaw
    ) -> None:
        """Merge new data into existing company record.

        Updates empty fields and adds new information without overwriting
        existing data unless it's clearly better.

        Args:
            existing: Existing company record.
            new_data: New scraped data.
        """
        # Update domain if not set
        if not existing.domain and new_data.domain:
            existing.domain = self._normalize_domain(new_data.domain)

        # Update website if not set
        if not existing.website_url and new_data.website_url:
            existing.website_url = new_data.website_url

        # Update LinkedIn if not set
        if not existing.linkedin_url and new_data.linkedin_url:
            existing.linkedin_url = new_data.linkedin_url

        # Update employee count if new data has it
        if new_data.employee_count and (
            not existing.employee_count or new_data.employee_count > existing.employee_count
        ):
            existing.employee_count = new_data.employee_count

        # Update vacancy count (additive)
        if new_data.open_vacancies > 0:
            existing.open_vacancies = max(
                existing.open_vacancies, new_data.open_vacancies
            )

        # Update location if not set
        if not existing.location and new_data.location:
            existing.location = new_data.location

        # Update industry if not set
        if not existing.industry and new_data.industry:
            existing.industry = new_data.industry

        # Update description if longer
        if new_data.description and (
            not existing.description
            or len(new_data.description) > len(existing.description or "")
        ):
            existing.description = new_data.description

        # Update funding info
        if new_data.has_funding and not existing.has_funding:
            existing.has_funding = True
            if new_data.funding_amount:
                existing.funding_amount = new_data.funding_amount

        # Merge raw data
        if new_data.raw_data:
            if existing.raw_data is None:
                existing.raw_data = {}
            # Add source-specific data
            source_key = new_data.source.value.lower()
            existing.raw_data[source_key] = new_data.raw_data

        self.db.add(existing)

    async def find_or_create_company(self, company_raw: CompanyRaw) -> tuple[Company, bool]:
        """Find existing company or create new one.

        Args:
            company_raw: Raw company data.

        Returns:
            Tuple of (Company, is_new).
        """
        # Try to find existing
        existing = await self._find_by_domain(company_raw)
        if not existing:
            existing = await self._find_by_name(company_raw)

        if existing:
            await self._merge_company_data(existing, company_raw)
            await self.db.commit()
            return existing, False

        # Create new company
        from src.models.company import CompanySource, CompanyStatus

        new_company = Company(
            name=company_raw.name,
            domain=self._normalize_domain(company_raw.domain) if company_raw.domain else None,
            website_url=company_raw.website_url,
            linkedin_url=company_raw.linkedin_url,
            industry=company_raw.industry,
            employee_count=company_raw.employee_count,
            open_vacancies=company_raw.open_vacancies,
            location=company_raw.location,
            description=company_raw.description,
            has_funding=company_raw.has_funding,
            funding_amount=company_raw.funding_amount,
            source=CompanySource(company_raw.source.value),
            source_url=company_raw.source_url,
            status=CompanyStatus.NEW,
            raw_data=company_raw.raw_data,
        )

        self.db.add(new_company)
        await self.db.commit()
        await self.db.refresh(new_company)

        return new_company, True
