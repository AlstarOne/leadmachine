"""Tests for CRUD operations."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud import company, email, event, lead, scrape_job, user
from src.models import CompanySource, CompanyStatus, EventType, LeadStatus
from src.schemas import (
    CompanyCreate,
    EmailCreate,
    EventCreate,
    LeadCreate,
    ScrapeJobCreate,
    UserCreate,
)
from src.models.email import EmailSequenceStep


@pytest_asyncio.fixture
async def test_company(db_session: AsyncSession):
    """Create a test company."""
    company_data = CompanyCreate(
        name="Test Company",
        domain="testcompany.com",
        source=CompanySource.INDEED,
        industry="Technology",
    )
    return await company.create(db_session, obj_in=company_data)


@pytest_asyncio.fixture
async def test_lead(db_session: AsyncSession, test_company):
    """Create a test lead."""
    lead_data = LeadCreate(
        company_id=test_company.id,
        first_name="John",
        last_name="Doe",
        email="john.doe@testcompany.com",
        job_title="CTO",
    )
    return await lead.create(db_session, obj_in=lead_data)


@pytest_asyncio.fixture
async def test_email(db_session: AsyncSession, test_lead):
    """Create a test email."""
    email_data = EmailCreate(
        lead_id=test_lead.id,
        subject="Test Subject",
        body_text="Test body content",
        sequence_step=EmailSequenceStep.INITIAL,
    )
    return await email.create(db_session, obj_in=email_data)


class TestCompanyCRUD:
    """Tests for Company CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_company(self, db_session: AsyncSession) -> None:
        """Test creating a company."""
        company_data = CompanyCreate(
            name="New Company",
            domain="newcompany.com",
            source=CompanySource.KVK,
        )
        result = await company.create(db_session, obj_in=company_data)

        assert result.id is not None
        assert result.name == "New Company"
        assert result.domain == "newcompany.com"
        assert result.source == CompanySource.KVK
        assert result.status == CompanyStatus.NEW

    @pytest.mark.asyncio
    async def test_get_company(self, db_session: AsyncSession, test_company) -> None:
        """Test getting a company by ID."""
        result = await company.get(db_session, id=test_company.id)

        assert result is not None
        assert result.id == test_company.id
        assert result.name == test_company.name

    @pytest.mark.asyncio
    async def test_get_company_by_domain(
        self, db_session: AsyncSession, test_company
    ) -> None:
        """Test getting a company by domain."""
        result = await company.get_by_domain(db_session, domain=test_company.domain)

        assert result is not None
        assert result.domain == test_company.domain

    @pytest.mark.asyncio
    async def test_get_or_create_existing(
        self, db_session: AsyncSession, test_company
    ) -> None:
        """Test get_or_create with existing company."""
        company_data = CompanyCreate(
            name="Different Name",
            domain=test_company.domain,
            source=CompanySource.LINKEDIN,
        )
        result, created = await company.get_or_create_by_domain(
            db_session, obj_in=company_data
        )

        assert created is False
        assert result.id == test_company.id
        assert result.name == test_company.name  # Original name preserved

    @pytest.mark.asyncio
    async def test_get_or_create_new(self, db_session: AsyncSession) -> None:
        """Test get_or_create with new company."""
        company_data = CompanyCreate(
            name="Brand New Company",
            domain="brandnew.com",
            source=CompanySource.TECHLEAP,
        )
        result, created = await company.get_or_create_by_domain(
            db_session, obj_in=company_data
        )

        assert created is True
        assert result.name == "Brand New Company"

    @pytest.mark.asyncio
    async def test_update_status(
        self, db_session: AsyncSession, test_company
    ) -> None:
        """Test updating company status."""
        result = await company.update_status(
            db_session,
            db_obj=test_company,
            new_status=CompanyStatus.ENRICHING,
        )

        assert result.status == CompanyStatus.ENRICHING

    @pytest.mark.asyncio
    async def test_delete_company(
        self, db_session: AsyncSession, test_company
    ) -> None:
        """Test deleting a company."""
        company_id = test_company.id
        await company.delete(db_session, id=company_id)

        result = await company.get(db_session, id=company_id)
        assert result is None


class TestLeadCRUD:
    """Tests for Lead CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_lead(
        self, db_session: AsyncSession, test_company
    ) -> None:
        """Test creating a lead."""
        lead_data = LeadCreate(
            company_id=test_company.id,
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )
        result = await lead.create(db_session, obj_in=lead_data)

        assert result.id is not None
        assert result.first_name == "Jane"
        assert result.company_id == test_company.id

    @pytest.mark.asyncio
    async def test_get_by_email(
        self, db_session: AsyncSession, test_lead
    ) -> None:
        """Test getting lead by email."""
        result = await lead.get_by_email(db_session, email=test_lead.email)

        assert result is not None
        assert result.email == test_lead.email

    @pytest.mark.asyncio
    async def test_get_by_company(
        self, db_session: AsyncSession, test_company, test_lead
    ) -> None:
        """Test getting leads by company."""
        results = await lead.get_by_company(
            db_session, company_id=test_company.id
        )

        assert len(results) >= 1
        assert any(l.id == test_lead.id for l in results)

    @pytest.mark.asyncio
    async def test_update_score(
        self, db_session: AsyncSession, test_lead
    ) -> None:
        """Test updating lead score."""
        result = await lead.update_score(
            db_session,
            db_obj=test_lead,
            score=75,
            breakdown={"size": 20, "industry": 25, "growth": 20, "activity": 10},
        )

        assert result.icp_score == 75
        assert result.classification.value == "HOT"
        assert result.status == LeadStatus.QUALIFIED  # Score >= 60


class TestEmailCRUD:
    """Tests for Email CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_email(
        self, db_session: AsyncSession, test_lead
    ) -> None:
        """Test creating an email."""
        email_data = EmailCreate(
            lead_id=test_lead.id,
            subject="Hello",
            body_text="Body content",
        )
        result = await email.create(db_session, obj_in=email_data)

        assert result.id is not None
        assert result.subject == "Hello"
        assert result.tracking_id is not None

    @pytest.mark.asyncio
    async def test_get_by_tracking_id(
        self, db_session: AsyncSession, test_email
    ) -> None:
        """Test getting email by tracking ID."""
        result = await email.get_by_tracking_id(
            db_session, tracking_id=test_email.tracking_id
        )

        assert result is not None
        assert result.id == test_email.id

    @pytest.mark.asyncio
    async def test_record_open(
        self, db_session: AsyncSession, test_email
    ) -> None:
        """Test recording email open."""
        from src.models.email import EmailStatus
        test_email.status = EmailStatus.SENT
        db_session.add(test_email)
        await db_session.commit()

        result = await email.record_open(db_session, db_obj=test_email)

        assert result.open_count == 1
        assert result.opened_at is not None


class TestEventCRUD:
    """Tests for Event CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_open_event(
        self, db_session: AsyncSession, test_email
    ) -> None:
        """Test creating an open event."""
        result = await event.create_open_event(
            db_session,
            email_id=test_email.id,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert result.id is not None
        assert result.event_type == EventType.OPEN
        assert result.email_id == test_email.id

    @pytest.mark.asyncio
    async def test_create_click_event(
        self, db_session: AsyncSession, test_email
    ) -> None:
        """Test creating a click event."""
        result = await event.create_click_event(
            db_session,
            email_id=test_email.id,
            clicked_url="https://example.com",
        )

        assert result.event_type == EventType.CLICK
        assert result.clicked_url == "https://example.com"

    @pytest.mark.asyncio
    async def test_count_by_type(
        self, db_session: AsyncSession, test_email
    ) -> None:
        """Test counting events by type."""
        # Create some events
        await event.create_open_event(db_session, email_id=test_email.id)
        await event.create_open_event(db_session, email_id=test_email.id)
        await event.create_click_event(
            db_session, email_id=test_email.id, clicked_url="https://test.com"
        )

        counts = await event.count_by_type(db_session, email_id=test_email.id)

        assert counts.get(EventType.OPEN, 0) >= 2
        assert counts.get(EventType.CLICK, 0) >= 1


class TestScrapeJobCRUD:
    """Tests for ScrapeJob CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_scrape_job(self, db_session: AsyncSession) -> None:
        """Test creating a scrape job."""
        job_data = ScrapeJobCreate(
            source=CompanySource.INDEED,
            keywords=["python", "developer"],
        )
        result = await scrape_job.create(db_session, obj_in=job_data)

        assert result.id is not None
        assert result.source == CompanySource.INDEED
        assert result.keywords == ["python", "developer"]

    @pytest.mark.asyncio
    async def test_start_and_complete_job(self, db_session: AsyncSession) -> None:
        """Test starting and completing a job."""
        job_data = ScrapeJobCreate(source=CompanySource.KVK)
        job_obj = await scrape_job.create(db_session, obj_in=job_data)

        # Start job
        started = await scrape_job.start_job(
            db_session, db_obj=job_obj, celery_task_id="task-123"
        )
        assert started.started_at is not None
        assert started.celery_task_id == "task-123"

        # Complete job
        completed = await scrape_job.complete_job(
            db_session,
            db_obj=started,
            results_count=50,
            new_count=40,
            duplicate_count=10,
        )
        assert completed.results_count == 50
        assert completed.completed_at is not None


class TestUserCRUD:
    """Tests for User CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session: AsyncSession) -> None:
        """Test creating a user with hashed password."""
        user_data = UserCreate(
            username="newuser",
            email="newuser@example.com",
            password="securepassword123",
        )
        result = await user.create(db_session, obj_in=user_data)

        assert result.id is not None
        assert result.username == "newuser"
        assert result.hashed_password != "securepassword123"  # Password is hashed

    @pytest.mark.asyncio
    async def test_authenticate_valid(self, db_session: AsyncSession) -> None:
        """Test authentication with valid credentials."""
        user_data = UserCreate(
            username="authuser",
            email="authuser@example.com",
            password="correctpassword",
        )
        created_user = await user.create(db_session, obj_in=user_data)

        result = await user.authenticate(
            db_session,
            username="authuser",
            password="correctpassword",
        )

        assert result is not None
        assert result.id == created_user.id

    @pytest.mark.asyncio
    async def test_authenticate_invalid_password(
        self, db_session: AsyncSession
    ) -> None:
        """Test authentication with wrong password."""
        user_data = UserCreate(
            username="authuser2",
            email="authuser2@example.com",
            password="correctpassword",
        )
        await user.create(db_session, obj_in=user_data)

        result = await user.authenticate(
            db_session,
            username="authuser2",
            password="wrongpassword",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_username(self, db_session: AsyncSession) -> None:
        """Test getting user by username."""
        user_data = UserCreate(
            username="findme",
            email="findme@example.com",
            password="password123",
        )
        created = await user.create(db_session, obj_in=user_data)

        result = await user.get_by_username(db_session, username="findme")

        assert result is not None
        assert result.id == created.id
