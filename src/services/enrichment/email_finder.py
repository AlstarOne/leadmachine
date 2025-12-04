"""Email finder service for generating and verifying email addresses."""

import asyncio
import re
import socket
import smtplib
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from src.services.enrichment.domain import DomainService


@dataclass
class EmailCandidate:
    """A potential email address with confidence score."""

    email: str
    pattern_name: str
    confidence: int  # 0-100
    is_verified: bool = False
    verification_status: str = "unknown"  # valid, invalid, catch_all, unknown


@dataclass
class EmailFinderResult:
    """Result of email finding operation."""

    candidates: list[EmailCandidate]
    best_email: str | None
    best_confidence: int
    domain_has_mx: bool
    domain_is_catch_all: bool = False


class EmailFinder:
    """Service for finding and verifying email addresses."""

    # Common email patterns (order by likelihood)
    EMAIL_PATTERNS = [
        ("first.last", "{first}.{last}@{domain}"),
        ("firstlast", "{first}{last}@{domain}"),
        ("first_last", "{first}_{last}@{domain}"),
        ("flast", "{f}{last}@{domain}"),
        ("firstl", "{first}{l}@{domain}"),
        ("first", "{first}@{domain}"),
        ("last.first", "{last}.{first}@{domain}"),
        ("lastfirst", "{last}{first}@{domain}"),
        ("last_first", "{last}_{first}@{domain}"),
        ("f.last", "{f}.{last}@{domain}"),
        ("first.l", "{first}.{l}@{domain}"),
        ("last", "{last}@{domain}"),
    ]

    # Pattern weights based on common usage
    PATTERN_WEIGHTS = {
        "first.last": 95,
        "firstlast": 85,
        "first_last": 75,
        "flast": 70,
        "firstl": 65,
        "first": 60,
        "last.first": 55,
        "lastfirst": 50,
        "last_first": 45,
        "f.last": 40,
        "first.l": 35,
        "last": 30,
    }

    def __init__(
        self,
        domain_service: DomainService | None = None,
        verify_emails: bool = True,
        timeout: float = 10.0,
    ) -> None:
        """Initialize email finder.

        Args:
            domain_service: Domain service for MX checks.
            verify_emails: Whether to verify emails via SMTP.
            timeout: Timeout for SMTP verification.
        """
        self.domain_service = domain_service or DomainService()
        self.verify_emails = verify_emails
        self.timeout = timeout

    def generate_patterns(
        self,
        first_name: str,
        last_name: str,
        domain: str,
    ) -> list[EmailCandidate]:
        """Generate email pattern candidates.

        Args:
            first_name: Person's first name.
            last_name: Person's last name.
            domain: Company domain.

        Returns:
            List of email candidates sorted by confidence.
        """
        if not first_name or not last_name or not domain:
            return []

        # Normalize inputs
        first = self._normalize_name(first_name)
        last = self._normalize_name(last_name)
        domain = self.domain_service.normalize(domain) or domain.lower()

        if not first or not last:
            return []

        candidates: list[EmailCandidate] = []

        for pattern_name, pattern_template in self.EMAIL_PATTERNS:
            try:
                email = pattern_template.format(
                    first=first,
                    last=last,
                    f=first[0],
                    l=last[0],
                    domain=domain,
                )

                # Validate email format
                if self._is_valid_format(email):
                    candidates.append(
                        EmailCandidate(
                            email=email,
                            pattern_name=pattern_name,
                            confidence=self.PATTERN_WEIGHTS.get(pattern_name, 50),
                        )
                    )
            except (IndexError, KeyError):
                continue

        # Sort by confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        return candidates

    async def find_email(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        known_pattern: str | None = None,
    ) -> EmailFinderResult:
        """Find the most likely email for a person.

        Args:
            first_name: Person's first name.
            last_name: Person's last name.
            domain: Company domain.
            known_pattern: Known email pattern to prioritize.

        Returns:
            EmailFinderResult with candidates and best match.
        """
        # Check domain has MX records
        has_mx, mx_records = await self.domain_service.check_mx_records(domain)

        if not has_mx:
            return EmailFinderResult(
                candidates=[],
                best_email=None,
                best_confidence=0,
                domain_has_mx=False,
            )

        # Generate candidates
        candidates = self.generate_patterns(first_name, last_name, domain)

        if not candidates:
            return EmailFinderResult(
                candidates=[],
                best_email=None,
                best_confidence=0,
                domain_has_mx=has_mx,
            )

        # If known pattern, prioritize it
        if known_pattern:
            for candidate in candidates:
                if candidate.pattern_name == known_pattern:
                    candidate.confidence += 20

        # Verify emails if enabled
        is_catch_all = False
        if self.verify_emails and mx_records:
            # First check if domain is catch-all
            is_catch_all = await self._check_catch_all(domain, mx_records[0])

            if not is_catch_all:
                # Verify top candidates
                verified_candidates = await self._verify_candidates(
                    candidates[:5], mx_records[0]
                )
                candidates = verified_candidates + candidates[5:]

        # Sort by confidence again after verification
        candidates.sort(key=lambda c: (c.is_verified, c.confidence), reverse=True)

        # Get best email
        best_email = None
        best_confidence = 0

        for candidate in candidates:
            if candidate.is_verified or (is_catch_all and candidate.confidence >= 70):
                best_email = candidate.email
                best_confidence = candidate.confidence
                break

        # If no verified, use highest confidence
        if not best_email and candidates:
            best_email = candidates[0].email
            best_confidence = candidates[0].confidence

        return EmailFinderResult(
            candidates=candidates,
            best_email=best_email,
            best_confidence=best_confidence,
            domain_has_mx=has_mx,
            domain_is_catch_all=is_catch_all,
        )

    async def verify_email(
        self,
        email: str,
    ) -> tuple[bool, int, str]:
        """Verify if an email address is valid via SMTP.

        Args:
            email: Email address to verify.

        Returns:
            Tuple of (is_valid, confidence, status).
        """
        if not self._is_valid_format(email):
            return False, 0, "invalid_format"

        domain = email.split("@")[1]
        has_mx, mx_records = await self.domain_service.check_mx_records(domain)

        if not has_mx:
            return False, 0, "no_mx"

        try:
            # Run SMTP check in thread pool
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._smtp_verify, email, mx_records[0]
                ),
                timeout=self.timeout,
            )
            return result
        except asyncio.TimeoutError:
            return False, 30, "timeout"
        except Exception:
            return False, 20, "error"

    async def _verify_candidates(
        self,
        candidates: list[EmailCandidate],
        mx_server: str,
    ) -> list[EmailCandidate]:
        """Verify multiple email candidates.

        Args:
            candidates: List of candidates to verify.
            mx_server: MX server to use.

        Returns:
            Candidates with verification results.
        """
        tasks = []
        for candidate in candidates:
            tasks.append(self.verify_email(candidate.email))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for candidate, result in zip(candidates, results):
            if isinstance(result, Exception):
                candidate.verification_status = "error"
            else:
                is_valid, confidence, status = result
                candidate.is_verified = is_valid
                candidate.verification_status = status
                if is_valid:
                    candidate.confidence = min(100, candidate.confidence + 20)

        return candidates

    async def _check_catch_all(self, domain: str, mx_server: str) -> bool:
        """Check if domain accepts all emails (catch-all).

        Args:
            domain: Domain to check.
            mx_server: MX server.

        Returns:
            True if catch-all.
        """
        # Generate a random fake email
        import uuid

        fake_email = f"nonexistent-{uuid.uuid4().hex[:8]}@{domain}"

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._smtp_verify, fake_email, mx_server
                ),
                timeout=self.timeout,
            )
            is_valid, _, _ = result
            return is_valid  # If fake email is accepted, it's catch-all
        except Exception:
            return False

    def _smtp_verify(
        self,
        email: str,
        mx_server: str,
    ) -> tuple[bool, int, str]:
        """Synchronous SMTP verification.

        Args:
            email: Email to verify.
            mx_server: MX server to connect to.

        Returns:
            Tuple of (is_valid, confidence, status).
        """
        try:
            # Connect to MX server
            smtp = smtplib.SMTP(timeout=self.timeout)
            smtp.connect(mx_server)
            smtp.helo("verify.example.com")

            # Try MAIL FROM
            code, _ = smtp.mail("verify@example.com")
            if code != 250:
                smtp.quit()
                return False, 30, "mail_rejected"

            # Try RCPT TO
            code, message = smtp.rcpt(email)
            smtp.quit()

            if code == 250:
                return True, 95, "valid"
            elif code == 550 or code == 551 or code == 553:
                return False, 95, "invalid"
            elif code == 450 or code == 451:
                # Temporary failure, might be greylisting
                return False, 50, "greylisted"
            else:
                return False, 40, f"unknown_{code}"

        except smtplib.SMTPServerDisconnected:
            return False, 30, "disconnected"
        except socket.timeout:
            return False, 30, "timeout"
        except Exception as e:
            return False, 20, f"error_{type(e).__name__}"

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for email generation.

        Args:
            name: Name to normalize.

        Returns:
            Normalized name.
        """
        if not name:
            return ""

        # Remove accents
        name = self._remove_accents(name)

        # Lowercase and strip
        name = name.lower().strip()

        # Remove non-alphanumeric except spaces
        name = re.sub(r"[^\w\s]", "", name)

        # Replace spaces with nothing (for compound names)
        name = name.replace(" ", "")

        return name

    def _remove_accents(self, text: str) -> str:
        """Remove accent characters from text.

        Args:
            text: Text with potential accents.

        Returns:
            Text without accents.
        """
        import unicodedata

        # Normalize to decomposed form
        normalized = unicodedata.normalize("NFD", text)

        # Remove combining characters (accents)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    def _is_valid_format(self, email: str) -> bool:
        """Check if email has valid format.

        Args:
            email: Email to check.

        Returns:
            True if valid format.
        """
        # Basic regex check
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, email))

    def detect_pattern(self, emails: list[str], domain: str) -> str | None:
        """Detect the email pattern used by a company.

        Args:
            emails: List of known emails from the company.
            domain: Company domain.

        Returns:
            Pattern name or None if not detected.
        """
        if not emails:
            return None

        pattern_counts: dict[str, int] = {}

        for email in emails:
            email_lower = email.lower()
            if not email_lower.endswith(f"@{domain}"):
                continue

            local_part = email_lower.split("@")[0]

            # Try to match against patterns
            for pattern_name, _ in self.EMAIL_PATTERNS:
                if self._matches_pattern(local_part, pattern_name):
                    pattern_counts[pattern_name] = pattern_counts.get(pattern_name, 0) + 1

        if not pattern_counts:
            return None

        # Return most common pattern
        return max(pattern_counts, key=pattern_counts.get)  # type: ignore[arg-type]

    def _matches_pattern(self, local_part: str, pattern_name: str) -> bool:
        """Check if email local part matches a pattern.

        Args:
            local_part: Local part of email (before @).
            pattern_name: Pattern name to check.

        Returns:
            True if matches.
        """
        # This is a heuristic check
        if pattern_name == "first.last":
            return "." in local_part and local_part.count(".") == 1
        elif pattern_name == "firstlast":
            return "." not in local_part and "_" not in local_part and len(local_part) > 4
        elif pattern_name == "first_last":
            return "_" in local_part and local_part.count("_") == 1
        elif pattern_name == "flast":
            return len(local_part) > 2 and local_part[1].isalpha() and not local_part[0].isupper()
        elif pattern_name == "first":
            return "." not in local_part and "_" not in local_part and len(local_part) <= 10

        return False
