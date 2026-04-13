"""Tests for the sunstone.ssrf module."""

import socket
from unittest.mock import patch

import pytest

from sunstone.ssrf import BLOCKED_NETWORKS, CLOUD_METADATA_IPS, _is_blocked_ip, is_public_url


def mock_getaddrinfo(ip: str):
    """Return a mock getaddrinfo result for a single IP."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


class TestIsBlockedIp:
    """Unit tests for _is_blocked_ip."""

    @pytest.mark.parametrize(
        "ip",
        [
            "93.184.216.34",  # example.com
            "8.8.8.8",  # Google DNS
            "1.1.1.1",  # Cloudflare DNS
            "2606:4700::1111",  # Cloudflare IPv6
        ],
    )
    def test_public_ips_not_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is False

    # --- IPv4 private ranges ---
    @pytest.mark.parametrize(
        "ip",
        [
            "0.0.0.1",  # "This" network
            "10.0.0.1",  # RFC 1918
            "10.255.255.255",
            "172.16.0.1",  # RFC 1918
            "172.31.255.255",
            "192.168.0.1",  # RFC 1918
            "192.168.255.255",
            "127.0.0.1",  # Loopback
            "127.255.255.255",
            "169.254.1.1",  # Link-local
        ],
    )
    def test_standard_private_ipv4_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- CGNAT ---
    @pytest.mark.parametrize("ip", ["100.64.0.1", "100.127.255.255"])
    def test_cgnat_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- Cloud metadata ---
    @pytest.mark.parametrize("ip", sorted(CLOUD_METADATA_IPS))
    def test_cloud_metadata_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- Documentation / reserved ---
    @pytest.mark.parametrize(
        "ip",
        [
            "192.0.0.1",  # IETF protocol assignments
            "192.0.2.1",  # TEST-NET-1
            "192.88.99.1",  # 6to4 relay
            "198.18.0.1",  # Benchmarking
            "198.51.100.1",  # TEST-NET-2
            "203.0.113.1",  # TEST-NET-3
        ],
    )
    def test_documentation_reserved_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- Multicast / future-reserved ---
    @pytest.mark.parametrize("ip", ["224.0.0.1", "239.255.255.255", "240.0.0.1", "255.255.255.255"])
    def test_multicast_and_reserved_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- IPv6 ---
    @pytest.mark.parametrize(
        "ip",
        [
            "::1",  # Loopback
            "fe80::1",  # Link-local
            "fc00::1",  # Unique local
            "fd12:3456:789a::1",  # Unique local
            "2002::1",  # 6to4
            "2001:db8::1",  # Documentation
            "ff02::1",  # Multicast
            "fec0::1",  # Site-local (deprecated)
            "100::1",  # Discard-only
        ],
    )
    def test_blocked_ipv6(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    # --- IPv4-mapped IPv6 bypass ---
    @pytest.mark.parametrize(
        "ip",
        [
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "::ffff:192.168.1.1",
            "::ffff:169.254.169.254",
        ],
    )
    def test_ipv4_mapped_ipv6_blocked(self, ip: str) -> None:
        assert _is_blocked_ip(ip) is True

    def test_ipv4_mapped_ipv6_public_allowed(self) -> None:
        assert _is_blocked_ip("::ffff:93.184.216.34") is False

    def test_unparseable_ip_blocked(self) -> None:
        assert _is_blocked_ip("not-an-ip") is True


class TestIsPublicUrl:
    """Integration tests for is_public_url."""

    def test_public_url_allowed(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("93.184.216.34")):
            assert is_public_url("https://example.com/data.csv") is True

    def test_non_http_scheme_blocked(self) -> None:
        assert is_public_url("file:///etc/passwd") is False
        assert is_public_url("ftp://example.com/data") is False
        assert is_public_url("gopher://example.com/") is False

    def test_no_hostname_blocked(self) -> None:
        assert is_public_url("http:///no-host") is False

    def test_private_ip_blocked(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("192.168.1.1")):
            assert is_public_url("http://internal.example.com/api") is False

    def test_cloud_metadata_blocked(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
            assert is_public_url("http://169.254.169.254/latest/meta-data/") is False

    def test_dns_failure_blocked(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=socket.gaierror("DNS failure")):
            assert is_public_url("http://nonexistent.invalid/data") is False

    def test_value_error_blocked(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=ValueError("bad")):
            assert is_public_url("https://example.com/data") is False

    def test_unexpected_exception_reraised(self) -> None:
        with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=RuntimeError("unexpected")):
            with pytest.raises(RuntimeError, match="unexpected"):
                is_public_url("https://example.com/data")


class TestBlockedNetworksCoverage:
    """Verify BLOCKED_NETWORKS covers the expected number of ranges."""

    def test_has_ipv4_and_ipv6_ranges(self) -> None:
        import ipaddress

        ipv4_count = sum(1 for n in BLOCKED_NETWORKS if isinstance(n, ipaddress.IPv4Network))
        ipv6_count = sum(1 for n in BLOCKED_NETWORKS if isinstance(n, ipaddress.IPv6Network))
        assert ipv4_count >= 15
        assert ipv6_count >= 7
