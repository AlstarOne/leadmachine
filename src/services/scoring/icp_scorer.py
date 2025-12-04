"""ICP (Ideal Customer Profile) scorer for leads."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.models.lead import Lead, LeadClassification, LeadStatus
from src.services.scoring.config import ScoringConfig


@dataclass
class ScoreBreakdown:
    """Breakdown of individual scoring components."""

    company_size: int = 0
    industry: int = 0
    growth: int = 0
    activity: int = 0
    location: int = 0

    company_size_reason: str = ""
    industry_reason: str = ""
    growth_reason: str = ""
    activity_reason: str = ""
    location_reason: str = ""

    @property
    def total(self) -> int:
        """Calculate total score."""
        return (
            self.company_size
            + self.industry
            + self.growth
            + self.activity
            + self.location
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "company_size": {
                "score": self.company_size,
                "reason": self.company_size_reason,
            },
            "industry": {
                "score": self.industry,
                "reason": self.industry_reason,
            },
            "growth": {
                "score": self.growth,
                "reason": self.growth_reason,
            },
            "activity": {
                "score": self.activity,
                "reason": self.activity_reason,
            },
            "location": {
                "score": self.location,
                "reason": self.location_reason,
            },
            "total": self.total,
        }


@dataclass
class ScoringResult:
    """Result of scoring a lead."""

    lead_id: int
    score: int
    breakdown: ScoreBreakdown
    classification: LeadClassification
    qualified: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "lead_id": self.lead_id,
            "score": self.score,
            "breakdown": self.breakdown.to_dict(),
            "classification": self.classification.value,
            "qualified": self.qualified,
            "errors": self.errors,
        }


class ICPScorer:
    """Scorer for evaluating leads against Ideal Customer Profile criteria."""

    def __init__(self, config: ScoringConfig | None = None) -> None:
        """Initialize ICP scorer.

        Args:
            config: Scoring configuration. Uses defaults if not provided.
        """
        self.config = config or ScoringConfig()

    def score_company_size(self, employee_count: int | None) -> tuple[int, str]:
        """Score based on company size.

        Args:
            employee_count: Number of employees.

        Returns:
            Tuple of (score, reason).
        """
        max_points = self.config.weights.company_size
        cfg = self.config.company_size

        if employee_count is None:
            score = (cfg.unknown_score * max_points) // 100
            return score, "Employee count unknown"

        for min_emp, max_emp, percentage in cfg.ranges:
            if max_emp is None:
                if employee_count >= min_emp:
                    score = (percentage * max_points) // 100
                    return score, f"{employee_count}+ employees (enterprise)"
            elif min_emp <= employee_count <= max_emp:
                score = (percentage * max_points) // 100
                if min_emp == 11 and max_emp == 50:
                    return score, f"{employee_count} employees (ideal size)"
                return score, f"{employee_count} employees"

        # Fallback (shouldn't happen with proper ranges)
        score = (cfg.unknown_score * max_points) // 100
        return score, f"{employee_count} employees"

    def score_industry(self, industry: str | None) -> tuple[int, str]:
        """Score based on industry match.

        Args:
            industry: Industry name/category.

        Returns:
            Tuple of (score, reason).
        """
        max_points = self.config.weights.industry
        cfg = self.config.industry

        if not industry:
            score = (cfg.unknown_score * max_points) // 100
            return score, "Industry unknown"

        industry_lower = industry.lower().strip()

        # Check for target industries
        for target in cfg.target_industries:
            if target in industry_lower or industry_lower in target:
                score = (cfg.target_score * max_points) // 100
                return score, f"Target industry: {industry}"

        # Check for related industries
        for related in cfg.related_industries:
            if related in industry_lower or industry_lower in related:
                score = (cfg.related_score * max_points) // 100
                return score, f"Related industry: {industry}"

        # Other industry
        score = (cfg.other_score * max_points) // 100
        return score, f"Other industry: {industry}"

    def score_growth(
        self,
        open_vacancies: int,
        has_funding: bool,
    ) -> tuple[int, str]:
        """Score based on growth signals.

        Args:
            open_vacancies: Number of open job positions.
            has_funding: Whether company has received funding.

        Returns:
            Tuple of (score, reason).
        """
        max_points = self.config.weights.growth
        cfg = self.config.growth

        reasons = []
        total_percentage = 0

        # Score vacancies
        if open_vacancies > 0:
            vacancy_points = min(
                open_vacancies * cfg.points_per_vacancy,
                cfg.max_vacancy_score,
            )
            total_percentage += vacancy_points
            reasons.append(f"{open_vacancies} open vacancies")
        else:
            reasons.append("No open vacancies")

        # Score funding
        if has_funding:
            total_percentage += cfg.funding_bonus
            reasons.append("Has funding")

        score = (total_percentage * max_points) // 100
        return score, "; ".join(reasons)

    def score_activity(
        self,
        linkedin_posts_30d: int,
        has_linkedin: bool,
    ) -> tuple[int, str]:
        """Score based on activity/engagement.

        Args:
            linkedin_posts_30d: Number of LinkedIn posts in last 30 days.
            has_linkedin: Whether lead has a LinkedIn profile URL.

        Returns:
            Tuple of (score, reason).
        """
        max_points = self.config.weights.activity
        cfg = self.config.activity

        reasons = []
        total_percentage = 0

        # Score LinkedIn presence
        if has_linkedin:
            total_percentage += cfg.linkedin_bonus
            reasons.append("Has LinkedIn profile")

        # Score posts
        if linkedin_posts_30d > 0:
            post_points = min(
                linkedin_posts_30d * cfg.points_per_post,
                cfg.max_post_score,
            )
            total_percentage += post_points
            reasons.append(f"{linkedin_posts_30d} LinkedIn posts (30d)")
        else:
            reasons.append("No recent LinkedIn activity")

        score = (total_percentage * max_points) // 100
        reason = "; ".join(reasons) if reasons else "No activity data"
        return score, reason

    def score_location(self, location: str | None) -> tuple[int, str]:
        """Score based on location.

        Args:
            location: Company location string.

        Returns:
            Tuple of (score, reason).
        """
        max_points = self.config.weights.location
        cfg = self.config.location

        if not location:
            score = (cfg.other_score * max_points) // 100
            return score, "Location unknown"

        location_lower = location.lower().strip()

        # Check for Randstad cities
        for city in cfg.randstad_cities:
            if city in location_lower:
                score = (cfg.randstad_score * max_points) // 100
                return score, f"Randstad location: {location}"

        # Check for Netherlands
        for indicator in cfg.netherlands_indicators:
            if indicator in location_lower:
                score = (cfg.netherlands_score * max_points) // 100
                return score, f"Netherlands: {location}"

        # Check for EU (simplified)
        eu_countries = {
            "germany", "deutschland", "france", "belgium", "belgie",
            "luxembourg", "austria", "ireland", "spain", "portugal",
            "italy", "poland", "sweden", "denmark", "finland", "norway",
        }
        for country in eu_countries:
            if country in location_lower:
                score = (cfg.eu_score * max_points) // 100
                return score, f"EU location: {location}"

        # Other location
        score = (cfg.other_score * max_points) // 100
        return score, f"Other location: {location}"

    def classify(self, score: int) -> LeadClassification:
        """Classify a lead based on score.

        Args:
            score: Total ICP score.

        Returns:
            LeadClassification enum value.
        """
        thresholds = self.config.thresholds

        if score >= thresholds.hot:
            return LeadClassification.HOT
        elif score >= thresholds.warm:
            return LeadClassification.WARM
        elif score >= thresholds.cool:
            return LeadClassification.COOL
        else:
            return LeadClassification.COLD

    def is_qualified(self, score: int) -> bool:
        """Check if score qualifies the lead.

        Args:
            score: Total ICP score.

        Returns:
            True if qualified.
        """
        return score >= self.config.thresholds.qualified_threshold

    def calculate_score(
        self,
        lead: Lead,
        company: Company | None = None,
    ) -> ScoringResult:
        """Calculate ICP score for a lead.

        Args:
            lead: Lead to score.
            company: Company associated with the lead.

        Returns:
            ScoringResult with score breakdown.
        """
        breakdown = ScoreBreakdown()
        errors: list[str] = []

        # Score company size
        employee_count = company.employee_count if company else None
        breakdown.company_size, breakdown.company_size_reason = self.score_company_size(
            employee_count
        )

        # Score industry
        industry = company.industry if company else None
        breakdown.industry, breakdown.industry_reason = self.score_industry(industry)

        # Score growth
        open_vacancies = company.open_vacancies if company else 0
        has_funding = company.has_funding if company else False
        breakdown.growth, breakdown.growth_reason = self.score_growth(
            open_vacancies, has_funding
        )

        # Score activity
        breakdown.activity, breakdown.activity_reason = self.score_activity(
            lead.linkedin_posts_30d or 0,
            lead.linkedin_url is not None,
        )

        # Score location
        location = company.location if company else None
        breakdown.location, breakdown.location_reason = self.score_location(location)

        # Calculate total and classify
        total_score = breakdown.total
        classification = self.classify(total_score)
        qualified = self.is_qualified(total_score)

        return ScoringResult(
            lead_id=lead.id,
            score=total_score,
            breakdown=breakdown,
            classification=classification,
            qualified=qualified,
            errors=errors,
        )

    async def score_lead(
        self,
        db: AsyncSession,
        lead: Lead,
        company: Company | None = None,
        save: bool = True,
    ) -> ScoringResult:
        """Score a lead and optionally save to database.

        Args:
            db: Database session.
            lead: Lead to score.
            company: Company (loaded if not provided).
            save: Whether to save score to database.

        Returns:
            ScoringResult.
        """
        # Load company if not provided
        if company is None and lead.company_id:
            company = await db.get(Company, lead.company_id)

        # Calculate score
        result = self.calculate_score(lead, company)

        # Save to database
        if save:
            lead.icp_score = result.score
            lead.score_breakdown = result.breakdown.to_dict()
            lead.classification = result.classification
            lead.scored_at = datetime.now()

            # Update status based on qualification
            if result.qualified:
                if lead.status in (LeadStatus.NEW, LeadStatus.ENRICHED):
                    lead.status = LeadStatus.QUALIFIED
            else:
                if lead.status in (LeadStatus.NEW, LeadStatus.ENRICHED, LeadStatus.QUALIFIED):
                    lead.status = LeadStatus.DISQUALIFIED

            db.add(lead)
            await db.commit()
            await db.refresh(lead)

        return result

    async def score_batch(
        self,
        db: AsyncSession,
        leads: list[Lead],
        max_concurrent: int = 10,
    ) -> list[ScoringResult]:
        """Score multiple leads.

        Args:
            db: Database session.
            leads: Leads to score.
            max_concurrent: Not used (scoring is CPU-bound, not I/O).

        Returns:
            List of ScoringResult.
        """
        results: list[ScoringResult] = []

        # Pre-load all companies to avoid N+1 queries
        company_ids = {lead.company_id for lead in leads if lead.company_id}
        companies_map: dict[int, Company] = {}

        if company_ids:
            stmt = select(Company).where(Company.id.in_(company_ids))
            db_result = await db.execute(stmt)
            for company in db_result.scalars():
                companies_map[company.id] = company

        # Score each lead
        for lead in leads:
            company = companies_map.get(lead.company_id) if lead.company_id else None
            result = await self.score_lead(db, lead, company, save=True)
            results.append(result)

        return results

    async def get_qualified_leads(
        self,
        db: AsyncSession,
        min_score: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        """Get qualified leads.

        Args:
            db: Database session.
            min_score: Minimum score (defaults to threshold).
            limit: Maximum leads to return.
            offset: Pagination offset.

        Returns:
            Tuple of (leads, total_count).
        """
        min_score = min_score or self.config.thresholds.qualified_threshold

        # Count query
        from sqlalchemy import func

        count_stmt = (
            select(func.count(Lead.id))
            .where(Lead.icp_score >= min_score)
            .where(Lead.status.in_([LeadStatus.QUALIFIED, LeadStatus.ENRICHED]))
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Data query
        stmt = (
            select(Lead)
            .where(Lead.icp_score >= min_score)
            .where(Lead.status.in_([LeadStatus.QUALIFIED, LeadStatus.ENRICHED]))
            .order_by(Lead.icp_score.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        leads = list(result.scalars())

        return leads, total

    async def get_leads_to_score(
        self,
        db: AsyncSession,
        limit: int = 100,
    ) -> list[Lead]:
        """Get leads that need scoring.

        Args:
            db: Database session.
            limit: Maximum leads to return.

        Returns:
            List of leads to score.
        """
        stmt = (
            select(Lead)
            .where(Lead.status.in_([LeadStatus.NEW, LeadStatus.ENRICHED]))
            .where(Lead.icp_score.is_(None))
            .order_by(Lead.created_at)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    def get_config(self) -> dict:
        """Get current scoring configuration.

        Returns:
            Configuration dictionary.
        """
        return self.config.to_dict()

    def update_config(self, config_data: dict) -> None:
        """Update scoring configuration.

        Args:
            config_data: New configuration values.
        """
        self.config = ScoringConfig.from_dict(config_data)
