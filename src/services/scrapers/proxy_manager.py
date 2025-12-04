"""Proxy rotation manager for scraping protected sites."""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class Proxy:
    """Proxy server configuration."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    protocol: str = "http"
    last_used: datetime | None = None
    fail_count: int = 0
    success_count: int = 0
    is_blocked: bool = False
    blocked_until: datetime | None = None

    @property
    def url(self) -> str:
        """Get proxy URL string."""
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.fail_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def mark_success(self) -> None:
        """Mark a successful request."""
        self.success_count += 1
        self.fail_count = max(0, self.fail_count - 1)  # Reduce fail count on success
        self.last_used = datetime.now()

    def mark_failure(self, block_minutes: int = 10) -> None:
        """Mark a failed request."""
        self.fail_count += 1
        self.last_used = datetime.now()

        # Block proxy if too many failures
        if self.fail_count >= 3:
            self.is_blocked = True
            self.blocked_until = datetime.now() + timedelta(minutes=block_minutes)


@dataclass
class ProxyManager:
    """Manages proxy rotation for scraping."""

    proxies: list[Proxy] = field(default_factory=list)
    min_delay_between_uses: float = 5.0  # Seconds between using same proxy
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add_proxy(
        self,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
        protocol: str = "http",
    ) -> None:
        """Add a proxy to the pool.

        Args:
            host: Proxy hostname.
            port: Proxy port.
            username: Optional auth username.
            password: Optional auth password.
            protocol: Protocol (http, https, socks5).
        """
        proxy = Proxy(
            host=host,
            port=port,
            username=username,
            password=password,
            protocol=protocol,
        )
        self.proxies.append(proxy)

    def add_proxies_from_list(self, proxy_strings: list[str]) -> int:
        """Add proxies from list of strings.

        Supports formats:
        - host:port
        - host:port:user:pass
        - protocol://host:port
        - protocol://user:pass@host:port

        Args:
            proxy_strings: List of proxy strings.

        Returns:
            Number of proxies added.
        """
        added = 0
        for proxy_str in proxy_strings:
            try:
                proxy = self._parse_proxy_string(proxy_str)
                if proxy:
                    self.proxies.append(proxy)
                    added += 1
            except Exception:
                continue
        return added

    def _parse_proxy_string(self, proxy_str: str) -> Proxy | None:
        """Parse a proxy string into Proxy object.

        Args:
            proxy_str: Proxy string in various formats.

        Returns:
            Proxy object or None.
        """
        proxy_str = proxy_str.strip()
        if not proxy_str:
            return None

        protocol = "http"
        username = None
        password = None

        # Check for protocol prefix
        if "://" in proxy_str:
            protocol, proxy_str = proxy_str.split("://", 1)

        # Check for auth
        if "@" in proxy_str:
            auth, proxy_str = proxy_str.rsplit("@", 1)
            if ":" in auth:
                username, password = auth.split(":", 1)

        # Parse host:port or host:port:user:pass
        parts = proxy_str.split(":")
        if len(parts) < 2:
            return None

        host = parts[0]
        port = int(parts[1])

        if len(parts) >= 4 and not username:
            username = parts[2]
            password = parts[3]

        return Proxy(
            host=host,
            port=port,
            username=username,
            password=password,
            protocol=protocol,
        )

    async def get_proxy(self) -> Proxy | None:
        """Get next available proxy using weighted random selection.

        Prioritizes proxies with:
        - Higher success rate
        - Not recently used
        - Not blocked

        Returns:
            Selected proxy or None if no proxies available.
        """
        async with self._lock:
            now = datetime.now()

            # Unblock proxies whose block time has passed
            for proxy in self.proxies:
                if proxy.is_blocked and proxy.blocked_until:
                    if now >= proxy.blocked_until:
                        proxy.is_blocked = False
                        proxy.fail_count = 0

            # Get available proxies
            available = [
                p
                for p in self.proxies
                if not p.is_blocked
                and (
                    p.last_used is None
                    or (now - p.last_used).total_seconds() >= self.min_delay_between_uses
                )
            ]

            if not available:
                # If no proxies available due to timing, return any non-blocked
                available = [p for p in self.proxies if not p.is_blocked]

            if not available:
                return None

            # Weight by success rate
            weights = [p.success_rate + 0.1 for p in available]  # +0.1 to avoid zero weights
            selected = random.choices(available, weights=weights, k=1)[0]

            return selected

    async def mark_proxy_result(self, proxy: Proxy, success: bool) -> None:
        """Mark proxy request result.

        Args:
            proxy: The proxy used.
            success: Whether request succeeded.
        """
        async with self._lock:
            if success:
                proxy.mark_success()
            else:
                proxy.mark_failure()

    @property
    def available_count(self) -> int:
        """Get count of available (non-blocked) proxies."""
        return sum(1 for p in self.proxies if not p.is_blocked)

    @property
    def total_count(self) -> int:
        """Get total proxy count."""
        return len(self.proxies)

    def get_stats(self) -> dict[str, Any]:
        """Get proxy pool statistics.

        Returns:
            Dictionary with pool stats.
        """
        total = len(self.proxies)
        blocked = sum(1 for p in self.proxies if p.is_blocked)
        total_success = sum(p.success_count for p in self.proxies)
        total_fail = sum(p.fail_count for p in self.proxies)

        return {
            "total_proxies": total,
            "available": total - blocked,
            "blocked": blocked,
            "total_requests": total_success + total_fail,
            "total_success": total_success,
            "total_failures": total_fail,
            "success_rate": total_success / (total_success + total_fail)
            if (total_success + total_fail) > 0
            else 0,
        }
