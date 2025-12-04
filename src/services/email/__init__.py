"""Email services package."""

from src.services.email.generator import EmailGenerator, GeneratedEmail, EmailSequence
from src.services.email.scheduler import SchedulerService, SendSlot, RateLimitStatus
from src.services.email.sender import EmailSender, EmailSendResult
from src.services.email.smtp import SMTPService, SendResult
from src.services.email.templates import EmailTemplates

__all__ = [
    "EmailGenerator",
    "EmailTemplates",
    "GeneratedEmail",
    "EmailSequence",
    "SMTPService",
    "SendResult",
    "EmailSender",
    "EmailSendResult",
    "SchedulerService",
    "SendSlot",
    "RateLimitStatus",
]
