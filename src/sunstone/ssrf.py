"""
SSRF (Server-Side Request Forgery) protection for URL validation.

Validates that URLs point to public internet resources, blocking access to
private networks, cloud metadata endpoints, and other restricted addresses.

Usage::

    from sunstone.ssrf import is_public_url

    if not is_public_url("https://example.com/data.csv"):
        raise ValueError("URL is not allowed")

The validation checks:
- Only ``http`` and ``https`` schemes are permitted
- All resolved IP addresses must be on the public internet
- Cloud metadata endpoints are always blocked
- IPv4-mapped IPv6 addresses are unwrapped and validated
- DNS resolution failures are treated as blocked

Based on protections from Pydantic AI, Advocate, and SafeURL.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

__all__ = ["is_public_url", "BLOCKED_NETWORKS", "CLOUD_METADATA_IPS"]

logger = logging.getLogger(__name__)

# IP networks that must never be reached via URL fetching.
# Compiled from Pydantic AI, Advocate, and SafeURL.
BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    # --- IPv4 ---
    ipaddress.IPv4Network("0.0.0.0/8"),  # "This" network (RFC 1122)
    ipaddress.IPv4Network("10.0.0.0/8"),  # Private (RFC 1918)
    ipaddress.IPv4Network("100.64.0.0/10"),  # CGNAT (RFC 6598) — includes Alibaba metadata
    ipaddress.IPv4Network("127.0.0.0/8"),  # Loopback (RFC 1122)
    ipaddress.IPv4Network("169.254.0.0/16"),  # Link-local (RFC 3927) — includes cloud metadata
    ipaddress.IPv4Network("172.16.0.0/12"),  # Private (RFC 1918)
    ipaddress.IPv4Network("192.0.0.0/29"),  # IETF protocol assignments (RFC 6890)
    ipaddress.IPv4Network("192.0.2.0/24"),  # Documentation TEST-NET-1 (RFC 5737)
    ipaddress.IPv4Network("192.88.99.0/24"),  # 6to4 relay anycast (RFC 7526)
    ipaddress.IPv4Network("192.168.0.0/16"),  # Private (RFC 1918)
    ipaddress.IPv4Network("198.18.0.0/15"),  # Benchmarking (RFC 2544)
    ipaddress.IPv4Network("198.51.100.0/24"),  # Documentation TEST-NET-2 (RFC 5737)
    ipaddress.IPv4Network("203.0.113.0/24"),  # Documentation TEST-NET-3 (RFC 5737)
    ipaddress.IPv4Network("224.0.0.0/4"),  # Multicast (RFC 5771)
    ipaddress.IPv4Network("240.0.0.0/4"),  # Reserved for future use (RFC 1112)
    ipaddress.IPv4Network("255.255.255.255/32"),  # Broadcast
    # --- IPv6 ---
    ipaddress.IPv6Network("::1/128"),  # Loopback
    ipaddress.IPv6Network("fe80::/10"),  # Link-local
    ipaddress.IPv6Network("fc00::/7"),  # Unique local address (RFC 4193)
    ipaddress.IPv6Network("2002::/16"),  # 6to4 — can embed private IPv4 (RFC 3056)
    ipaddress.IPv6Network("2001:db8::/32"),  # Documentation (RFC 3849)
    ipaddress.IPv6Network("ff00::/8"),  # Multicast
    ipaddress.IPv6Network("100::/64"),  # Discard-only (RFC 6666)
    ipaddress.IPv6Network("fec0::/10"),  # Site-local (deprecated, RFC 3879)
)

# Cloud metadata endpoint IPs — always blocked regardless of any future
# "allow local" option, since leaking cloud credentials is catastrophic.
CLOUD_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS, GCP, Azure metadata
        "fd00:ec2::254",  # AWS EC2 IPv6 metadata
        "100.100.100.200",  # Alibaba Cloud metadata
    }
)


def _is_blocked_ip(ip_str: str) -> bool:
    """Check whether a resolved IP address falls in a blocked range.

    Handles IPv4-mapped IPv6 addresses (e.g. ``::ffff:192.168.1.1``) by
    unwrapping them before checking against the IPv4 blocked networks.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Unparseable → treat as blocked to be safe.
        return True

    # Always block cloud metadata endpoints.
    if ip_str in CLOUD_METADATA_IPS:
        return True

    # Unwrap IPv4-mapped IPv6 so that e.g. ::ffff:127.0.0.1 is caught.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    return any(ip in network for network in BLOCKED_NETWORKS)


def is_public_url(url: str) -> bool:
    """Validate that a URL points to a public (non-private) resource.

    Prevents SSRF attacks by checking:

    * Only ``http`` and ``https`` schemes are allowed.
    * The hostname must resolve to at least one IP address.
    * Every resolved IP address must be on the public internet
      (not in any :data:`BLOCKED_NETWORKS` range).
    * Cloud metadata endpoints are always blocked.
    * IPv4-mapped IPv6 addresses are unwrapped and checked.

    Returns ``True`` if the URL is safe to fetch, ``False`` otherwise.
    Logs a warning for every rejection.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.warning("URL scheme '%s' not allowed (only http/https permitted)", parsed.scheme)
        return False
    if not parsed.hostname:
        logger.warning("URL has no hostname")
        return False

    hostname = parsed.hostname
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
        for addrinfo in addrinfos:
            sockaddr = addrinfo[4]
            ip = str(sockaddr[0])
            if _is_blocked_ip(ip):
                logger.warning(
                    "URL hostname '%s' resolves to restricted IP address: %s",
                    hostname,
                    ip,
                )
                return False
        return True
    except socket.gaierror:
        logger.warning("Unable to resolve hostname: %s", hostname)
        return False
    except ValueError as e:
        logger.warning("Error validating URL '%s': %s", url, e)
        return False
    except Exception as e:
        logger.exception("Unexpected error validating URL '%s': %s", url, e)
        raise
