"""Pydantic schemas for LeadMachine."""

from src.schemas.company import (
    CompanyBase,
    CompanyCreate,
    CompanyList,
    CompanyRead,
    CompanyUpdate,
)
from src.schemas.email import (
    EmailBase,
    EmailCreate,
    EmailList,
    EmailRead,
    EmailSequence,
    EmailUpdate,
)
from src.schemas.event import (
    EventBase,
    EventCreate,
    EventList,
    EventRead,
    TrackingStats,
)
from src.schemas.lead import (
    LeadBase,
    LeadCreate,
    LeadList,
    LeadRead,
    LeadUpdate,
    LeadWithCompany,
)
from src.schemas.scrape_job import (
    ScrapeJobBase,
    ScrapeJobCreate,
    ScrapeJobList,
    ScrapeJobRead,
    ScrapeJobUpdate,
    ScrapeJobWithDuration,
)
from src.schemas.user import (
    LoginRequest,
    PasswordChange,
    Token,
    TokenPayload,
    UserBase,
    UserCreate,
    UserList,
    UserRead,
    UserUpdate,
)

__all__ = [
    # Company
    "CompanyBase",
    "CompanyCreate",
    "CompanyUpdate",
    "CompanyRead",
    "CompanyList",
    # Lead
    "LeadBase",
    "LeadCreate",
    "LeadUpdate",
    "LeadRead",
    "LeadList",
    "LeadWithCompany",
    # Email
    "EmailBase",
    "EmailCreate",
    "EmailUpdate",
    "EmailRead",
    "EmailList",
    "EmailSequence",
    # Event
    "EventBase",
    "EventCreate",
    "EventRead",
    "EventList",
    "TrackingStats",
    # ScrapeJob
    "ScrapeJobBase",
    "ScrapeJobCreate",
    "ScrapeJobUpdate",
    "ScrapeJobRead",
    "ScrapeJobList",
    "ScrapeJobWithDuration",
    # User & Auth
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserRead",
    "UserList",
    "Token",
    "TokenPayload",
    "LoginRequest",
    "PasswordChange",
]
