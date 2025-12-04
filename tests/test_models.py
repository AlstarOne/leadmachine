"""Tests for database models."""

import pytest

from src.models import (
    Company,
    CompanySource,
    CompanyStatus,
    Email,
    EmailSequenceStep,
    EmailStatus,
    Event,
    EventType,
    Lead,
    LeadClassification,
    LeadStatus,
    ScrapeJob,
    ScrapeJobStatus,
    User,
)


class TestCompanyModel:
    """Tests for Company model."""

    def test_company_creation(self) -> None:
        """Test company instance creation."""
        company = Company(
            name="Test Company",
            domain="test.com",
            source=CompanySource.INDEED,
            status=CompanyStatus.NEW,  # Explicitly set for testing
        )
        assert company.name == "Test Company"
        assert company.domain == "test.com"
        assert company.source == CompanySource.INDEED
        assert company.status == CompanyStatus.NEW

    def test_company_status_transitions(self) -> None:
        """Test valid status transitions."""
        company = Company(name="Test", source=CompanySource.INDEED, status=CompanyStatus.NEW)

        # NEW -> ENRICHING is valid
        assert company.can_transition_to(CompanyStatus.ENRICHING) is True

        # NEW -> ENRICHED is not valid (must go through ENRICHING)
        assert company.can_transition_to(CompanyStatus.ENRICHED) is False

        # Change status and test again
        company.status = CompanyStatus.ENRICHING
        assert company.can_transition_to(CompanyStatus.ENRICHED) is True
        assert company.can_transition_to(CompanyStatus.NO_CONTACT) is True

    def test_company_repr(self) -> None:
        """Test company string representation."""
        company = Company(
            name="Test Company",
            source=CompanySource.INDEED,
        )
        company.id = 1
        assert "Test Company" in repr(company)
        assert "1" in repr(company)


class TestLeadModel:
    """Tests for Lead model."""

    def test_lead_creation(self) -> None:
        """Test lead instance creation."""
        lead = Lead(
            company_id=1,
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            status=LeadStatus.NEW,
            classification=LeadClassification.UNSCORED,
        )
        assert lead.first_name == "John"
        assert lead.last_name == "Doe"
        assert lead.email == "john@example.com"
        assert lead.status == LeadStatus.NEW
        assert lead.classification == LeadClassification.UNSCORED

    def test_lead_full_name(self) -> None:
        """Test lead full name property."""
        lead = Lead(company_id=1, first_name="John", last_name="Doe")
        assert lead.full_name == "John Doe"

        lead_no_last = Lead(company_id=1, first_name="John")
        assert lead_no_last.full_name == "John"

        lead_no_first = Lead(company_id=1, last_name="Doe")
        assert lead_no_first.full_name == "Doe"

    def test_lead_classification_mapping(self) -> None:
        """Test score to classification mapping based on ranges."""
        # HOT >= 75
        assert LeadClassification.HOT.value == "HOT"
        # WARM 60-74
        assert LeadClassification.WARM.value == "WARM"
        # COOL 45-59
        assert LeadClassification.COOL.value == "COOL"
        # COLD < 45
        assert LeadClassification.COLD.value == "COLD"

    def test_lead_status_transitions(self) -> None:
        """Test valid status transitions."""
        lead = Lead(company_id=1, status=LeadStatus.NEW)

        # NEW -> ENRICHED is valid
        assert lead.can_transition_to(LeadStatus.ENRICHED) is True

        # NEW -> SEQUENCED is not valid
        assert lead.can_transition_to(LeadStatus.SEQUENCED) is False


class TestEmailModel:
    """Tests for Email model."""

    def test_email_creation(self) -> None:
        """Test email instance creation."""
        email = Email(
            lead_id=1,
            subject="Test Subject",
            body_text="Test body",
            status=EmailStatus.DRAFT,
            sequence_step=EmailSequenceStep.INITIAL,
            open_count=0,
            click_count=0,
        )
        assert email.subject == "Test Subject"
        assert email.body_text == "Test body"
        assert email.status == EmailStatus.DRAFT
        assert email.sequence_step == EmailSequenceStep.INITIAL
        assert email.open_count == 0
        assert email.click_count == 0

    def test_email_status_transitions(self) -> None:
        """Test valid status transitions."""
        email = Email(lead_id=1, subject="Test", body_text="Body", status=EmailStatus.DRAFT)

        # DRAFT -> PENDING is valid
        assert email.can_transition_to(EmailStatus.PENDING) is True

        # DRAFT -> SENT is not valid
        assert email.can_transition_to(EmailStatus.SENT) is False

    def test_email_record_open(self) -> None:
        """Test recording email open."""
        email = Email(
            lead_id=1, subject="Test", body_text="Body",
            status=EmailStatus.SENT,
            open_count=0,
            click_count=0,
        )

        email.record_open()

        assert email.open_count == 1
        assert email.opened_at is not None
        assert email.status == EmailStatus.OPENED

        # Second open should increment count but not change timestamp
        first_open = email.opened_at
        email.record_open()
        assert email.open_count == 2
        assert email.opened_at == first_open

    def test_email_record_click(self) -> None:
        """Test recording link click."""
        email = Email(
            lead_id=1, subject="Test", body_text="Body",
            status=EmailStatus.OPENED,
            open_count=0,
            click_count=0,
        )

        email.record_click()

        assert email.click_count == 1
        assert email.clicked_at is not None
        assert email.status == EmailStatus.CLICKED

    def test_email_record_reply(self) -> None:
        """Test recording reply."""
        email = Email(lead_id=1, subject="Test", body_text="Body", status=EmailStatus.SENT)

        email.record_reply()

        assert email.replied_at is not None
        assert email.status == EmailStatus.REPLIED


class TestEventModel:
    """Tests for Event model."""

    def test_event_creation(self) -> None:
        """Test event instance creation."""
        event = Event(
            email_id=1,
            event_type=EventType.OPEN,
            ip_address="192.168.1.1",
        )
        assert event.email_id == 1
        assert event.event_type == EventType.OPEN
        assert event.ip_address == "192.168.1.1"

    def test_create_open_event(self) -> None:
        """Test factory method for open event."""
        event = Event.create_open_event(
            email_id=1,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        assert event.event_type == EventType.OPEN
        assert event.ip_address == "192.168.1.1"
        assert event.user_agent == "Mozilla/5.0"

    def test_create_click_event(self) -> None:
        """Test factory method for click event."""
        event = Event.create_click_event(
            email_id=1,
            clicked_url="https://example.com",
            ip_address="192.168.1.1",
        )
        assert event.event_type == EventType.CLICK
        assert event.clicked_url == "https://example.com"


class TestScrapeJobModel:
    """Tests for ScrapeJob model."""

    def test_scrape_job_creation(self) -> None:
        """Test scrape job instance creation."""
        job = ScrapeJob(
            source=CompanySource.INDEED,
            keywords=["python", "developer"],
            status=ScrapeJobStatus.PENDING,
            results_count=0,
            new_companies_count=0,
            duplicate_count=0,
        )
        assert job.source == CompanySource.INDEED
        assert job.keywords == ["python", "developer"]
        assert job.status == ScrapeJobStatus.PENDING
        assert job.results_count == 0

    def test_scrape_job_start(self) -> None:
        """Test starting a scrape job."""
        job = ScrapeJob(source=CompanySource.INDEED, status=ScrapeJobStatus.PENDING)
        job.start()

        assert job.status == ScrapeJobStatus.RUNNING
        assert job.started_at is not None

    def test_scrape_job_complete(self) -> None:
        """Test completing a scrape job."""
        job = ScrapeJob(source=CompanySource.INDEED, status=ScrapeJobStatus.PENDING)
        job.start()
        job.complete(results_count=100, new_count=80, duplicate_count=20)

        assert job.status == ScrapeJobStatus.COMPLETED
        assert job.completed_at is not None
        assert job.results_count == 100
        assert job.new_companies_count == 80
        assert job.duplicate_count == 20

    def test_scrape_job_fail(self) -> None:
        """Test failing a scrape job."""
        job = ScrapeJob(source=CompanySource.INDEED, status=ScrapeJobStatus.PENDING)
        job.start()
        job.fail("Connection timeout")

        assert job.status == ScrapeJobStatus.FAILED
        assert job.error_message == "Connection timeout"

    def test_scrape_job_duration(self) -> None:
        """Test duration calculation."""
        job = ScrapeJob(source=CompanySource.INDEED, status=ScrapeJobStatus.PENDING)

        # No duration before start
        assert job.duration_seconds is None

        job.start()
        # Duration should be calculated from started_at
        assert job.duration_seconds is not None
        assert job.duration_seconds >= 0


class TestUserModel:
    """Tests for User model."""

    def test_user_creation(self) -> None:
        """Test user instance creation."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashedpassword",
            is_active=True,
            is_superuser=False,
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_superuser is False

    def test_user_repr(self) -> None:
        """Test user string representation."""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hash",
        )
        user.id = 1
        assert "testuser" in repr(user)
