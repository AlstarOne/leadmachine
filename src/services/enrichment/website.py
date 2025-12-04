"""Website scraper for finding team members and contact information."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


@dataclass
class Person:
    """Person found on a website."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    image_url: str | None = None
    source_url: str | None = None
    confidence: int = 50  # 0-100

    @property
    def name(self) -> str:
        """Get best available name."""
        if self.full_name:
            return self.full_name
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"


@dataclass
class ContactInfo:
    """Contact information found on a website."""

    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)


class WebsiteScraper:
    """Scraper for extracting team members and contact info from websites."""

    # URL patterns for team/about pages
    TEAM_PAGE_PATTERNS = [
        r"/team",
        r"/about",
        r"/about-us",
        r"/over-ons",
        r"/ons-team",
        r"/mensen",
        r"/people",
        r"/who-we-are",
        r"/our-team",
        r"/leadership",
        r"/management",
        r"/staff",
        r"/medewerkers",
    ]

    # Contact page patterns
    CONTACT_PAGE_PATTERNS = [
        r"/contact",
        r"/contact-us",
        r"/contacteer-ons",
        r"/get-in-touch",
    ]

    # Job title patterns for decision makers
    DECISION_MAKER_TITLES = [
        r"ceo",
        r"chief executive",
        r"founder",
        r"oprichter",
        r"co-founder",
        r"mede-oprichter",
        r"managing director",
        r"directeur",
        r"cto",
        r"chief technology",
        r"cfo",
        r"chief financial",
        r"coo",
        r"chief operating",
        r"cmo",
        r"chief marketing",
        r"vp",
        r"vice president",
        r"head of",
        r"hoofd",
        r"director",
        r"manager",
        r"owner",
        r"eigenaar",
        r"partner",
    ]

    def __init__(
        self,
        timeout: float = 15.0,
        max_pages: int = 10,
    ) -> None:
        """Initialize website scraper.

        Args:
            timeout: Request timeout in seconds.
            max_pages: Maximum pages to scrape per domain.
        """
        self.timeout = timeout
        self.max_pages = max_pages
        self._http_client: Any = None

    async def _get_client(self) -> Any:
        """Get or create HTTP client."""
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
                verify=False,  # Some sites have cert issues
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def find_team_members(self, domain: str) -> list[Person]:
        """Find team members from a company website.

        Args:
            domain: Company domain.

        Returns:
            List of Person objects found.
        """
        base_url = f"https://{domain}"
        team_pages = await self._find_team_pages(base_url)

        all_people: list[Person] = []
        seen_names: set[str] = set()

        for page_url in team_pages[: self.max_pages]:
            try:
                people = await self._scrape_team_page(page_url)
                for person in people:
                    name_key = person.name.lower()
                    if name_key not in seen_names and name_key != "unknown":
                        person.source_url = page_url
                        all_people.append(person)
                        seen_names.add(name_key)
            except Exception:
                continue

        # Sort by confidence and title importance
        all_people.sort(
            key=lambda p: (
                self._is_decision_maker(p.job_title),
                p.confidence,
            ),
            reverse=True,
        )

        return all_people

    async def find_contact_info(self, domain: str) -> ContactInfo:
        """Find contact information from a company website.

        Args:
            domain: Company domain.

        Returns:
            ContactInfo with found data.
        """
        base_url = f"https://{domain}"
        contact_info = ContactInfo()

        # Try main page and contact pages
        pages_to_check = [base_url]
        pages_to_check.extend(await self._find_contact_pages(base_url))

        for page_url in pages_to_check[: self.max_pages]:
            try:
                html = await self._fetch_page(page_url)
                if html:
                    self._extract_contact_info(html, contact_info)
            except Exception:
                continue

        # Deduplicate
        contact_info.emails = list(dict.fromkeys(contact_info.emails))
        contact_info.phones = list(dict.fromkeys(contact_info.phones))
        contact_info.addresses = list(dict.fromkeys(contact_info.addresses))

        return contact_info

    async def _find_team_pages(self, base_url: str) -> list[str]:
        """Find team/about page URLs.

        Args:
            base_url: Website base URL.

        Returns:
            List of potential team page URLs.
        """
        found_pages: list[str] = []

        # Try common patterns
        for pattern in self.TEAM_PAGE_PATTERNS:
            url = f"{base_url}{pattern}"
            if await self._page_exists(url):
                found_pages.append(url)

        # Also check homepage for links to team pages
        try:
            html = await self._fetch_page(base_url)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = link["href"].lower()
                    for pattern in self.TEAM_PAGE_PATTERNS:
                        if pattern.strip("/") in href:
                            full_url = urljoin(base_url, link["href"])
                            if full_url not in found_pages:
                                found_pages.append(full_url)
        except Exception:
            pass

        return found_pages

    async def _find_contact_pages(self, base_url: str) -> list[str]:
        """Find contact page URLs.

        Args:
            base_url: Website base URL.

        Returns:
            List of contact page URLs.
        """
        found_pages: list[str] = []

        for pattern in self.CONTACT_PAGE_PATTERNS:
            url = f"{base_url}{pattern}"
            if await self._page_exists(url):
                found_pages.append(url)

        return found_pages

    async def _page_exists(self, url: str) -> bool:
        """Check if a page exists (returns 200).

        Args:
            url: URL to check.

        Returns:
            True if page exists.
        """
        try:
            client = await self._get_client()
            response = await client.head(url)
            return response.status_code == 200
        except Exception:
            return False

    async def _fetch_page(self, url: str) -> str | None:
        """Fetch page HTML.

        Args:
            url: URL to fetch.

        Returns:
            HTML content or None.
        """
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except Exception:
            return None

    async def _scrape_team_page(self, url: str) -> list[Person]:
        """Scrape team members from a page.

        Args:
            url: Team page URL.

        Returns:
            List of Person objects.
        """
        html = await self._fetch_page(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        people: list[Person] = []

        # Look for common team member patterns
        # Pattern 1: Team cards/grid items
        team_cards = soup.find_all(
            ["div", "article", "li"],
            class_=re.compile(
                r"team|member|person|employee|staff|profile|card",
                re.I,
            ),
        )

        for card in team_cards:
            person = self._parse_team_card(card)
            if person and person.name != "Unknown":
                people.append(person)

        # Pattern 2: Structured data (JSON-LD)
        people.extend(self._extract_from_structured_data(soup))

        return people

    def _parse_team_card(self, card: Any) -> Person | None:
        """Parse a team member card element.

        Args:
            card: BeautifulSoup element.

        Returns:
            Person or None.
        """
        person = Person()

        # Find name
        name_elem = card.find(
            ["h2", "h3", "h4", "strong", "span"],
            class_=re.compile(r"name|title", re.I),
        )
        if not name_elem:
            name_elem = card.find(["h2", "h3", "h4"])

        if name_elem:
            full_name = name_elem.get_text(strip=True)
            person.full_name = full_name
            parts = self._split_name(full_name)
            person.first_name = parts[0]
            person.last_name = parts[1]

        # Find job title
        title_elem = card.find(
            ["p", "span", "div"],
            class_=re.compile(r"title|role|position|function|functie", re.I),
        )
        if title_elem:
            person.job_title = title_elem.get_text(strip=True)

        # Find email
        email_link = card.find("a", href=re.compile(r"mailto:"))
        if email_link:
            email = email_link["href"].replace("mailto:", "").split("?")[0]
            person.email = email.strip().lower()

        # Find LinkedIn
        linkedin_link = card.find("a", href=re.compile(r"linkedin\.com"))
        if linkedin_link:
            person.linkedin_url = linkedin_link["href"]

        # Find image
        img = card.find("img")
        if img and img.get("src"):
            person.image_url = img["src"]

        # Set confidence based on what we found
        if person.full_name:
            person.confidence = 60
            if person.job_title:
                person.confidence += 20
            if person.email:
                person.confidence += 10
            if person.linkedin_url:
                person.confidence += 10

        return person if person.full_name else None

    def _split_name(self, full_name: str) -> tuple[str | None, str | None]:
        """Split full name into first and last name.

        Args:
            full_name: Full name string.

        Returns:
            Tuple of (first_name, last_name).
        """
        if not full_name:
            return None, None

        parts = full_name.strip().split()
        if len(parts) == 0:
            return None, None
        elif len(parts) == 1:
            return parts[0], None
        else:
            # Handle Dutch naming: "Jan van den Berg"
            # Prefixes that belong to last name
            prefixes = {"van", "de", "den", "der", "het", "ter", "te", "ten"}

            first_name = parts[0]
            last_parts = parts[1:]

            # Check if middle parts are prefixes
            if len(last_parts) > 1 and last_parts[0].lower() in prefixes:
                last_name = " ".join(last_parts)
            else:
                last_name = " ".join(last_parts)

            return first_name, last_name

    def _extract_from_structured_data(self, soup: BeautifulSoup) -> list[Person]:
        """Extract people from JSON-LD structured data.

        Args:
            soup: BeautifulSoup object.

        Returns:
            List of Person objects.
        """
        import json

        people: list[Person] = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                people.extend(self._parse_json_ld(data))
            except Exception:
                continue

        return people

    def _parse_json_ld(self, data: dict | list) -> list[Person]:
        """Parse JSON-LD data for people.

        Args:
            data: JSON-LD data.

        Returns:
            List of Person objects.
        """
        people: list[Person] = []

        if isinstance(data, list):
            for item in data:
                people.extend(self._parse_json_ld(item))
        elif isinstance(data, dict):
            schema_type = data.get("@type", "")
            if schema_type == "Person":
                person = Person(
                    full_name=data.get("name"),
                    job_title=data.get("jobTitle"),
                    email=data.get("email"),
                    confidence=80,  # Structured data is reliable
                )
                if person.full_name:
                    parts = self._split_name(person.full_name)
                    person.first_name = parts[0]
                    person.last_name = parts[1]
                    people.append(person)

            # Check nested structures
            for key in ["member", "employee", "founder", "employee"]:
                if key in data:
                    people.extend(self._parse_json_ld(data[key]))

        return people

    def _extract_contact_info(self, html: str, info: ContactInfo) -> None:
        """Extract contact information from HTML.

        Args:
            html: Page HTML.
            info: ContactInfo object to populate.
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # Extract emails
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        emails = re.findall(email_pattern, text)
        info.emails.extend(e.lower() for e in emails if self._is_valid_email(e))

        # Also check mailto links
        for link in soup.find_all("a", href=re.compile(r"mailto:")):
            email = link["href"].replace("mailto:", "").split("?")[0]
            if self._is_valid_email(email):
                info.emails.append(email.lower())

        # Extract phone numbers (Dutch and international formats)
        phone_patterns = [
            r"\+31\s*\(?0?\)?\s*\d{1,3}[\s\-]?\d{3}[\s\-]?\d{4}",  # +31 format
            r"0\d{2}[\s\-]?\d{3}[\s\-]?\d{4}",  # 010-123-4567
            r"0\d{9}",  # 0101234567
            r"\+\d{1,3}[\s\-]?\d{6,12}",  # International
        ]
        for pattern in phone_patterns:
            phones = re.findall(pattern, text)
            info.phones.extend(phones)

        # Extract social links
        social_patterns = {
            "linkedin": r"https?://(?:www\.)?linkedin\.com/company/[a-zA-Z0-9\-_]+",
            "twitter": r"https?://(?:www\.)?twitter\.com/[a-zA-Z0-9_]+",
            "facebook": r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+",
            "instagram": r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9._]+",
        }

        for platform, pattern in social_patterns.items():
            matches = re.findall(pattern, str(soup))
            if matches and platform not in info.social_links:
                info.social_links[platform] = matches[0]

    def _is_valid_email(self, email: str) -> bool:
        """Check if email looks valid and not generic.

        Args:
            email: Email to check.

        Returns:
            True if valid.
        """
        email = email.lower()

        # Skip common invalid patterns
        invalid_patterns = [
            r"example\.com$",
            r"test\.com$",
            r"@\d+\.",
            r"\.png@",  # image.png@domain
            r"\.jpg@",  # image.jpg@domain
            r"\.gif@",  # image.gif@domain
            r"\.svg@",  # image.svg@domain
            r"\.webp@",  # image.webp@domain
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, email):
                return False

        return True

    def _is_decision_maker(self, title: str | None) -> bool:
        """Check if job title indicates a decision maker.

        Args:
            title: Job title.

        Returns:
            True if decision maker.
        """
        if not title:
            return False

        title_lower = title.lower()
        for pattern in self.DECISION_MAKER_TITLES:
            if re.search(pattern, title_lower):
                return True

        return False
