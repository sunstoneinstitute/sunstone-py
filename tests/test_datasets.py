"""
Tests for Sunstone DatasetsManager functionality.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import sunstone
from sunstone.datasets import _is_safe_url


class TestDatasetsManager:
    """Tests for DatasetsManager class."""

    def test_load_datasets_manager(self, project_path: Path):
        """Test loading datasets manager from project path."""
        manager = sunstone.DatasetsManager(project_path)
        assert manager is not None

    def test_find_dataset_by_slug(self, project_path: Path):
        """Test finding a dataset by its slug."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        assert dataset is not None
        assert dataset.name == "Official UN Member States"
        assert dataset.slug == "official-un-member-states"
        assert dataset.location is not None
        assert len(dataset.fields) > 0
        if dataset.source:
            assert dataset.source.license is not None

    def test_find_nonexistent_dataset(self, project_path: Path):
        """Test that finding a non-existent dataset returns None."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("does-not-exist")
        assert dataset is None


class TestURLSafety:
    """Tests for URL safety validation (SSRF prevention)."""

    def test_valid_https_url(self):
        """Test that valid HTTPS URLs to public addresses are allowed."""
        assert _is_safe_url("https://example.com/data.csv") is True
        assert _is_safe_url("https://www.google.com/file.json") is True

    def test_valid_http_url(self):
        """Test that valid HTTP URLs to public addresses are allowed."""
        assert _is_safe_url("http://example.com/data.csv") is True

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked."""
        assert _is_safe_url("file:///etc/passwd") is False
        assert _is_safe_url("file:///tmp/data.csv") is False

    def test_ftp_scheme_blocked(self):
        """Test that FTP URLs are blocked."""
        assert _is_safe_url("ftp://example.com/data.csv") is False

    def test_localhost_blocked(self):
        """Test that localhost URLs are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.1"):
            assert _is_safe_url("http://localhost/api") is False
            assert _is_safe_url("http://localhost:8080/data") is False

    def test_loopback_ip_blocked(self):
        """Test that loopback IP addresses are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.1"):
            assert _is_safe_url("http://127.0.0.1/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.2"):
            assert _is_safe_url("http://127.0.0.2:8080/data") is False

    def test_private_ip_10_blocked(self):
        """Test that private IP addresses (10.x.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="10.0.0.1"):
            assert _is_safe_url("http://internal.example.com/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="10.255.255.254"):
            assert _is_safe_url("http://10.255.255.254/data") is False

    def test_private_ip_192_168_blocked(self):
        """Test that private IP addresses (192.168.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="192.168.1.1"):
            assert _is_safe_url("http://router.local/config") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="192.168.100.50"):
            assert _is_safe_url("http://192.168.100.50/api") is False

    def test_private_ip_172_16_blocked(self):
        """Test that private IP addresses (172.16-31.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="172.16.0.1"):
            assert _is_safe_url("http://internal-app.local/data") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="172.31.255.255"):
            assert _is_safe_url("http://172.31.255.255/api") is False

    def test_link_local_blocked(self):
        """Test that link-local addresses (169.254.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="169.254.169.254"):
            assert _is_safe_url("http://169.254.169.254/metadata") is False

    def test_cloud_metadata_endpoint_blocked(self):
        """Test that AWS/GCP cloud metadata endpoints are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="169.254.169.254"):
            assert _is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_ipv6_loopback_blocked(self):
        """Test that IPv6 loopback address (::1) is blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="::1"):
            assert _is_safe_url("http://localhost/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="::1"):
            assert _is_safe_url("http://[::1]/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="::1"):
            assert _is_safe_url("http://[::1]:8080/data") is False

    def test_ipv6_link_local_blocked(self):
        """Test that IPv6 link-local addresses (fe80::) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fe80::1"):
            assert _is_safe_url("http://ipv6-link-local.example.com/data") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fe80::1234:5678:abcd:ef01"):
            assert _is_safe_url("http://[fe80::1234:5678:abcd:ef01]/api") is False

    def test_ipv6_unique_local_blocked(self):
        """Test that IPv6 unique local addresses (fc00::/7, including fd00::) are blocked."""
        # fc00:: prefix (unique local, not yet assigned)
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fc00::1"):
            assert _is_safe_url("http://internal-ipv6.example.com/data") is False
        # fd00:: prefix (unique local, commonly used for private networks)
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fd00::1"):
            assert _is_safe_url("http://private-ipv6.example.com/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fd12:3456:789a::1"):
            assert _is_safe_url("http://[fd12:3456:789a::1]:8080/data") is False

    def test_dns_resolution_failure(self):
        """Test that URLs with unresolvable hostnames are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", side_effect=Exception("DNS lookup failed")):
            assert _is_safe_url("http://nonexistent-domain-xyz123.com/data") is False

    def test_url_without_hostname(self):
        """Test that URLs without hostnames are blocked."""
        assert _is_safe_url("http:///no-host") is False

    def test_fetch_from_url_with_ssrf_attempt(self, project_path: Path):
        """Test that fetch_from_url raises ValueError for SSRF attempts."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Mock the source URL to point to a private IP
            dataset.source.location.data = "http://169.254.169.254/metadata"

            # Mock DNS resolution to return the link-local IP
            with patch("sunstone.datasets.socket.gethostbyname", return_value="169.254.169.254"):
                with pytest.raises(ValueError, match="not allowed"):
                    manager.fetch_from_url(dataset, force=True)

    def test_fetch_from_url_with_file_scheme(self, project_path: Path):
        """Test that fetch_from_url raises ValueError for file:// URLs."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Mock the source URL to use file:// scheme
            dataset.source.location.data = "file:///etc/passwd"

            with pytest.raises(ValueError, match="not allowed"):
                manager.fetch_from_url(dataset, force=True)
