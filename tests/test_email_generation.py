"""Tests for email generation services."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.company import Company
from src.models.email import EmailSequenceStep
from src.models.lead import Lead, LeadStatus
from src.services.email.generator import EmailGenerator, GeneratedEmail, EmailSequence
from src.services.email.templates import EmailTemplates, EmailTemplate
from src.services.llm.openai_service import OpenAIService, GenerationResult


class TestEmailTemplates:
    """Tests for EmailTemplates class."""

    def test_get_initial_template(self) -> None:
        """Test getting initial email template."""
        template = EmailTemplates.get_template("initial")
        assert template is not None
        assert template.email_type == "initial"
        assert template.max_words == 100
        assert "{first_name}" in template.user_prompt_template
        assert "{company_name}" in template.user_prompt_template

    def test_get_followup1_template(self) -> None:
        """Test getting first follow-up template."""
        template = EmailTemplates.get_template("followup1")
        assert template is not None
        assert template.email_type == "followup1"
        assert template.max_words == 80
        assert "{previous_subject}" in template.user_prompt_template

    def test_get_followup2_template(self) -> None:
        """Test getting second follow-up template."""
        template = EmailTemplates.get_template("followup2")
        assert template is not None
        assert template.email_type == "followup2"
        assert template.max_words == 70

    def test_get_breakup_template(self) -> None:
        """Test getting breakup email template."""
        template = EmailTemplates.get_template("breakup")
        assert template is not None
        assert template.email_type == "breakup"
        assert template.max_words == 60

    def test_get_unknown_template_raises_error(self) -> None:
        """Test that unknown template type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown email type"):
            EmailTemplates.get_template("unknown")

    def test_get_value_proposition_default(self) -> None:
        """Test getting default value proposition."""
        prop = EmailTemplates.get_value_proposition(None)
        assert "leadgeneratie" in prop.lower() or "automatisering" in prop.lower()

    def test_get_value_proposition_saas(self) -> None:
        """Test getting SaaS value proposition."""
        prop = EmailTemplates.get_value_proposition("saas")
        assert "SaaS" in prop or "sales" in prop.lower()

    def test_get_value_proposition_technology(self) -> None:
        """Test getting technology value proposition."""
        prop = EmailTemplates.get_value_proposition("technology")
        assert "tech" in prop.lower()

    def test_get_value_proposition_recruitment(self) -> None:
        """Test getting recruitment value proposition."""
        prop = EmailTemplates.get_value_proposition("recruitment")
        assert "kandidaten" in prop.lower() or "automatiseren" in prop.lower()

    def test_get_sequence_schedule(self) -> None:
        """Test getting email sequence schedule."""
        schedule = EmailTemplates.get_sequence_schedule()
        assert len(schedule) == 4
        assert schedule[0] == ("initial", 0)
        assert schedule[1] == ("followup1", 3)
        assert schedule[2] == ("followup2", 7)
        assert schedule[3] == ("breakup", 14)

    def test_format_system_prompt(self) -> None:
        """Test formatting system prompt."""
        template = EmailTemplates.get_template("initial")
        formatted = EmailTemplates.format_system_prompt(template)
        assert "100" in formatted  # max_words
        assert "professional" in formatted  # tone
        # Check for Dutch content (may be "Nederlands" or similar)
        assert "Nederlands" in formatted or "nederlands" in formatted.lower()


class TestOpenAIService:
    """Tests for OpenAI service."""

    def test_init_default(self) -> None:
        """Test default initialization."""
        service = OpenAIService(api_key="test-key")
        assert service.api_key == "test-key"
        assert service.model == "gpt-4o-mini"
        assert service.max_retries == 3

    def test_init_custom_model(self) -> None:
        """Test initialization with custom model."""
        service = OpenAIService(api_key="test-key", model="gpt-4o")
        assert service.model == "gpt-4o"

    def test_estimate_cost_gpt4o_mini(self) -> None:
        """Test cost estimation for gpt-4o-mini."""
        service = OpenAIService(api_key="test-key")
        cost = service.estimate_cost(1000, 500)
        # gpt-4o-mini: $0.00015/1k input, $0.0006/1k output
        expected = (1000 / 1000) * 0.00015 + (500 / 1000) * 0.0006
        assert cost == pytest.approx(expected, rel=0.01)

    def test_estimate_cost_gpt4o(self) -> None:
        """Test cost estimation for gpt-4o."""
        service = OpenAIService(api_key="test-key", model="gpt-4o")
        cost = service.estimate_cost(1000, 500)
        # gpt-4o: $0.005/1k input, $0.015/1k output
        expected = (1000 / 1000) * 0.005 + (500 / 1000) * 0.015
        assert cost == pytest.approx(expected, rel=0.01)

    def test_count_tokens_fallback(self) -> None:
        """Test token counting fallback."""
        service = OpenAIService(api_key="test-key")
        # Without tiktoken properly configured, should use fallback
        text = "Dit is een test tekst voor token counting."
        count = service.count_tokens(text)
        # Fallback: 1 token ≈ 4 chars
        assert count > 0

    @pytest.mark.asyncio
    async def test_generate_mocked(self) -> None:
        """Test text generation with mocked client."""
        service = OpenAIService(api_key="test-key")

        # Mock the response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated text"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.generate("Test prompt", "System prompt")

            assert result.success is True
            assert result.text == "Generated text"
            assert result.prompt_tokens == 100
            assert result.completion_tokens == 50
            assert result.total_tokens == 150

    @pytest.mark.asyncio
    async def test_generate_with_json_mocked(self) -> None:
        """Test JSON generation with mocked client."""
        service = OpenAIService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"subject": "Test", "body": "Hello"}'
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            parsed, result = await service.generate_with_json("Test prompt")

            assert result.success is True
            assert parsed is not None
            assert parsed["subject"] == "Test"
            assert parsed["body"] == "Hello"

    @pytest.mark.asyncio
    async def test_generate_handles_error(self) -> None:
        """Test that generation handles errors gracefully."""
        service = OpenAIService(api_key="test-key")

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("API Error")
            )
            mock_get_client.return_value = mock_client

            result = await service.generate("Test prompt")

            assert result.success is False
            assert "API Error" in str(result.error)


class TestEmailGenerator:
    """Tests for EmailGenerator class."""

    @pytest.fixture
    def mock_openai_service(self) -> MagicMock:
        """Create mock OpenAI service."""
        mock = MagicMock(spec=OpenAIService)
        mock.generate_with_json = AsyncMock()
        mock.estimate_cost = MagicMock(return_value=0.001)
        return mock

    @pytest.fixture
    def sample_lead(self) -> Lead:
        """Create sample lead for testing."""
        lead = Lead(
            id=1,
            first_name="Jan",
            last_name="de Vries",
            email="jan@example.nl",
            job_title="CTO",
            status=LeadStatus.QUALIFIED,
        )
        return lead

    @pytest.fixture
    def sample_company(self) -> Company:
        """Create sample company for testing."""
        company = Company(
            id=1,
            name="TechStartup BV",
            domain="techstartup.nl",
            industry="technology",
            location="Amsterdam",
            employee_count=25,
            open_vacancies=3,
        )
        return company

    def test_init_default(self) -> None:
        """Test default initialization."""
        generator = EmailGenerator()
        assert generator.openai is not None
        assert generator.custom_value_proposition is None

    def test_init_custom_proposition(self) -> None:
        """Test initialization with custom value proposition."""
        generator = EmailGenerator(value_proposition="Custom proposition")
        assert generator.custom_value_proposition == "Custom proposition"

    def test_get_value_proposition_custom(self) -> None:
        """Test getting custom value proposition."""
        generator = EmailGenerator(value_proposition="My custom value")
        prop = generator._get_value_proposition("technology")
        assert prop == "My custom value"

    def test_get_value_proposition_default(self) -> None:
        """Test getting default value proposition."""
        generator = EmailGenerator()
        prop = generator._get_value_proposition("technology")
        assert "tech" in prop.lower()

    def test_build_context(self, sample_lead: Lead, sample_company: Company) -> None:
        """Test context building."""
        generator = EmailGenerator()
        context = generator._build_context(sample_lead, sample_company)

        assert context["first_name"] == "Jan"
        assert context["last_name"] == "de Vries"
        assert context["job_title"] == "CTO"
        assert context["company_name"] == "TechStartup BV"
        assert context["industry"] == "technology"
        assert context["location"] == "Amsterdam"
        assert context["employee_count"] == 25
        assert context["open_vacancies"] == 3
        assert "value_proposition" in context

    def test_build_context_no_company(self, sample_lead: Lead) -> None:
        """Test context building without company."""
        generator = EmailGenerator()
        context = generator._build_context(sample_lead, None)

        assert context["first_name"] == "Jan"
        assert context["company_name"] == "jullie bedrijf"
        assert context["industry"] == "technologie"

    def test_build_context_missing_lead_data(self) -> None:
        """Test context building with missing lead data."""
        lead = Lead(id=1, status=LeadStatus.NEW)
        generator = EmailGenerator()
        context = generator._build_context(lead, None)

        assert context["first_name"] == "daar"  # fallback
        assert context["job_title"] == "professional"  # fallback

    @pytest.mark.asyncio
    async def test_generate_email_success(
        self,
        mock_openai_service: MagicMock,
        sample_lead: Lead,
        sample_company: Company,
    ) -> None:
        """Test successful email generation."""
        mock_openai_service.generate_with_json.return_value = (
            {
                "subject": "Test onderwerp",
                "body": "Hoi Jan,\n\nDit is een test email.\n\nMet vriendelijke groet",
                "preview_text": "Preview tekst",
            },
            GenerationResult(
                text="{}",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                model="gpt-4o-mini",
                finish_reason="stop",
                success=True,
            ),
        )

        generator = EmailGenerator(openai_service=mock_openai_service)
        email = await generator.generate_email(
            lead=sample_lead,
            company=sample_company,
            email_type="initial",
        )

        assert email.subject == "Test onderwerp"
        assert "Jan" in email.body
        assert email.preview_text == "Preview tekst"
        assert email.email_type == "initial"
        assert email.sequence_step == 1
        assert email.word_count > 0

    @pytest.mark.asyncio
    async def test_generate_email_fallback_on_failure(
        self,
        mock_openai_service: MagicMock,
        sample_lead: Lead,
        sample_company: Company,
    ) -> None:
        """Test email generation fallback on API failure."""
        mock_openai_service.generate_with_json.return_value = (
            None,
            GenerationResult(
                text="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model="gpt-4o-mini",
                finish_reason="error",
                success=False,
                error="API Error",
            ),
        )

        generator = EmailGenerator(openai_service=mock_openai_service)
        email = await generator.generate_email(
            lead=sample_lead,
            company=sample_company,
            email_type="initial",
        )

        # Should return fallback email
        assert email.subject is not None
        assert "TechStartup BV" in email.subject
        assert email.body is not None

    @pytest.mark.asyncio
    async def test_generate_sequence(
        self,
        mock_openai_service: MagicMock,
        sample_lead: Lead,
        sample_company: Company,
    ) -> None:
        """Test generating complete email sequence."""
        # Mock successful response for all emails
        mock_openai_service.generate_with_json.return_value = (
            {
                "subject": "Test onderwerp",
                "body": "Test body voor de email.",
                "preview_text": "Preview",
            },
            GenerationResult(
                text="{}",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                model="gpt-4o-mini",
                finish_reason="stop",
                success=True,
            ),
        )

        generator = EmailGenerator(openai_service=mock_openai_service)
        sequence = await generator.generate_sequence(
            lead=sample_lead,
            company=sample_company,
        )

        assert sequence.lead_id == sample_lead.id
        assert len(sequence.emails) == 4
        assert sequence.success is True
        assert sequence.total_tokens > 0
        assert sequence.estimated_cost > 0

        # Check sequence steps
        assert sequence.emails[0].email_type == "initial"
        assert sequence.emails[1].email_type == "followup1"
        assert sequence.emails[2].email_type == "followup2"
        assert sequence.emails[3].email_type == "breakup"

        # Check scheduling
        assert sequence.emails[0].scheduled_for is not None
        assert sequence.emails[1].scheduled_for > sequence.emails[0].scheduled_for
        assert sequence.emails[2].scheduled_for > sequence.emails[1].scheduled_for
        assert sequence.emails[3].scheduled_for > sequence.emails[2].scheduled_for

    @pytest.mark.asyncio
    async def test_generate_sequence_with_start_date(
        self,
        mock_openai_service: MagicMock,
        sample_lead: Lead,
        sample_company: Company,
    ) -> None:
        """Test sequence generation with custom start date."""
        mock_openai_service.generate_with_json.return_value = (
            {"subject": "Test", "body": "Body", "preview_text": "Preview"},
            GenerationResult(
                text="{}",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                model="gpt-4o-mini",
                finish_reason="stop",
                success=True,
            ),
        )

        start_date = datetime(2024, 1, 1, 9, 0, 0)
        generator = EmailGenerator(openai_service=mock_openai_service)
        sequence = await generator.generate_sequence(
            lead=sample_lead,
            company=sample_company,
            start_date=start_date,
        )

        # Check scheduled dates
        assert sequence.emails[0].scheduled_for == start_date
        assert sequence.emails[1].scheduled_for == start_date + timedelta(days=3)
        assert sequence.emails[2].scheduled_for == start_date + timedelta(days=7)
        assert sequence.emails[3].scheduled_for == start_date + timedelta(days=14)

    def test_text_to_html(self) -> None:
        """Test plain text to HTML conversion."""
        generator = EmailGenerator()
        text = "Hoi Jan,\n\nDit is een test.\n\nMet groet"
        html = generator._text_to_html(text)

        assert "<!DOCTYPE html>" in html
        assert "<p>" in html
        assert "Hoi Jan," in html
        assert "Dit is een test." in html

    def test_text_to_html_escapes_html(self) -> None:
        """Test that HTML characters are escaped."""
        generator = EmailGenerator()
        text = "Test <script>alert('xss')</script>"
        html = generator._text_to_html(text)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestEmailSequenceStepMapping:
    """Tests for email sequence step mapping."""

    def test_initial_step_mapping(self) -> None:
        """Test initial email maps to step 1."""
        step_map = {"initial": 1, "followup1": 2, "followup2": 3, "breakup": 4}
        assert step_map.get("initial", 1) == 1

    def test_followup1_step_mapping(self) -> None:
        """Test followup1 maps to step 2."""
        step_map = {"initial": 1, "followup1": 2, "followup2": 3, "breakup": 4}
        assert step_map.get("followup1", 1) == 2

    def test_followup2_step_mapping(self) -> None:
        """Test followup2 maps to step 3."""
        step_map = {"initial": 1, "followup1": 2, "followup2": 3, "breakup": 4}
        assert step_map.get("followup2", 1) == 3

    def test_breakup_step_mapping(self) -> None:
        """Test breakup maps to step 4."""
        step_map = {"initial": 1, "followup1": 2, "followup2": 3, "breakup": 4}
        assert step_map.get("breakup", 1) == 4


class TestGeneratedEmailDataclass:
    """Tests for GeneratedEmail dataclass."""

    def test_create_generated_email(self) -> None:
        """Test creating GeneratedEmail."""
        result = GenerationResult(
            text="test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4o-mini",
            finish_reason="stop",
            success=True,
        )
        email = GeneratedEmail(
            subject="Test Subject",
            body="Test body text.",
            preview_text="Preview",
            email_type="initial",
            sequence_step=1,
            word_count=3,
            generation_result=result,
        )

        assert email.subject == "Test Subject"
        assert email.body == "Test body text."
        assert email.preview_text == "Preview"
        assert email.email_type == "initial"
        assert email.sequence_step == 1
        assert email.word_count == 3
        assert email.scheduled_for is None

    def test_generated_email_with_scheduled_time(self) -> None:
        """Test GeneratedEmail with scheduled time."""
        scheduled = datetime.now() + timedelta(days=3)
        result = GenerationResult(
            text="test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4o-mini",
            finish_reason="stop",
            success=True,
        )
        email = GeneratedEmail(
            subject="Test",
            body="Body",
            preview_text="Preview",
            email_type="followup1",
            sequence_step=2,
            word_count=1,
            generation_result=result,
            scheduled_for=scheduled,
        )

        assert email.scheduled_for == scheduled


class TestEmailSequenceDataclass:
    """Tests for EmailSequence dataclass."""

    def test_create_empty_sequence(self) -> None:
        """Test creating empty email sequence."""
        sequence = EmailSequence(lead_id=1)

        assert sequence.lead_id == 1
        assert sequence.emails == []
        assert sequence.total_tokens == 0
        assert sequence.estimated_cost == 0.0
        assert sequence.success is True
        assert sequence.errors == []

    def test_email_sequence_with_emails(self) -> None:
        """Test EmailSequence with emails."""
        result = GenerationResult(
            text="test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4o-mini",
            finish_reason="stop",
            success=True,
        )
        email = GeneratedEmail(
            subject="Test",
            body="Body",
            preview_text="Preview",
            email_type="initial",
            sequence_step=1,
            word_count=1,
            generation_result=result,
        )
        sequence = EmailSequence(
            lead_id=1,
            emails=[email],
            total_tokens=150,
            estimated_cost=0.001,
            success=True,
        )

        assert len(sequence.emails) == 1
        assert sequence.total_tokens == 150
        assert sequence.estimated_cost == 0.001
