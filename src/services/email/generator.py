"""Email generator service using LLM for personalization."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.company import Company
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.models.lead import Lead, LeadStatus
from src.services.email.templates import EmailTemplates
from src.services.llm.openai_service import OpenAIService, GenerationResult


@dataclass
class GeneratedEmail:
    """A generated email."""

    subject: str
    body: str
    preview_text: str
    email_type: str  # initial, followup1, followup2, breakup
    sequence_step: int
    word_count: int
    generation_result: GenerationResult
    scheduled_for: datetime | None = None


@dataclass
class EmailSequence:
    """A complete email sequence for a lead."""

    lead_id: int
    emails: list[GeneratedEmail] = field(default_factory=list)
    total_tokens: int = 0
    estimated_cost: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)


class EmailGenerator:
    """Service for generating personalized email sequences."""

    def __init__(
        self,
        openai_service: OpenAIService | None = None,
        value_proposition: str | None = None,
    ) -> None:
        """Initialize email generator.

        Args:
            openai_service: OpenAI service instance.
            value_proposition: Custom value proposition to use.
        """
        self.openai = openai_service or OpenAIService()
        self.custom_value_proposition = value_proposition
        self.templates = EmailTemplates()

    def _get_value_proposition(self, industry: str | None) -> str:
        """Get value proposition for context.

        Args:
            industry: Industry of the lead's company.

        Returns:
            Value proposition string.
        """
        if self.custom_value_proposition:
            return self.custom_value_proposition
        return EmailTemplates.get_value_proposition(industry)

    def _build_context(
        self,
        lead: Lead,
        company: Company | None,
        additional_context: str = "",
    ) -> dict[str, Any]:
        """Build context dictionary for template.

        Args:
            lead: Lead to generate email for.
            company: Company associated with lead.
            additional_context: Any additional context.

        Returns:
            Context dictionary.
        """
        return {
            "first_name": lead.first_name or "daar",
            "last_name": lead.last_name or "",
            "job_title": lead.job_title or "professional",
            "company_name": company.name if company else "jullie bedrijf",
            "industry": company.industry if company else "technologie",
            "location": company.location if company else "Nederland",
            "employee_count": company.employee_count if company else "onbekend",
            "open_vacancies": company.open_vacancies if company else 0,
            "additional_context": additional_context,
            "value_proposition": self._get_value_proposition(
                company.industry if company else None
            ),
        }

    async def generate_email(
        self,
        lead: Lead,
        company: Company | None,
        email_type: str,
        previous_subject: str | None = None,
        previous_summary: str | None = None,
        additional_context: str = "",
    ) -> GeneratedEmail:
        """Generate a single email.

        Args:
            lead: Lead to generate email for.
            company: Company associated with lead.
            email_type: Type of email to generate.
            previous_subject: Subject of previous email (for follow-ups).
            previous_summary: Summary of previous email.
            additional_context: Additional context for personalization.

        Returns:
            GeneratedEmail with subject and body.
        """
        template = EmailTemplates.get_template(email_type)
        context = self._build_context(lead, company, additional_context)

        # Add previous email info for follow-ups
        context["previous_subject"] = previous_subject or ""
        context["previous_summary"] = previous_summary or ""

        # Format prompts
        system_prompt = EmailTemplates.format_system_prompt(template)
        user_prompt = template.user_prompt_template.format(**context)

        # Generate with JSON response
        parsed_json, result = await self.openai.generate_with_json(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.7,
        )

        # Map email_type to sequence step
        step_map = {"initial": 1, "followup1": 2, "followup2": 3, "breakup": 4}
        sequence_step = step_map.get(email_type, 1)

        if not result.success or not parsed_json:
            # Return fallback email
            return GeneratedEmail(
                subject=f"Vraagje over {company.name if company else 'jullie bedrijf'}",
                body=f"Hoi {lead.first_name or 'daar'},\n\nIk hoop dat je even tijd hebt voor een korte vraag.\n\nMet vriendelijke groet",
                preview_text="Een korte vraag",
                email_type=email_type,
                sequence_step=sequence_step,
                word_count=20,
                generation_result=result,
            )

        subject = parsed_json.get("subject", "")
        body = parsed_json.get("body", "")
        preview_text = parsed_json.get("preview_text", "")

        word_count = len(body.split())

        return GeneratedEmail(
            subject=subject,
            body=body,
            preview_text=preview_text,
            email_type=email_type,
            sequence_step=sequence_step,
            word_count=word_count,
            generation_result=result,
        )

    async def generate_sequence(
        self,
        lead: Lead,
        company: Company | None,
        additional_context: str = "",
        start_date: datetime | None = None,
    ) -> EmailSequence:
        """Generate complete email sequence for a lead.

        Args:
            lead: Lead to generate sequence for.
            company: Company associated with lead.
            additional_context: Additional context for personalization.
            start_date: When to start the sequence (defaults to now).

        Returns:
            EmailSequence with all generated emails.
        """
        start_date = start_date or datetime.now()
        sequence = EmailSequence(lead_id=lead.id)

        schedule = EmailTemplates.get_sequence_schedule()
        previous_subject: str | None = None
        previous_summary: str | None = None

        for email_type, days_offset in schedule:
            try:
                email = await self.generate_email(
                    lead=lead,
                    company=company,
                    email_type=email_type,
                    previous_subject=previous_subject,
                    previous_summary=previous_summary,
                    additional_context=additional_context,
                )

                # Set scheduled time
                email.scheduled_for = start_date + timedelta(days=days_offset)

                # Track for next iteration
                previous_subject = email.subject
                previous_summary = email.body[:200] + "..." if len(email.body) > 200 else email.body

                # Accumulate stats
                sequence.total_tokens += email.generation_result.total_tokens
                sequence.estimated_cost += self.openai.estimate_cost(
                    email.generation_result.prompt_tokens,
                    email.generation_result.completion_tokens,
                )

                sequence.emails.append(email)

                if not email.generation_result.success:
                    sequence.errors.append(
                        f"{email_type}: {email.generation_result.error}"
                    )

            except Exception as e:
                sequence.errors.append(f"{email_type}: {str(e)}")
                sequence.success = False

        return sequence

    async def generate_and_save_sequence(
        self,
        db: AsyncSession,
        lead: Lead,
        company: Company | None = None,
        additional_context: str = "",
        start_date: datetime | None = None,
    ) -> EmailSequence:
        """Generate and save email sequence to database.

        Args:
            db: Database session.
            lead: Lead to generate sequence for.
            company: Company (loaded if not provided).
            additional_context: Additional context.
            start_date: When to start sequence.

        Returns:
            EmailSequence with saved emails.
        """
        # Load company if not provided
        if company is None and lead.company_id:
            company = await db.get(Company, lead.company_id)

        # Generate sequence
        sequence = await self.generate_sequence(
            lead=lead,
            company=company,
            additional_context=additional_context,
            start_date=start_date,
        )

        # Save to database
        step_enum_map = {
            1: EmailSequenceStep.INITIAL,
            2: EmailSequenceStep.FOLLOWUP_1,
            3: EmailSequenceStep.FOLLOWUP_2,
            4: EmailSequenceStep.BREAKUP,
        }
        day_map = {1: 0, 2: 3, 3: 7, 4: 14}

        for generated_email in sequence.emails:
            step_enum = step_enum_map.get(
                generated_email.sequence_step, EmailSequenceStep.INITIAL
            )
            scheduled_day = day_map.get(generated_email.sequence_step, 0)

            email = Email(
                lead_id=lead.id,
                sequence_step=step_enum,
                scheduled_day=scheduled_day,
                subject=generated_email.subject,
                body_text=generated_email.body,
                body_html=self._text_to_html(generated_email.body),
                status=EmailStatus.PENDING,
                scheduled_at=generated_email.scheduled_for,
            )
            db.add(email)

        # Update lead status
        lead.status = LeadStatus.SEQUENCED
        lead.sequenced_at = datetime.now()
        db.add(lead)

        await db.commit()

        return sequence

    def _text_to_html(self, text: str) -> str:
        """Convert plain text email to HTML.

        Args:
            text: Plain text email body.

        Returns:
            HTML version of the email.
        """
        # Escape HTML characters
        html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Convert newlines to paragraphs
        paragraphs = html.split("\n\n")
        html_paragraphs = [f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip()]

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        p {{ margin: 0 0 16px 0; }}
    </style>
</head>
<body>
    {''.join(html_paragraphs)}
</body>
</html>"""

    async def regenerate_email(
        self,
        db: AsyncSession,
        email: Email,
        lead: Lead,
        company: Company | None = None,
    ) -> GeneratedEmail:
        """Regenerate a specific email.

        Args:
            db: Database session.
            email: Existing email to regenerate.
            lead: Lead associated with email.
            company: Company (loaded if not provided).

        Returns:
            New GeneratedEmail.
        """
        # Load company if needed
        if company is None and lead.company_id:
            company = await db.get(Company, lead.company_id)

        # Determine email type from sequence step
        type_map = {1: "initial", 2: "followup1", 3: "followup2", 4: "breakup"}
        email_type = type_map.get(email.sequence_step, "initial")

        # Generate new email
        generated = await self.generate_email(
            lead=lead,
            company=company,
            email_type=email_type,
        )

        # Update existing email record
        email.subject = generated.subject
        email.body_text = generated.body
        email.body_html = self._text_to_html(generated.body)

        db.add(email)
        await db.commit()

        return generated
