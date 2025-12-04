"""Scoring configuration for ICP (Ideal Customer Profile) scoring."""

from dataclasses import dataclass, field


@dataclass
class ScoringWeights:
    """Weights for different scoring components."""

    company_size: int = 30  # Max points for company size
    industry: int = 25  # Max points for industry match
    growth: int = 20  # Max points for growth signals
    activity: int = 15  # Max points for founder/decision maker activity
    location: int = 10  # Max points for location

    @property
    def total(self) -> int:
        """Get total maximum points."""
        return (
            self.company_size
            + self.industry
            + self.growth
            + self.activity
            + self.location
        )


@dataclass
class CompanySizeConfig:
    """Configuration for company size scoring."""

    # Employee count ranges and their scores (as percentage of max)
    # Format: (min_employees, max_employees, score_percentage)
    ranges: list[tuple[int, int | None, int]] = field(
        default_factory=lambda: [
            (1, 10, 60),  # Very small: 60% of max
            (11, 50, 100),  # Ideal size: 100% of max
            (51, 200, 80),  # Medium: 80% of max
            (201, 500, 50),  # Larger: 50% of max
            (501, None, 20),  # Enterprise: 20% of max
        ]
    )

    # Score when employee count is unknown
    unknown_score: int = 40


@dataclass
class IndustryConfig:
    """Configuration for industry scoring."""

    # Exact match industries (100% of max points)
    target_industries: set[str] = field(
        default_factory=lambda: {
            "software",
            "saas",
            "technology",
            "tech",
            "it",
            "fintech",
            "healthtech",
            "edtech",
            "e-commerce",
            "ecommerce",
            "digital",
            "ai",
            "artificial intelligence",
            "machine learning",
            "data",
            "analytics",
            "cloud",
            "cybersecurity",
            "iot",
            "blockchain",
        }
    )

    # Related industries (60% of max points)
    related_industries: set[str] = field(
        default_factory=lambda: {
            "consulting",
            "marketing",
            "media",
            "advertising",
            "telecommunications",
            "professional services",
            "business services",
            "finance",
            "banking",
            "insurance",
            "recruitment",
            "hr",
            "human resources",
        }
    )

    # Score percentages
    target_score: int = 100
    related_score: int = 60
    other_score: int = 30
    unknown_score: int = 40


@dataclass
class GrowthConfig:
    """Configuration for growth signals scoring."""

    # Points per open vacancy (capped)
    points_per_vacancy: int = 4
    max_vacancy_score: int = 80  # As percentage of max growth points

    # Bonus for having funding
    funding_bonus: int = 40  # As percentage of max growth points

    # Minimum vacancies to be considered "growing"
    min_vacancies_growing: int = 3


@dataclass
class ActivityConfig:
    """Configuration for activity/engagement scoring."""

    # Points per LinkedIn post in last 30 days
    points_per_post: int = 5
    max_post_score: int = 80  # As percentage of max activity points

    # Bonus for having LinkedIn URL
    linkedin_bonus: int = 20  # As percentage of max activity points


@dataclass
class LocationConfig:
    """Configuration for location scoring."""

    # Randstad (main economic region) - 100% of max
    randstad_cities: set[str] = field(
        default_factory=lambda: {
            "amsterdam",
            "rotterdam",
            "den haag",
            "the hague",
            "'s-gravenhage",
            "utrecht",
            "eindhoven",
            "almere",
            "haarlem",
            "haarlemmermeer",
            "zaanstad",
            "amersfoort",
            "arnhem",
            "nijmegen",
            "enschede",
            "tilburg",
            "breda",
            "groningen",
            "leiden",
            "delft",
            "dordrecht",
            "zoetermeer",
            "maastricht",
            "zwolle",
            "deventer",
            "apeldoorn",
            "hilversum",
            "amstelveen",
            "hoofddorp",
            "schiphol",
        }
    )

    # Score percentages
    randstad_score: int = 100
    netherlands_score: int = 70
    eu_score: int = 50
    other_score: int = 20

    # Netherlands indicators
    netherlands_indicators: set[str] = field(
        default_factory=lambda: {
            "nederland",
            "netherlands",
            "nl",
            "holland",
        }
    )


@dataclass
class ClassificationThresholds:
    """Thresholds for lead classification."""

    hot: int = 75  # Score >= 75 = HOT
    warm: int = 60  # Score >= 60 = WARM
    cool: int = 45  # Score >= 45 = COOL
    # Below cool = COLD

    qualified_threshold: int = 60  # Minimum score to be qualified


@dataclass
class ScoringConfig:
    """Complete scoring configuration."""

    weights: ScoringWeights = field(default_factory=ScoringWeights)
    company_size: CompanySizeConfig = field(default_factory=CompanySizeConfig)
    industry: IndustryConfig = field(default_factory=IndustryConfig)
    growth: GrowthConfig = field(default_factory=GrowthConfig)
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    thresholds: ClassificationThresholds = field(default_factory=ClassificationThresholds)

    def to_dict(self) -> dict:
        """Convert config to dictionary for storage/API."""
        return {
            "weights": {
                "company_size": self.weights.company_size,
                "industry": self.weights.industry,
                "growth": self.weights.growth,
                "activity": self.weights.activity,
                "location": self.weights.location,
                "total": self.weights.total,
            },
            "thresholds": {
                "hot": self.thresholds.hot,
                "warm": self.thresholds.warm,
                "cool": self.thresholds.cool,
                "qualified": self.thresholds.qualified_threshold,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScoringConfig":
        """Create config from dictionary."""
        config = cls()

        if "weights" in data:
            weights = data["weights"]
            config.weights = ScoringWeights(
                company_size=weights.get("company_size", 30),
                industry=weights.get("industry", 25),
                growth=weights.get("growth", 20),
                activity=weights.get("activity", 15),
                location=weights.get("location", 10),
            )

        if "thresholds" in data:
            thresholds = data["thresholds"]
            config.thresholds = ClassificationThresholds(
                hot=thresholds.get("hot", 75),
                warm=thresholds.get("warm", 60),
                cool=thresholds.get("cool", 45),
                qualified_threshold=thresholds.get("qualified", 60),
            )

        return config
