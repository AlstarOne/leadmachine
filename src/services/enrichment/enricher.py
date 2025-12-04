"""Enrichment orchestrator that coordinates all enrichment services."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company, CompanyStatus
from src.models.lead import Lead, LeadStatus
from src.services.enrichment.domain import DomainService
from src.services.enrichment.email_finder import EmailFinder
from src.services.enrichment.website import Person, WebsiteScraper


@dataclass
class EnrichmentResult:
    """Result of enriching a company."""

    company_id: int
    success: bool
    leads_created: int = 0
    leads_updated: int = 0
    domain_verified: bool = False
    website_found: bool = False
    team_members_found: int = 0
    emails_found: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class LeadEnrichmentResult:
    """Result of enriching a lead."""

    lead_id: int
    success: bool
    email_found: bool = False
    email: str | None = None
    email_confidence: int = 0
    linkedin_found: bool = False
    linkedin_url: str | None = None
    errors: list[str] = field(default_factory=list)


class EnrichmentOrchestrator:
    """Orchestrates the enrichment process for companies and leads."""

    def __init__(
        self,
        db: AsyncSession,
        domain_service: DomainService | None = None,
        website_scraper: WebsiteScraper | None = None,
        email_finder: EmailFinder | None = None,
    ) -> None:
        """Initialize enrichment orchestrator.

        Args:
            db: Database session.
            domain_service: Domain service instance.
            website_scraper: Website scraper instance.
            email_finder: Email finder instance.
        """
        self.db = db
        self.domain_service = domain_service or DomainService()
        self.website_scraper = website_scraper or WebsiteScraper()
        self.email_finder = email_finder or EmailFinder(self.domain_service)

    async def close(self) -> None:
        """Close all services."""
        await self.website_scraper.close()

    async def enrich_company(
        self,
        company: Company,
        find_team: bool = True,
        verify_domain: bool = True,
    ) -> EnrichmentResult:
        """Enrich a single company with contact information.

        Args:
            company: Company to enrich.
            find_team: Whether to find team members.
            verify_domain: Whether to verify domain.

        Returns:
            EnrichmentResult with enrichment data.
        """
        start_time = datetime.now()
        result = EnrichmentResult(company_id=company.id, success=False)

        try:
            # Update status to enriching
            company.status = CompanyStatus.ENRICHING
            self.db.add(company)
            await self.db.commit()

            # Step 1: Verify/find domain
            domain = company.domain
            if not domain and company.website_url:
                domain = self.domain_service.extract_from_url(company.website_url)
                if domain:
                    company.domain = domain

            if not domain and company.name:
                # Try to guess domain from company name
                guesses = self.domain_service.guess_company_domain(company.name)
                for guess in guesses[:3]:  # Try top 3 guesses
                    domain_info = await self.domain_service.get_domain_info(guess)
                    if domain_info.has_website or domain_info.has_mx:
                        domain = guess
                        company.domain = domain
                        company.website_url = f"https://{domain}"
                        break

            if not domain:
                result.errors.append("Could not find or verify domain")
                company.status = CompanyStatus.NO_CONTACT
                self.db.add(company)
                await self.db.commit()
                return result

            # Step 2: Verify domain
            if verify_domain:
                domain_info = await self.domain_service.get_domain_info(domain)
                result.domain_verified = domain_info.has_mx
                result.website_found = domain_info.has_website

                if domain_info.redirects_to:
                    # Update to final URL
                    new_domain = self.domain_service.extract_from_url(domain_info.redirects_to)
                    if new_domain and new_domain != domain:
                        company.domain = new_domain
                        domain = new_domain

                if not domain_info.has_mx:
                    result.errors.append("Domain has no MX records")

            # Step 3: Find team members
            leads_created = 0
            leads_updated = 0

            if find_team:
                team_members = await self.website_scraper.find_team_members(domain)
                result.team_members_found = len(team_members)

                # Also get contact info
                contact_info = await self.website_scraper.find_contact_info(domain)

                # Detect email pattern from found emails
                known_pattern = self.email_finder.detect_pattern(
                    contact_info.emails, domain
                )

                # Update company LinkedIn if found
                if contact_info.social_links.get("linkedin") and not company.linkedin_url:
                    company.linkedin_url = contact_info.social_links["linkedin"]

                # Create or update leads for team members
                for person in team_members[:10]:  # Limit to 10 leads per company
                    lead_result = await self._create_or_update_lead(
                        company=company,
                        person=person,
                        known_pattern=known_pattern,
                    )

                    if lead_result.email_found:
                        result.emails_found += 1

                    if lead_result.success:
                        if lead_result.lead_id > 0:
                            leads_created += 1
                        else:
                            leads_updated += 1

            result.leads_created = leads_created
            result.leads_updated = leads_updated

            # Update company status
            if result.emails_found > 0:
                company.status = CompanyStatus.ENRICHED
                company.enriched_at = datetime.now()
            else:
                company.status = CompanyStatus.NO_CONTACT

            self.db.add(company)
            await self.db.commit()

            result.success = True

        except Exception as e:
            result.errors.append(f"Enrichment error: {e!s}")
            company.status = CompanyStatus.NEW  # Reset to retry later
            self.db.add(company)
            await self.db.commit()

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result

    async def enrich_lead(
        self,
        lead: Lead,
        company: Company | None = None,
    ) -> LeadEnrichmentResult:
        """Enrich a single lead with email and LinkedIn.

        Args:
            lead: Lead to enrich.
            company: Company for the lead (optional, loaded if not provided).

        Returns:
            LeadEnrichmentResult with enrichment data.
        """
        result = LeadEnrichmentResult(lead_id=lead.id, success=False)

        try:
            # Get company if not provided
            if not company:
                company = await self.db.get(Company, lead.company_id)
                if not company:
                    result.errors.append("Company not found")
                    return result

            domain = company.domain
            if not domain:
                result.errors.append("Company has no domain")
                return result

            # Find email
            if not lead.email and lead.first_name and lead.last_name:
                email_result = await self.email_finder.find_email(
                    first_name=lead.first_name,
                    last_name=lead.last_name,
                    domain=domain,
                )

                if email_result.best_email:
                    lead.email = email_result.best_email
                    lead.email_confidence = email_result.best_confidence
                    result.email_found = True
                    result.email = email_result.best_email
                    result.email_confidence = email_result.best_confidence

            # Update lead status
            if lead.email:
                lead.status = LeadStatus.ENRICHED
            else:
                lead.status = LeadStatus.NO_EMAIL

            self.db.add(lead)
            await self.db.commit()

            result.success = True
            result.linkedin_found = lead.linkedin_url is not None
            result.linkedin_url = lead.linkedin_url

        except Exception as e:
            result.errors.append(f"Lead enrichment error: {e!s}")

        return result

    async def _create_or_update_lead(
        self,
        company: Company,
        person: Person,
        known_pattern: str | None,
    ) -> LeadEnrichmentResult:
        """Create or update a lead from a found person.

        Args:
            company: Company the person belongs to.
            person: Person data from website scraping.
            known_pattern: Known email pattern for the company.

        Returns:
            LeadEnrichmentResult.
        """
        result = LeadEnrichmentResult(lead_id=0, success=False)

        try:
            # Check if lead already exists by email or name
            existing_lead = None

            if person.email:
                from sqlalchemy import select

                stmt = select(Lead).where(Lead.email == person.email.lower())
                db_result = await self.db.execute(stmt)
                existing_lead = db_result.scalar_one_or_none()

            if existing_lead:
                # Update existing lead
                result.lead_id = -existing_lead.id  # Negative to indicate update

                if person.job_title and not existing_lead.job_title:
                    existing_lead.job_title = person.job_title
                if person.linkedin_url and not existing_lead.linkedin_url:
                    existing_lead.linkedin_url = person.linkedin_url

                self.db.add(existing_lead)
                await self.db.flush()  # Flush changes without committing
                result.success = True
                result.email_found = existing_lead.email is not None
                result.email = existing_lead.email

            else:
                # Create new lead
                new_lead = Lead(
                    company_id=company.id,
                    first_name=person.first_name,
                    last_name=person.last_name,
                    email=person.email.lower() if person.email else None,
                    job_title=person.job_title,
                    linkedin_url=person.linkedin_url,
                    status=LeadStatus.NEW,
                )

                # Try to find email if not provided
                if not new_lead.email and person.first_name and person.last_name and company.domain:
                    email_result = await self.email_finder.find_email(
                        first_name=person.first_name,
                        last_name=person.last_name,
                        domain=company.domain,
                        known_pattern=known_pattern,
                    )

                    if email_result.best_email:
                        new_lead.email = email_result.best_email
                        new_lead.email_confidence = email_result.best_confidence

                # Set status based on email
                if new_lead.email:
                    new_lead.status = LeadStatus.ENRICHED
                    result.email_found = True
                    result.email = new_lead.email
                    result.email_confidence = new_lead.email_confidence
                else:
                    new_lead.status = LeadStatus.NO_EMAIL

                self.db.add(new_lead)
                await self.db.flush()  # Get ID without committing
                result.lead_id = new_lead.id
                result.success = True

            result.linkedin_found = person.linkedin_url is not None
            result.linkedin_url = person.linkedin_url

        except Exception as e:
            result.errors.append(f"Lead creation error: {e!s}")

        return result

    async def enrich_batch(
        self,
        companies: list[Company],
        max_concurrent: int = 3,
    ) -> list[EnrichmentResult]:
        """Enrich multiple companies with rate limiting.

        Args:
            companies: Companies to enrich.
            max_concurrent: Maximum concurrent enrichments.

        Returns:
            List of EnrichmentResult.
        """
        results: list[EnrichmentResult] = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def enrich_with_limit(company: Company) -> EnrichmentResult:
            async with semaphore:
                return await self.enrich_company(company)

        tasks = [enrich_with_limit(company) for company in companies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        final_results: list[EnrichmentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    EnrichmentResult(
                        company_id=companies[i].id,
                        success=False,
                        errors=[str(result)],
                    )
                )
            else:
                final_results.append(result)

        return final_results
