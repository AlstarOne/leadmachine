"""Tests for ICP scoring services."""

import pytest

from src.models.lead import LeadClassification
from src.services.scoring import ICPScorer, ScoringConfig
from src.services.scoring.config import (
    ClassificationThresholds,
    CompanySizeConfig,
    GrowthConfig,
    IndustryConfig,
    LocationConfig,
    ScoringWeights,
)


class TestScoringConfig:
    """Tests for ScoringConfig."""

    def test_default_weights(self) -> None:
        """Test default scoring weights."""
        config = ScoringConfig()
        assert config.weights.company_size == 30
        assert config.weights.industry == 25
        assert config.weights.growth == 20
        assert config.weights.activity == 15
        assert config.weights.location == 10
        assert config.weights.total == 100

    def test_default_thresholds(self) -> None:
        """Test default classification thresholds."""
        config = ScoringConfig()
        assert config.thresholds.hot == 75
        assert config.thresholds.warm == 60
        assert config.thresholds.cool == 45
        assert config.thresholds.qualified_threshold == 60

    def test_config_to_dict(self) -> None:
        """Test converting config to dictionary."""
        config = ScoringConfig()
        data = config.to_dict()

        assert "weights" in data
        assert "thresholds" in data
        assert data["weights"]["total"] == 100
        assert data["thresholds"]["qualified"] == 60

    def test_config_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "weights": {
                "company_size": 40,
                "industry": 20,
                "growth": 15,
                "activity": 15,
                "location": 10,
            },
            "thresholds": {
                "hot": 80,
                "warm": 65,
                "cool": 50,
                "qualified": 65,
            },
        }
        config = ScoringConfig.from_dict(data)

        assert config.weights.company_size == 40
        assert config.weights.industry == 20
        assert config.thresholds.hot == 80
        assert config.thresholds.qualified_threshold == 65

    def test_custom_weights(self) -> None:
        """Test custom scoring weights."""
        weights = ScoringWeights(
            company_size=40,
            industry=30,
            growth=10,
            activity=10,
            location=10,
        )
        assert weights.total == 100

    def test_target_industries(self) -> None:
        """Test target industries in default config."""
        config = ScoringConfig()
        assert "software" in config.industry.target_industries
        assert "saas" in config.industry.target_industries
        assert "technology" in config.industry.target_industries
        assert "fintech" in config.industry.target_industries

    def test_randstad_cities(self) -> None:
        """Test Randstad cities in default config."""
        config = ScoringConfig()
        assert "amsterdam" in config.location.randstad_cities
        assert "rotterdam" in config.location.randstad_cities
        assert "utrecht" in config.location.randstad_cities
        assert "eindhoven" in config.location.randstad_cities


class TestICPScorer:
    """Tests for ICPScorer."""

    @pytest.fixture
    def scorer(self) -> ICPScorer:
        """Create ICPScorer instance."""
        return ICPScorer()

    # Company size scoring tests
    def test_company_size_ideal(self, scorer: ICPScorer) -> None:
        """Test scoring for ideal company size (11-50 employees)."""
        score, reason = scorer.score_company_size(30)
        assert score == 30  # 100% of max 30
        assert "ideal size" in reason.lower()

    def test_company_size_small(self, scorer: ICPScorer) -> None:
        """Test scoring for small company (1-10 employees)."""
        score, reason = scorer.score_company_size(5)
        assert score == 18  # 60% of max 30
        assert "5 employees" in reason

    def test_company_size_medium(self, scorer: ICPScorer) -> None:
        """Test scoring for medium company (51-200 employees)."""
        score, reason = scorer.score_company_size(100)
        assert score == 24  # 80% of max 30
        assert "100 employees" in reason

    def test_company_size_large(self, scorer: ICPScorer) -> None:
        """Test scoring for larger company (201-500 employees)."""
        score, reason = scorer.score_company_size(300)
        assert score == 15  # 50% of max 30
        assert "300 employees" in reason

    def test_company_size_enterprise(self, scorer: ICPScorer) -> None:
        """Test scoring for enterprise (501+ employees)."""
        score, reason = scorer.score_company_size(1000)
        assert score == 6  # 20% of max 30
        assert "enterprise" in reason.lower()

    def test_company_size_unknown(self, scorer: ICPScorer) -> None:
        """Test scoring when employee count is unknown."""
        score, reason = scorer.score_company_size(None)
        assert score == 12  # 40% of max 30
        assert "unknown" in reason.lower()

    # Industry scoring tests
    def test_industry_target(self, scorer: ICPScorer) -> None:
        """Test scoring for target industry."""
        score, reason = scorer.score_industry("SaaS")
        assert score == 25  # 100% of max 25
        assert "target industry" in reason.lower()

    def test_industry_technology(self, scorer: ICPScorer) -> None:
        """Test scoring for technology industry."""
        score, reason = scorer.score_industry("Technology")
        assert score == 25  # 100% of max 25

    def test_industry_related(self, scorer: ICPScorer) -> None:
        """Test scoring for related industry."""
        score, reason = scorer.score_industry("Marketing")
        assert score == 15  # 60% of max 25
        assert "related industry" in reason.lower()

    def test_industry_other(self, scorer: ICPScorer) -> None:
        """Test scoring for other industry."""
        score, reason = scorer.score_industry("Manufacturing")
        assert score == 7  # 30% of max 25 = 7.5 -> 7
        assert "other industry" in reason.lower()

    def test_industry_unknown(self, scorer: ICPScorer) -> None:
        """Test scoring when industry is unknown."""
        score, reason = scorer.score_industry(None)
        assert score == 10  # 40% of max 25
        assert "unknown" in reason.lower()

    def test_industry_case_insensitive(self, scorer: ICPScorer) -> None:
        """Test industry matching is case insensitive."""
        score1, _ = scorer.score_industry("SAAS")
        score2, _ = scorer.score_industry("saas")
        score3, _ = scorer.score_industry("SaaS")
        assert score1 == score2 == score3 == 25

    # Growth scoring tests
    def test_growth_high_vacancies(self, scorer: ICPScorer) -> None:
        """Test scoring with many open vacancies."""
        score, reason = scorer.score_growth(10, has_funding=False)
        assert score > 0
        assert "vacancies" in reason.lower()

    def test_growth_with_funding(self, scorer: ICPScorer) -> None:
        """Test scoring with funding."""
        score_with, _ = scorer.score_growth(0, has_funding=True)
        score_without, _ = scorer.score_growth(0, has_funding=False)
        assert score_with > score_without

    def test_growth_vacancies_and_funding(self, scorer: ICPScorer) -> None:
        """Test scoring with both vacancies and funding."""
        score, reason = scorer.score_growth(5, has_funding=True)
        assert score > 0
        assert "vacancies" in reason.lower()
        assert "funding" in reason.lower()

    def test_growth_no_signals(self, scorer: ICPScorer) -> None:
        """Test scoring with no growth signals."""
        score, reason = scorer.score_growth(0, has_funding=False)
        assert score == 0
        assert "no open vacancies" in reason.lower()

    def test_growth_vacancies_capped(self, scorer: ICPScorer) -> None:
        """Test that vacancy score is capped."""
        # With 100 vacancies, score should still be capped
        score1, _ = scorer.score_growth(100, has_funding=False)
        score2, _ = scorer.score_growth(20, has_funding=False)
        # Both should be at or near cap
        assert score1 == score2  # Both capped at max vacancy score

    # Activity scoring tests
    def test_activity_linkedin_presence(self, scorer: ICPScorer) -> None:
        """Test scoring with LinkedIn presence."""
        score_with, _ = scorer.score_activity(0, has_linkedin=True)
        score_without, _ = scorer.score_activity(0, has_linkedin=False)
        assert score_with > score_without

    def test_activity_posts(self, scorer: ICPScorer) -> None:
        """Test scoring with LinkedIn posts."""
        score, reason = scorer.score_activity(5, has_linkedin=True)
        assert score > 0
        assert "posts" in reason.lower()

    def test_activity_no_data(self, scorer: ICPScorer) -> None:
        """Test scoring with no activity data."""
        score, reason = scorer.score_activity(0, has_linkedin=False)
        assert score == 0

    def test_activity_posts_capped(self, scorer: ICPScorer) -> None:
        """Test that post score is capped."""
        score1, _ = scorer.score_activity(100, has_linkedin=True)
        score2, _ = scorer.score_activity(20, has_linkedin=True)
        # Both should be at or near cap
        assert score1 == score2  # Both capped

    # Location scoring tests
    def test_location_randstad(self, scorer: ICPScorer) -> None:
        """Test scoring for Randstad location."""
        score, reason = scorer.score_location("Amsterdam")
        assert score == 10  # 100% of max 10
        assert "randstad" in reason.lower()

    def test_location_rotterdam(self, scorer: ICPScorer) -> None:
        """Test scoring for Rotterdam."""
        score, _ = scorer.score_location("Rotterdam, Netherlands")
        assert score == 10

    def test_location_netherlands(self, scorer: ICPScorer) -> None:
        """Test scoring for Netherlands outside Randstad."""
        score, reason = scorer.score_location("Some small town, Netherlands")
        assert score == 7  # 70% of max 10
        assert "netherlands" in reason.lower()

    def test_location_eu(self, scorer: ICPScorer) -> None:
        """Test scoring for EU location."""
        score, reason = scorer.score_location("Berlin, Germany")
        assert score == 5  # 50% of max 10
        assert "eu" in reason.lower()

    def test_location_other(self, scorer: ICPScorer) -> None:
        """Test scoring for other location."""
        score, reason = scorer.score_location("New York, USA")
        assert score == 2  # 20% of max 10
        assert "other" in reason.lower()

    def test_location_unknown(self, scorer: ICPScorer) -> None:
        """Test scoring when location is unknown."""
        score, reason = scorer.score_location(None)
        assert score == 2  # 20% of max 10
        assert "unknown" in reason.lower()

    def test_location_case_insensitive(self, scorer: ICPScorer) -> None:
        """Test location matching is case insensitive."""
        score1, _ = scorer.score_location("AMSTERDAM")
        score2, _ = scorer.score_location("amsterdam")
        score3, _ = scorer.score_location("Amsterdam")
        assert score1 == score2 == score3 == 10

    # Classification tests
    def test_classify_hot(self, scorer: ICPScorer) -> None:
        """Test classification for HOT score."""
        assert scorer.classify(75) == LeadClassification.HOT
        assert scorer.classify(100) == LeadClassification.HOT
        assert scorer.classify(85) == LeadClassification.HOT

    def test_classify_warm(self, scorer: ICPScorer) -> None:
        """Test classification for WARM score."""
        assert scorer.classify(60) == LeadClassification.WARM
        assert scorer.classify(74) == LeadClassification.WARM
        assert scorer.classify(65) == LeadClassification.WARM

    def test_classify_cool(self, scorer: ICPScorer) -> None:
        """Test classification for COOL score."""
        assert scorer.classify(45) == LeadClassification.COOL
        assert scorer.classify(59) == LeadClassification.COOL
        assert scorer.classify(50) == LeadClassification.COOL

    def test_classify_cold(self, scorer: ICPScorer) -> None:
        """Test classification for COLD score."""
        assert scorer.classify(0) == LeadClassification.COLD
        assert scorer.classify(44) == LeadClassification.COLD
        assert scorer.classify(30) == LeadClassification.COLD

    # Qualification tests
    def test_is_qualified_above_threshold(self, scorer: ICPScorer) -> None:
        """Test qualification above threshold."""
        assert scorer.is_qualified(60) is True
        assert scorer.is_qualified(75) is True
        assert scorer.is_qualified(100) is True

    def test_is_qualified_below_threshold(self, scorer: ICPScorer) -> None:
        """Test qualification below threshold."""
        assert scorer.is_qualified(59) is False
        assert scorer.is_qualified(0) is False
        assert scorer.is_qualified(45) is False

    def test_is_qualified_at_threshold(self, scorer: ICPScorer) -> None:
        """Test qualification at exact threshold."""
        assert scorer.is_qualified(60) is True

    # Config tests
    def test_get_config(self, scorer: ICPScorer) -> None:
        """Test getting configuration."""
        config = scorer.get_config()
        assert "weights" in config
        assert "thresholds" in config

    def test_update_config(self, scorer: ICPScorer) -> None:
        """Test updating configuration."""
        scorer.update_config({
            "weights": {"company_size": 40},
            "thresholds": {"hot": 80},
        })

        config = scorer.get_config()
        assert config["weights"]["company_size"] == 40
        assert config["thresholds"]["hot"] == 80


class TestScoreBreakdown:
    """Tests for ScoreBreakdown."""

    def test_breakdown_total(self) -> None:
        """Test breakdown total calculation."""
        from src.services.scoring.icp_scorer import ScoreBreakdown

        breakdown = ScoreBreakdown(
            company_size=30,
            industry=25,
            growth=20,
            activity=15,
            location=10,
        )
        assert breakdown.total == 100

    def test_breakdown_to_dict(self) -> None:
        """Test breakdown to dictionary conversion."""
        from src.services.scoring.icp_scorer import ScoreBreakdown

        breakdown = ScoreBreakdown(
            company_size=30,
            industry=25,
            growth=20,
            activity=15,
            location=10,
            company_size_reason="Test reason",
        )
        data = breakdown.to_dict()

        assert data["company_size"]["score"] == 30
        assert data["company_size"]["reason"] == "Test reason"
        assert data["total"] == 100


class TestScoringResult:
    """Tests for ScoringResult."""

    def test_result_to_dict(self) -> None:
        """Test result to dictionary conversion."""
        from src.services.scoring.icp_scorer import ScoreBreakdown, ScoringResult

        breakdown = ScoreBreakdown(company_size=30)
        result = ScoringResult(
            lead_id=1,
            score=75,
            breakdown=breakdown,
            classification=LeadClassification.HOT,
            qualified=True,
        )
        data = result.to_dict()

        assert data["lead_id"] == 1
        assert data["score"] == 75
        assert data["classification"] == "HOT"
        assert data["qualified"] is True
        assert "breakdown" in data

    def test_result_with_errors(self) -> None:
        """Test result with errors."""
        from src.services.scoring.icp_scorer import ScoreBreakdown, ScoringResult

        breakdown = ScoreBreakdown()
        result = ScoringResult(
            lead_id=1,
            score=0,
            breakdown=breakdown,
            classification=LeadClassification.COLD,
            qualified=False,
            errors=["Test error"],
        )
        data = result.to_dict()

        assert len(data["errors"]) == 1
        assert data["errors"][0] == "Test error"
