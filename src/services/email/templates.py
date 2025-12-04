"""Email templates for cold outreach campaigns."""

from dataclasses import dataclass


@dataclass
class EmailTemplate:
    """Email template with system and user prompts."""

    name: str
    email_type: str  # initial, followup1, followup2, breakup
    system_prompt: str
    user_prompt_template: str
    max_words: int = 100
    tone: str = "professional"
    language: str = "dutch"


class EmailTemplates:
    """Collection of email templates for Dutch cold outreach."""

    # System prompt for all emails
    BASE_SYSTEM_PROMPT = """Je bent een expert in het schrijven van zakelijke cold emails in het Nederlands.

Schrijfregels:
- Houd de email kort en bondig (max {max_words} woorden)
- Gebruik een {tone} maar menselijke toon
- Geen overdreven verkooppraatjes of hype
- Begin NOOIT met "Ik hoop dat het goed met je gaat" of vergelijkbare clichés
- Geen emojis of uitroeptekens in de onderwerpregel
- Personaliseer op basis van de gegeven context
- Focus op waarde voor de ontvanger, niet op jezelf
- Eindig met een duidelijke, lage-drempel call-to-action
- Gebruik "je/jij" tenzij het een zeer formele sector is
- Schrijf in vloeiend, natuurlijk Nederlands

Structuur:
1. Korte, relevante opening (1 zin)
2. Waardepropositie of relevante observatie (2-3 zinnen)
3. Call-to-action (1 zin)

Vermijd:
- "Mijn naam is..." als opening
- "Ik kwam je profiel tegen..."
- "Ik wilde even contact opnemen..."
- Lange opsommingen van features
- Te veel vragen in één email"""

    INITIAL_EMAIL = EmailTemplate(
        name="initial",
        email_type="initial",
        system_prompt=BASE_SYSTEM_PROMPT,
        user_prompt_template="""Schrijf een eerste cold email voor de volgende situatie:

Lead informatie:
- Naam: {first_name} {last_name}
- Functie: {job_title}
- Bedrijf: {company_name}
- Industrie: {industry}
- Locatie: {location}
- Bedrijfsgrootte: {employee_count} medewerkers
- Open vacatures: {open_vacancies}

Extra context (indien beschikbaar):
{additional_context}

Onze propositie:
{value_proposition}

Schrijf nu een persoonlijke, korte email die:
1. Opent met iets relevanters dan "Hoi [naam]"
2. Toont dat je het bedrijf kent
3. Een specifiek voordeel benoemd
4. Eindigt met een simpele vraag of verzoek

Geef je antwoord in het volgende JSON formaat:
{{
    "subject": "Onderwerpregel (max 50 karakters)",
    "body": "De email tekst",
    "preview_text": "Preview tekst voor inbox (max 90 karakters)"
}}""",
        max_words=100,
    )

    FOLLOWUP_1 = EmailTemplate(
        name="followup_1",
        email_type="followup1",
        system_prompt=BASE_SYSTEM_PROMPT,
        user_prompt_template="""Schrijf een eerste follow-up email (3 dagen na de eerste email):

Lead informatie:
- Naam: {first_name} {last_name}
- Functie: {job_title}
- Bedrijf: {company_name}
- Industrie: {industry}

Vorige email onderwerp: {previous_subject}
Vorige email samenvatting: {previous_summary}

Onze propositie:
{value_proposition}

Schrijf een korte follow-up die:
1. Niet begint met "Ik wilde even checken..."
2. Een nieuwe invalshoek of extra waarde biedt
3. Kort refereert aan de vorige email
4. Laagdrempelig eindigt

Geef je antwoord in het volgende JSON formaat:
{{
    "subject": "Re: [vorige onderwerp] of nieuwe onderwerpregel",
    "body": "De email tekst",
    "preview_text": "Preview tekst voor inbox (max 90 karakters)"
}}""",
        max_words=80,
    )

    FOLLOWUP_2 = EmailTemplate(
        name="followup_2",
        email_type="followup2",
        system_prompt=BASE_SYSTEM_PROMPT,
        user_prompt_template="""Schrijf een tweede follow-up email (7 dagen na de eerste email):

Lead informatie:
- Naam: {first_name} {last_name}
- Functie: {job_title}
- Bedrijf: {company_name}
- Industrie: {industry}

Vorige emails: 2 (geen reactie)
Laatste onderwerp: {previous_subject}

Onze propositie:
{value_proposition}

Schrijf een follow-up die:
1. Een compleet nieuwe invalshoek heeft
2. Mogelijk een andere stakeholder suggereert
3. Nog steeds waarde biedt zonder pushy te zijn
4. Kort en direct is

Geef je antwoord in het volgende JSON formaat:
{{
    "subject": "Nieuwe onderwerpregel (niet Re:)",
    "body": "De email tekst",
    "preview_text": "Preview tekst voor inbox (max 90 karakters)"
}}""",
        max_words=70,
    )

    BREAKUP = EmailTemplate(
        name="breakup",
        email_type="breakup",
        system_prompt=BASE_SYSTEM_PROMPT,
        user_prompt_template="""Schrijf een laatste "breakup" email (14 dagen na de eerste email):

Lead informatie:
- Naam: {first_name} {last_name}
- Functie: {job_title}
- Bedrijf: {company_name}

Vorige emails: 3 (geen reactie)

Onze propositie:
{value_proposition}

Schrijf een afsluitende email die:
1. Respectvol erkent dat timing mogelijk niet goed is
2. De deur open laat voor toekomstig contact
3. GEEN schuldgevoel probeert op te wekken
4. Kort en waardig is
5. Mogelijk een laatste stukje waarde deelt (artikel, tip, etc.)

Geef je antwoord in het volgende JSON formaat:
{{
    "subject": "Korte, directe onderwerpregel",
    "body": "De email tekst",
    "preview_text": "Preview tekst voor inbox (max 90 karakters)"
}}""",
        max_words=60,
    )

    # Default value propositions for different scenarios
    DEFAULT_VALUE_PROPOSITIONS = {
        "saas": """We helpen SaaS bedrijven hun sales cycle te verkorten door
data-gedreven lead qualification en gepersonaliseerde outreach.""",

        "technology": """We ondersteunen tech bedrijven bij het vinden van
gekwalificeerde leads in de Nederlandse markt.""",

        "recruitment": """We automatiseren het proces van het vinden en
benaderen van potentiële kandidaten en klanten.""",

        "marketing": """We helpen marketing agencies hun outbound strategie
te optimaliseren met AI-gedreven personalisatie.""",

        "default": """We helpen bedrijven tijd te besparen op leadgeneratie
door slimme automatisering en personalisatie.""",
    }

    @classmethod
    def get_template(cls, email_type: str) -> EmailTemplate:
        """Get template by email type.

        Args:
            email_type: Type of email (initial, followup1, followup2, breakup).

        Returns:
            EmailTemplate for the type.

        Raises:
            ValueError: If type is unknown.
        """
        templates = {
            "initial": cls.INITIAL_EMAIL,
            "followup1": cls.FOLLOWUP_1,
            "followup2": cls.FOLLOWUP_2,
            "breakup": cls.BREAKUP,
        }

        if email_type not in templates:
            raise ValueError(f"Unknown email type: {email_type}")

        return templates[email_type]

    @classmethod
    def get_value_proposition(cls, industry: str | None) -> str:
        """Get value proposition for industry.

        Args:
            industry: Industry name.

        Returns:
            Value proposition string.
        """
        if not industry:
            return cls.DEFAULT_VALUE_PROPOSITIONS["default"]

        industry_lower = industry.lower()

        for key, value in cls.DEFAULT_VALUE_PROPOSITIONS.items():
            if key in industry_lower or industry_lower in key:
                return value

        return cls.DEFAULT_VALUE_PROPOSITIONS["default"]

    @classmethod
    def get_sequence_schedule(cls) -> list[tuple[str, int]]:
        """Get the email sequence schedule.

        Returns:
            List of (email_type, days_after_start) tuples.
        """
        return [
            ("initial", 0),
            ("followup1", 3),
            ("followup2", 7),
            ("breakup", 14),
        ]

    @classmethod
    def format_system_prompt(
        cls,
        template: EmailTemplate,
        tone: str = "professional",
    ) -> str:
        """Format system prompt with variables.

        Args:
            template: Email template.
            tone: Desired tone.

        Returns:
            Formatted system prompt.
        """
        return template.system_prompt.format(
            max_words=template.max_words,
            tone=tone,
        )
