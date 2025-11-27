"""
Tests for Sunstone DatasetsManager functionality.
"""

import socket
import unittest.mock
from pathlib import Path
from unittest.mock import patch


import pytest
import sunstone
from sunstone.datasets import _is_public_url


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
        with patch("sunstone.datasets.socket.gethostbyname", return_value="93.184.216.34"):
            assert _is_public_url("https://example.com/data.csv") is True
            assert _is_public_url("https://www.google.com/file.json") is True

    def test_valid_http_url(self):
        """Test that valid HTTP URLs to public addresses are allowed."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="93.184.216.34"):
            assert _is_public_url("http://example.com/data.csv") is True

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked."""
        assert _is_public_url("file:///etc/passwd") is False
        assert _is_public_url("file:///tmp/data.csv") is False

    def test_ftp_scheme_blocked(self):
        """Test that FTP URLs are blocked."""
        assert _is_public_url("ftp://example.com/data.csv") is False

    def test_localhost_blocked(self):
        """Test that localhost URLs are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.1"):
            assert _is_public_url("http://localhost/api") is False
            assert _is_public_url("http://localhost:8080/data") is False

    def test_loopback_ip_blocked(self):
        """Test that loopback IP addresses are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.1"):
            assert _is_public_url("http://127.0.0.1/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="127.0.0.2"):
            assert _is_public_url("http://127.0.0.2:8080/data") is False

    def test_private_ip_10_blocked(self):
        """Test that private IP addresses (10.x.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="10.0.0.1"):
            assert _is_public_url("http://internal.example.com/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="10.255.255.254"):
            assert _is_public_url("http://10.255.255.254/data") is False

    def test_private_ip_192_168_blocked(self):
        """Test that private IP addresses (192.168.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="192.168.1.1"):
            assert _is_public_url("http://router.local/config") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="192.168.100.50"):
            assert _is_public_url("http://192.168.100.50/api") is False

    def test_private_ip_172_16_blocked(self):
        """Test that private IP addresses (172.16-31.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="172.16.0.1"):
            assert _is_public_url("http://internal-app.local/data") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="172.31.255.255"):
            assert _is_public_url("http://172.31.255.255/api") is False

    def test_link_local_blocked(self):
        """Test that link-local addresses (169.254.x.x) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="169.254.169.254"):
            assert _is_public_url("http://169.254.169.254/metadata") is False

    def test_cloud_metadata_endpoint_blocked(self):
        """Test that AWS/GCP cloud metadata endpoints are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="169.254.169.254"):
            assert _is_public_url("http://169.254.169.254/latest/meta-data/") is False

    def test_ipv6_loopback_blocked(self):
        """Test that IPv6 loopback address (::1) is blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="::1"):
            assert _is_public_url("http://localhost/api") is False
            assert _is_public_url("http://[::1]/api") is False
            assert _is_public_url("http://[::1]:8080/data") is False

    def test_ipv6_link_local_blocked(self):
        """Test that IPv6 link-local addresses (fe80::) are blocked."""
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fe80::1"):
            assert _is_public_url("http://ipv6-link-local.example.com/data") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fe80::1234:5678:abcd:ef01"):
            assert _is_public_url("http://[fe80::1234:5678:abcd:ef01]/api") is False

    def test_ipv6_unique_local_blocked(self):
        """Test that IPv6 unique local addresses (fc00::/7, including fd00::) are blocked."""
        # fc00:: prefix (unique local, not yet assigned)
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fc00::1"):
            assert _is_public_url("http://internal-ipv6.example.com/data") is False
        # fd00:: prefix (unique local, commonly used for private networks)
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fd00::1"):
            assert _is_public_url("http://private-ipv6.example.com/api") is False
        with patch("sunstone.datasets.socket.gethostbyname", return_value="fd12:3456:789a::1"):
            assert _is_public_url("http://[fd12:3456:789a::1]:8080/data") is False

    def test_dns_resolution_failure(self):
        """Test that URLs with unresolvable hostnames are blocked."""
        with patch(
            "sunstone.datasets.socket.gethostbyname",
            side_effect=socket.gaierror("DNS lookup failed"),
        ):
            assert _is_public_url("http://nonexistent-domain-xyz123.com/data") is False

    def test_url_without_hostname(self):
        """Test that URLs without hostnames are blocked."""
        assert _is_public_url("http:///no-host") is False

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


class TestRedirectSSRFProtection:
    """Tests for HTTP redirect SSRF protection."""

    def test_redirect_to_private_ip_blocked(self, project_path: Path):
        """Test that redirects to private IPs are blocked (SSRF bypass prevention)."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Start with a valid public URL
            dataset.source.location.data = "https://example.com/data.csv"

            # Mock DNS resolution: initial URL resolves to public, redirect to private
            def dns_side_effect(hostname):
                if "example.com" in hostname:
                    return "93.184.216.34"  # Public IP for example.com
                elif "evil-internal" in hostname:
                    return "192.168.1.1"  # Private IP
                raise socket.gaierror("Unknown host")

            # Mock HTTP response with redirect to private IP
            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "http://evil-internal.local/metadata"}

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_localhost_blocked(self, project_path: Path):
        """Test that redirects to localhost are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname):
                if "example.com" in hostname:
                    return "93.184.216.34"
                elif hostname == "localhost":
                    return "127.0.0.1"
                raise socket.gaierror("Unknown host")

            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "http://localhost/admin"}

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_cloud_metadata_blocked(self, project_path: Path):
        """Test that redirects to cloud metadata endpoints are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname):
                if "example.com" in hostname:
                    return "93.184.216.34"
                elif hostname == "169.254.169.254":
                    return "169.254.169.254"
                raise socket.gaierror("Unknown host")

            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_public_url_allowed(self, project_path: Path):
        """Test that redirects to other public URLs are allowed."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/old-path"

            def dns_side_effect(hostname):
                # Both URLs resolve to public IPs
                return "93.184.216.34"

            # First call returns redirect, second call returns content
            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "https://example.com/new-path"}

            mock_final_response = unittest.mock.Mock()
            mock_final_response.is_redirect = False
            mock_final_response.status_code = 200
            mock_final_response.content = b"test data"
            mock_final_response.raise_for_status = unittest.mock.Mock()

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch(
                    "sunstone.datasets.requests.get",
                    side_effect=[mock_redirect_response, mock_final_response],
                ):
                    # Should succeed without raising an error
                    result = manager.fetch_from_url(dataset, force=True)
                    assert result.exists()

    def test_too_many_redirects_blocked(self, project_path: Path):
        """Test that too many redirects are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname):
                return "93.184.216.34"  # All public IPs

            # Always return redirect
            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "https://example.com/redirect-loop"}

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="Too many redirects"):
                        manager.fetch_from_url(dataset, force=True, max_redirects=5)

    def test_redirect_without_location_header_blocked(self, project_path: Path):
        """Test that redirects without Location header are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname):
                return "93.184.216.34"

            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {}  # No Location header

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="Location header"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_file_scheme_blocked(self, project_path: Path):
        """Test that redirects to file:// URLs are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname):
                return "93.184.216.34"

            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "file:///etc/passwd"}

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch("sunstone.datasets.requests.get", return_value=mock_redirect_response):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_relative_redirect_url_resolved(self, project_path: Path):
        """Test that relative redirect URLs are properly resolved."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/old/data.csv"

            def dns_side_effect(hostname):
                return "93.184.216.34"  # Public IP

            # First call returns redirect with relative URL, second call returns content
            mock_redirect_response = unittest.mock.Mock()
            mock_redirect_response.is_redirect = True
            mock_redirect_response.headers = {"Location": "../new/data.csv"}  # Relative URL

            mock_final_response = unittest.mock.Mock()
            mock_final_response.is_redirect = False
            mock_final_response.status_code = 200
            mock_final_response.content = b"test data"
            mock_final_response.raise_for_status = unittest.mock.Mock()

            with patch("sunstone.datasets.socket.gethostbyname", side_effect=dns_side_effect):
                with patch(
                    "sunstone.datasets.requests.get",
                    side_effect=[mock_redirect_response, mock_final_response],
                ) as mock_get:
                    result = manager.fetch_from_url(dataset, force=True)
                    assert result.exists()
                    # Verify the relative URL was resolved to the correct absolute URL
                    # The second call should be to the resolved URL: https://example.com/new/data.csv
                    assert mock_get.call_count == 2
                    second_call_url = mock_get.call_args_list[1][0][0]
                    assert second_call_url == "https://example.com/new/data.csv"
