"""Domain service for normalization and validation."""

import asyncio
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class DomainInfo:
    """Information about a domain."""

    domain: str
    has_mx: bool
    mx_records: list[str]
    has_website: bool
    redirects_to: str | None = None
    is_valid: bool = True
    error: str | None = None


class DomainService:
    """Service for domain normalization and validation."""

    # Common email provider domains to skip
    EMAIL_PROVIDERS = {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.nl",
        "hotmail.com",
        "hotmail.nl",
        "outlook.com",
        "outlook.nl",
        "live.com",
        "live.nl",
        "msn.com",
        "msn.nl",
        "icloud.com",
        "me.com",
        "aol.com",
        "protonmail.com",
        "mail.com",
        "gmx.com",
        "gmx.nl",
        "ziggo.nl",
        "kpnmail.nl",
        "xs4all.nl",
        "hetnet.nl",
        "planet.nl",
        "home.nl",
        "upcmail.nl",
        "casema.nl",
        "tele2.nl",
    }

    # Common non-company domains
    EXCLUDED_DOMAINS = {
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "youtube.com",
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "medium.com",
        "wordpress.com",
        "wix.com",
        "squarespace.com",
        "weebly.com",
        "blogspot.com",
        "tumblr.com",
    }

    def __init__(self, timeout: float = 5.0) -> None:
        """Initialize domain service.

        Args:
            timeout: Timeout for DNS lookups in seconds.
        """
        self.timeout = timeout

    def normalize(self, domain: str | None) -> str | None:
        """Normalize a domain name.

        Args:
            domain: Raw domain string (may include protocol, www, path).

        Returns:
            Normalized domain or None if invalid.
        """
        if not domain:
            return None

        domain = domain.strip().lower()

        # Remove trailing dots (DNS FQDN format)
        domain = domain.rstrip(".")

        # Handle URLs
        if "://" in domain:
            try:
                parsed = urlparse(domain)
                domain = parsed.netloc or parsed.path
            except Exception:
                pass

        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]

        # Remove trailing slashes and paths
        domain = domain.split("/")[0]

        # Remove port
        domain = domain.split(":")[0]

        # Basic validation
        if not domain or "." not in domain:
            return None

        # Check for valid domain characters
        if not re.match(r"^[a-z0-9][a-z0-9\-\.]*[a-z0-9]$", domain):
            return None

        return domain

    def is_company_domain(self, domain: str) -> bool:
        """Check if domain is likely a company domain (not personal email).

        Args:
            domain: Normalized domain.

        Returns:
            True if likely a company domain.
        """
        domain = self.normalize(domain) or ""

        if domain in self.EMAIL_PROVIDERS:
            return False

        if domain in self.EXCLUDED_DOMAINS:
            return False

        # Check for subdomains of excluded
        for excluded in self.EXCLUDED_DOMAINS:
            if domain.endswith(f".{excluded}"):
                return False

        return True

    def extract_from_email(self, email: str) -> str | None:
        """Extract domain from email address (only if company domain).

        Args:
            email: Email address.

        Returns:
            Domain part of email or None if personal email provider.
        """
        if not email or "@" not in email:
            return None

        try:
            domain = email.split("@")[1].strip().lower()
            normalized = self.normalize(domain)
            # Return None if it's a personal email provider
            if normalized and not self.is_company_domain(normalized):
                return None
            return normalized
        except (IndexError, AttributeError):
            return None

    def extract_from_url(self, url: str) -> str | None:
        """Extract domain from URL.

        Args:
            url: Full URL.

        Returns:
            Domain or None.
        """
        return self.normalize(url)

    async def check_mx_records(self, domain: str) -> tuple[bool, list[str]]:
        """Check if domain has MX records (can receive email).

        Args:
            domain: Domain to check.

        Returns:
            Tuple of (has_mx, list of MX records).
        """
        domain = self.normalize(domain)
        if not domain:
            return False, []

        try:
            # Run DNS lookup in thread pool to not block
            loop = asyncio.get_event_loop()
            mx_records = await loop.run_in_executor(
                None, self._sync_mx_lookup, domain
            )
            return len(mx_records) > 0, mx_records
        except Exception:
            return False, []

    def _sync_mx_lookup(self, domain: str) -> list[str]:
        """Synchronous MX record lookup.

        Args:
            domain: Domain to lookup.

        Returns:
            List of MX server hostnames.
        """
        import dns.resolver

        try:
            answers = dns.resolver.resolve(domain, "MX")
            return [str(rdata.exchange).rstrip(".") for rdata in answers]
        except Exception:
            return []

    async def check_website(self, domain: str) -> tuple[bool, str | None]:
        """Check if domain has a working website.

        Args:
            domain: Domain to check.

        Returns:
            Tuple of (has_website, final_url_after_redirects).
        """
        import httpx

        domain = self.normalize(domain)
        if not domain:
            return False, None

        urls_to_try = [
            f"https://{domain}",
            f"https://www.{domain}",
            f"http://{domain}",
        ]

        for url in urls_to_try:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=True,
                    verify=False,  # Some sites have cert issues
                ) as client:
                    response = await client.head(url)
                    if response.status_code < 400:
                        return True, str(response.url)
            except Exception:
                continue

        return False, None

    async def get_domain_info(self, domain: str) -> DomainInfo:
        """Get comprehensive domain information.

        Args:
            domain: Domain to analyze.

        Returns:
            DomainInfo with all gathered data.
        """
        normalized = self.normalize(domain)
        if not normalized:
            return DomainInfo(
                domain=domain or "",
                has_mx=False,
                mx_records=[],
                has_website=False,
                is_valid=False,
                error="Invalid domain format",
            )

        # Run MX and website checks concurrently
        mx_task = self.check_mx_records(normalized)
        website_task = self.check_website(normalized)

        (has_mx, mx_records), (has_website, redirects_to) = await asyncio.gather(
            mx_task, website_task
        )

        return DomainInfo(
            domain=normalized,
            has_mx=has_mx,
            mx_records=mx_records,
            has_website=has_website,
            redirects_to=redirects_to,
            is_valid=True,
        )

    def guess_company_domain(self, company_name: str) -> list[str]:
        """Guess possible domains from company name.

        Args:
            company_name: Company name.

        Returns:
            List of possible domain guesses.
        """
        if not company_name:
            return []

        # Normalize name
        name = company_name.lower().strip()

        # Remove common suffixes (only remove one suffix)
        suffixes = [
            " b.v.", " bv", " n.v.", " nv", " holding", " group",
            " ltd", " limited", " inc", " corp", " gmbh", " llc",
        ]
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break  # Only remove one suffix

        # Remove punctuation and special chars
        name = re.sub(r"[^\w\s-]", "", name)

        # Create variations
        variations = []

        # Full name with spaces removed (e.g., "Tech Corp" -> "techcorp")
        simple = name.replace(" ", "").replace("-", "")
        variations.append(simple)

        # Hyphenated version
        hyphenated = name.replace(" ", "-")
        if hyphenated != simple:
            variations.append(hyphenated)

        # First word only (for "Company Name BV" -> "company")
        words = name.split()
        if words and words[0] != simple:
            variations.append(words[0])

        # First two words combined (for longer names)
        if len(words) >= 2:
            two_words = words[0] + words[1]
            if two_words not in variations:
                variations.append(two_words)

        # Common TLDs for Netherlands
        tlds = [".nl", ".com", ".io", ".eu", ".co"]

        domains = []
        for var in variations:
            if var and len(var) > 2:
                for tld in tlds:
                    domains.append(f"{var}{tld}")

        return list(dict.fromkeys(domains))  # Remove duplicates while preserving order
