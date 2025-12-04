"""CRUD operations for LeadMachine."""

from src.crud.company import company
from src.crud.email import email
from src.crud.event import event
from src.crud.lead import lead
from src.crud.scrape_job import scrape_job
from src.crud.user import user

__all__ = [
    "company",
    "email",
    "event",
    "lead",
    "scrape_job",
    "user",
]
