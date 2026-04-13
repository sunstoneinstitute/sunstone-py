"""
Tests for Sunstone DatasetsManager functionality.
"""

import socket
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Any


import pytest
import sunstone
from sunstone.ssrf import is_public_url


def _make_response(status: int, location: str | None = None, content: bytes = b"test data") -> MagicMock:
    """Create a mock urllib response object."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.headers = {}
    if location is not None:
        mock_resp.headers["Location"] = location
    mock_resp.read.return_value = content
    return mock_resp


def _make_ok_response(content: bytes = b"test data") -> unittest.mock.Mock:
    """Create a mock urlopen response for a successful (200) request."""
    return _make_response(200, content=content)


def mock_getaddrinfo(ip: str) -> list[tuple[Any, ...]]:
    """Create a mock getaddrinfo return value for a given IP address."""
    if ":" in ip:  # IPv6
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0))]
    else:  # IPv4
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]


class TestDatasetsManager:
    """Tests for DatasetsManager class."""

    def test_load_datasets_manager(self, project_path: Path) -> None:
        """Test loading datasets manager from project path."""
        manager = sunstone.DatasetsManager(project_path)
        assert manager is not None

    def test_find_dataset_by_slug(self, project_path: Path) -> None:
        """Test finding a dataset by its slug."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        assert dataset is not None
        assert dataset.name == "Official UN Member States"
        assert dataset.slug == "official-un-member-states"
        assert dataset.location is not None
        assert dataset.fields is not None and len(dataset.fields) > 0
        if dataset.source:
            assert dataset.source.license is not None

    def test_find_nonexistent_dataset(self, project_path: Path) -> None:
        """Test that finding a non-existent dataset returns None."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("does-not-exist")
        assert dataset is None


class TestFieldSchemaExtendedProperties:
    """Tests for field-level description, unit, and source."""

    def test_parse_fields_with_description(self, project_copy: Path) -> None:
        """Test that field description is parsed from datasets.yaml."""
        yaml_path = project_copy / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "  - name: Member State\n        type: string",
            '  - name: Member State\n        type: string\n        description: "Name of the UN member state"',
        )
        yaml_path.write_text(content)

        manager = sunstone.DatasetsManager(project_copy)
        dataset = manager.find_dataset_by_slug("official-un-member-states")
        assert dataset is not None
        assert dataset.fields is not None
        member_state_field = next(f for f in dataset.fields if f.name == "Member State")
        assert member_state_field.description == "Name of the UN member state"

    def test_parse_fields_with_unit(self, project_copy: Path) -> None:
        """Test that field unit is parsed from datasets.yaml."""
        yaml_path = project_copy / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "  - name: M49 Code\n        type: string",
            '  - name: M49 Code\n        type: string\n        unit: "code"',
        )
        yaml_path.write_text(content)

        manager = sunstone.DatasetsManager(project_copy)
        dataset = manager.find_dataset_by_slug("official-un-member-states")
        assert dataset is not None
        assert dataset.fields is not None
        m49_field = next(f for f in dataset.fields if f.name == "M49 Code")
        assert m49_field.unit == "code"

    def test_parse_fields_with_source(self, project_copy: Path) -> None:
        """Test that field source is parsed from datasets.yaml."""
        yaml_path = project_copy / "datasets.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "  - name: ISO Code\n        type: string",
            '  - name: ISO Code\n        type: string\n        source: "iso-standards"',
        )
        yaml_path.write_text(content)

        manager = sunstone.DatasetsManager(project_copy)
        dataset = manager.find_dataset_by_slug("official-un-member-states")
        assert dataset is not None
        assert dataset.fields is not None
        iso_field = next(f for f in dataset.fields if f.name == "ISO Code")
        assert iso_field.source == "iso-standards"

    def test_parse_fields_without_extended_properties(self, project_path: Path) -> None:
        """Test that fields without new properties default to None."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")
        assert dataset is not None
        assert dataset.fields is not None
        field = dataset.fields[0]
        assert field.description is None
        assert field.unit is None
        assert field.source is None


class TestFieldSchemaSerialization:
    """Tests for field schema serialization helper."""

    def test_field_to_dict_minimal(self) -> None:
        """Test serialization with only required fields."""
        from sunstone.datasets import _field_schema_to_dict
        from sunstone.lineage import FieldSchema

        field = FieldSchema(name="x", type="string")
        d = _field_schema_to_dict(field)
        assert d == {"name": "x", "type": "string"}

    def test_field_to_dict_all_properties(self) -> None:
        """Test serialization with all properties set."""
        from sunstone.datasets import _field_schema_to_dict
        from sunstone.lineage import FieldSchema

        field = FieldSchema(
            name="population",
            type="integer",
            description="Total population",
            unit="people",
            source="census-data",
            constraints={"minimum": 0},
        )
        d = _field_schema_to_dict(field)
        assert d == {
            "name": "population",
            "type": "integer",
            "constraints": {"minimum": 0},
            "description": "Total population",
            "unit": "people",
            "source": "census-data",
        }

    def test_field_to_dict_omits_none(self) -> None:
        """Test that None values are omitted from serialization."""
        from sunstone.datasets import _field_schema_to_dict
        from sunstone.lineage import FieldSchema

        field = FieldSchema(name="x", type="string", description="A field")
        d = _field_schema_to_dict(field)
        assert "unit" not in d
        assert "source" not in d
        assert "constraints" not in d
        assert d["description"] == "A field"


class TestPackageMetadata:
    """Tests for package metadata parsing."""

    def test_get_package_metadata(self, project_path: Path) -> None:
        """Test getting package metadata from datasets.yaml."""
        manager = sunstone.DatasetsManager(project_path)
        package = manager.get_package_metadata()

        assert package is not None
        assert package.title == "UN Member States Dataset"
        assert package.version == "1.0.0"
        assert package.license == "CC-BY-4.0"

    def test_package_description(self, project_path: Path) -> None:
        """Test that package description is parsed correctly."""
        manager = sunstone.DatasetsManager(project_path)
        package = manager.get_package_metadata()

        assert package is not None
        assert package.description is not None
        assert "UN Member States" in package.description

    def test_package_keywords(self, project_path: Path) -> None:
        """Test that package keywords are parsed correctly."""
        manager = sunstone.DatasetsManager(project_path)
        package = manager.get_package_metadata()

        assert package is not None
        assert package.keywords is not None
        assert "united-nations" in package.keywords
        assert "member-states" in package.keywords

    def test_package_contributors(self, project_path: Path) -> None:
        """Test that package contributors are parsed correctly."""
        manager = sunstone.DatasetsManager(project_path)
        package = manager.get_package_metadata()

        assert package is not None
        assert package.contributors is not None
        assert len(package.contributors) == 1

        contributor = package.contributors[0]
        assert contributor.title == "Sunstone Institute"
        assert contributor.roles is not None
        assert "creator" in contributor.roles
        assert "publisher" in contributor.roles

    def test_package_metadata_none_when_missing(self, tmp_path: Path) -> None:
        """Test that get_package_metadata returns None when no package section exists."""
        # Create a minimal datasets.yaml without package section
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text("""
inputs: []
outputs: []
""")
        manager = sunstone.DatasetsManager(tmp_path)
        package = manager.get_package_metadata()

        assert package is None


class TestURLSafety:
    """Tests for URL safety validation (SSRF prevention)."""

    def test_valid_https_url(self) -> None:
        """Test that valid HTTPS URLs to public addresses are allowed."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("93.184.216.34")):
            assert is_public_url("https://example.com/data.csv") is True
            assert is_public_url("https://www.google.com/file.json") is True

    def test_valid_http_url(self) -> None:
        """Test that valid HTTP URLs to public addresses are allowed."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("93.184.216.34")):
            assert is_public_url("http://example.com/data.csv") is True

    def test_file_scheme_blocked(self) -> None:
        """Test that file:// URLs are blocked."""
        assert is_public_url("file:///etc/passwd") is False
        assert is_public_url("file:///tmp/data.csv") is False

    def test_ftp_scheme_blocked(self) -> None:
        """Test that FTP URLs are blocked."""
        assert is_public_url("ftp://example.com/data.csv") is False

    def test_localhost_blocked(self) -> None:
        """Test that localhost URLs are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.1")):
            assert is_public_url("http://localhost/api") is False
            assert is_public_url("http://localhost:8080/data") is False

    def test_loopback_ip_blocked(self) -> None:
        """Test that loopback IP addresses are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.1")):
            assert is_public_url("http://127.0.0.1/api") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.2")):
            assert is_public_url("http://127.0.0.2:8080/data") is False

    def test_private_ip_10_blocked(self) -> None:
        """Test that private IP addresses (10.x.x.x) are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("10.0.0.1")):
            assert is_public_url("http://internal.example.com/api") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("10.255.255.254")):
            assert is_public_url("http://10.255.255.254/data") is False

    def test_private_ip_192_168_blocked(self) -> None:
        """Test that private IP addresses (192.168.x.x) are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("192.168.1.1")):
            assert is_public_url("http://router.local/config") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("192.168.100.50")):
            assert is_public_url("http://192.168.100.50/api") is False

    def test_private_ip_172_16_blocked(self) -> None:
        """Test that private IP addresses (172.16-31.x.x) are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("172.16.0.1")):
            assert is_public_url("http://internal-app.local/data") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("172.31.255.255")):
            assert is_public_url("http://172.31.255.255/api") is False

    def test_link_local_blocked(self) -> None:
        """Test that link-local addresses (169.254.x.x) are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
            assert is_public_url("http://169.254.169.254/metadata") is False

    def test_cloud_metadata_endpoint_blocked(self) -> None:
        """Test that AWS/GCP cloud metadata endpoints are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
            assert is_public_url("http://169.254.169.254/latest/meta-data/") is False

    def test_ipv6_loopback_blocked(self) -> None:
        """Test that IPv6 loopback address (::1) is blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("::1")):
            assert is_public_url("http://localhost/api") is False
            assert is_public_url("http://[::1]/api") is False
            assert is_public_url("http://[::1]:8080/data") is False

    def test_ipv6_link_local_blocked(self) -> None:
        """Test that IPv6 link-local addresses (fe80::) are blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("fe80::1")):
            assert is_public_url("http://ipv6-link-local.example.com/data") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("fe80::1234:5678:abcd:ef01")):
            assert is_public_url("http://[fe80::1234:5678:abcd:ef01]/api") is False

    def test_ipv6_unique_local_blocked(self) -> None:
        """Test that IPv6 unique local addresses (fc00::/7, including fd00::) are blocked."""
        # fc00:: prefix (unique local, not yet assigned)
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("fc00::1")):
            assert is_public_url("http://internal-ipv6.example.com/data") is False
        # fd00:: prefix (unique local, commonly used for private networks)
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("fd00::1")):
            assert is_public_url("http://private-ipv6.example.com/api") is False
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("fd12:3456:789a::1")):
            assert is_public_url("http://[fd12:3456:789a::1]:8080/data") is False

    def test_dns_resolution_failure(self) -> None:
        """Test that URLs with unresolvable hostnames are blocked."""
        with patch(
            "sunstone.ssrf.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS lookup failed"),
        ):
            assert is_public_url("http://nonexistent-domain-xyz123.com/data") is False

    def test_decimal_ip_representation_blocked(self) -> None:
        """Test that decimal IP representations (e.g., 2130706433 = 127.0.0.1) are blocked.

        An attacker might try to bypass SSRF protection using decimal IP notation.
        socket.getaddrinfo() correctly resolves these to the actual IP address.
        """
        # 2130706433 is the decimal representation of 127.0.0.1
        # getaddrinfo resolves this to the actual IP, which should be blocked
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.1")):
            assert is_public_url("http://2130706433/api") is False

        # 3232235777 is the decimal representation of 192.168.1.1
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("192.168.1.1")):
            assert is_public_url("http://3232235777/data") is False

        # 2851995649 is the decimal representation of 169.254.169.254 (cloud metadata)
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
            assert is_public_url("http://2851995649/latest/meta-data/") is False

    def test_hex_ip_representation_blocked(self) -> None:
        """Test that hexadecimal IP representations (e.g., 0x7f000001 = 127.0.0.1) are blocked.

        An attacker might try to bypass SSRF protection using hex IP notation.
        socket.getaddrinfo() correctly resolves these to the actual IP address.
        """
        # 0x7f000001 is the hex representation of 127.0.0.1
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.1")):
            assert is_public_url("http://0x7f000001/api") is False

        # 0xc0a80101 is the hex representation of 192.168.1.1
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("192.168.1.1")):
            assert is_public_url("http://0xc0a80101/data") is False

        # 0xa9fea9fe is the hex representation of 169.254.169.254
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
            assert is_public_url("http://0xa9fea9fe/metadata") is False

    def test_mixed_notation_ip_blocked(self) -> None:
        """Test that mixed notation IPs are blocked.

        Some systems accept mixed decimal/hex/octal notation like 127.0.0.1
        represented as 0x7f.0.0.1 or similar variations.
        """
        # Various representations that resolve to loopback
        with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("127.0.0.1")):
            assert is_public_url("http://0x7f.0.0.1/api") is False
            assert is_public_url("http://127.0x0.0.1/data") is False

    def test_url_without_hostname(self) -> None:
        """Test that URLs without hostnames are blocked."""
        assert is_public_url("http:///no-host") is False

    def test_fetch_from_url_with_ssrf_attempt(self, project_path: Path) -> None:
        """Test that fetch_from_url raises ValueError for SSRF attempts."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Mock the source URL to point to a private IP
            dataset.source.location.data = "http://169.254.169.254/metadata"

            # Mock DNS resolution to return the link-local IP
            with patch("sunstone.ssrf.socket.getaddrinfo", return_value=mock_getaddrinfo("169.254.169.254")):
                with pytest.raises(ValueError, match="not allowed"):
                    manager.fetch_from_url(dataset, force=True)

    def test_fetch_from_url_with_file_scheme(self, project_path: Path) -> None:
        """Test that fetch_from_url raises ValueError for file:// URLs."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Mock the source URL to use file:// scheme
            dataset.source.location.data = "file:///etc/passwd"

            with pytest.raises(ValueError, match="No URL handler found"):
                manager.fetch_from_url(dataset, force=True)


class TestRedirectSSRFProtection:
    """Tests for HTTP redirect SSRF protection."""

    def test_redirect_to_private_ip_blocked(self, project_path: Path) -> None:
        """Test that redirects to private IPs are blocked (SSRF bypass prevention)."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Start with a valid public URL
            dataset.source.location.data = "https://example.com/data.csv"

            # Mock DNS resolution: initial URL resolves to public, redirect to private
            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                if "example.com" in hostname:
                    return mock_getaddrinfo("93.184.216.34")  # Public IP for example.com
                elif "evil-internal" in hostname:
                    return mock_getaddrinfo("192.168.1.1")  # Private IP
                raise socket.gaierror("Unknown host")

            redirect_response = _make_response(302, "http://evil-internal.local/metadata")
            mock_opener = MagicMock()
            mock_opener.open.return_value = redirect_response

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_localhost_blocked(self, project_path: Path) -> None:
        """Test that redirects to localhost are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                if "example.com" in hostname:
                    return mock_getaddrinfo("93.184.216.34")
                elif hostname == "localhost":
                    return mock_getaddrinfo("127.0.0.1")
                raise socket.gaierror("Unknown host")

            redirect_response = _make_response(302, "http://localhost/admin")
            mock_opener = MagicMock()
            mock_opener.open.return_value = redirect_response

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_cloud_metadata_blocked(self, project_path: Path) -> None:
        """Test that redirects to cloud metadata endpoints are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                if "example.com" in hostname:
                    return mock_getaddrinfo("93.184.216.34")
                elif hostname == "169.254.169.254":
                    return mock_getaddrinfo("169.254.169.254")
                raise socket.gaierror("Unknown host")

            redirect_response = _make_response(302, "http://169.254.169.254/latest/meta-data/")
            mock_opener = MagicMock()
            mock_opener.open.return_value = redirect_response

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_public_url_allowed(self, project_path: Path) -> None:
        """Test that redirects to other public URLs are allowed."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/old-path"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                # Both URLs resolve to public IPs
                return mock_getaddrinfo("93.184.216.34")

            redirect_response = _make_response(302, "https://example.com/new-path")
            ok_response = _make_ok_response(b"test data")
            mock_opener = MagicMock()
            mock_opener.open.side_effect = [redirect_response, ok_response]

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    # Mock file writing to avoid modifying test input files
                    with patch("builtins.open", unittest.mock.mock_open()):
                        # Should succeed without raising an error
                        result = manager.fetch_from_url(dataset, force=True)
                        assert result is not None

    def test_too_many_redirects_blocked(self, project_path: Path) -> None:
        """Test that too many redirects are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                return mock_getaddrinfo("93.184.216.34")  # All public IPs

            # HttpURLHandler.max_redirects defaults to 10; loop exits after 11 redirects
            redirect_responses = [_make_response(302, "https://example.com/redirect-loop") for _ in range(12)]
            mock_opener = MagicMock()
            mock_opener.open.side_effect = redirect_responses

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="Too many redirects"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_without_location_header_blocked(self, project_path: Path) -> None:
        """Test that redirects without Location header are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                return mock_getaddrinfo("93.184.216.34")

            # Redirect with no Location header
            redirect_response = _make_response(302, None)
            mock_opener = MagicMock()
            mock_opener.open.return_value = redirect_response

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="Location header"):
                        manager.fetch_from_url(dataset, force=True)

    def test_redirect_to_file_scheme_blocked(self, project_path: Path) -> None:
        """Test that redirects to file:// URLs are blocked."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                return mock_getaddrinfo("93.184.216.34")

            redirect_response = _make_response(302, "file:///etc/passwd")
            mock_opener = MagicMock()
            mock_opener.open.return_value = redirect_response

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    with pytest.raises(ValueError, match="not allowed"):
                        manager.fetch_from_url(dataset, force=True)

    def test_relative_redirect_url_resolved(self, project_path: Path) -> None:
        """Test that relative redirect URLs are properly resolved."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            dataset.source.location.data = "https://example.com/old/data.csv"

            def dns_side_effect(hostname: str, port: Any) -> list[tuple[Any, ...]]:
                return mock_getaddrinfo("93.184.216.34")  # Public IP

            redirect_response = _make_response(302, "../new/data.csv")
            ok_response = _make_ok_response(b"test data")
            mock_opener = MagicMock()
            mock_opener.open.side_effect = [redirect_response, ok_response]

            with patch("sunstone.ssrf.socket.getaddrinfo", side_effect=dns_side_effect):
                with patch("sunstone.handlers.build_opener", return_value=mock_opener):
                    # Mock file writing to avoid modifying test input files
                    with patch("builtins.open", unittest.mock.mock_open()):
                        result = manager.fetch_from_url(dataset, force=True)
                        assert result is not None
                        # Verify the relative URL was resolved to the correct absolute URL
                        # The second call should be to the resolved URL: https://example.com/new/data.csv
                        assert mock_opener.open.call_count == 2
                        second_call_request = mock_opener.open.call_args_list[1][0][0]
                        assert second_call_request.full_url == "https://example.com/new/data.csv"
