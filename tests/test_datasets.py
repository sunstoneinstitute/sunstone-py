"""
Tests for Sunstone DatasetsManager functionality.
"""

import io
import socket
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Any


import pytest
import sunstone
from sunstone.ssrf import is_public_url


def _make_response(status: int, location: str | None = None, content: bytes = b"test data") -> MagicMock:
    """Create a mock urllib response object.

    For non-redirect responses, read() behaves as a stream (returns data once,
    then empty bytes) to work correctly with streaming size-limited reads.
    """
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.headers = {}
    if location is not None:
        mock_resp.headers["Location"] = location
    # Use stream-based read for non-redirect statuses to avoid infinite loops
    # with _read_response_with_limit's chunked reading.
    if status not in (301, 302, 303, 307, 308):
        stream = io.BytesIO(content)
        mock_resp.read = stream.read
    else:
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
        assert field.custom_properties is None

    def test_parse_fields_with_rdf_custom_properties(self, tmp_path: Path) -> None:
        """RDF property keys on a field are collected into custom_properties."""
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Nutrient Data\n"
            "    slug: nutrient-data\n"
            "    location: outputs/data.csv\n"
            "    fields:\n"
            "      - name: n_tonnes\n"
            "        type: number\n"
            "        unit: http://qudt.org/vocab/unit/TONNE\n"
            "        qudt:hasQuantityKind: http://qudt.org/vocab/quantitykind/Mass\n"
            "        sosa:observedProperty: http://vocab.nerc.ac.uk/collection/P01/current/TNITZZXX/\n"
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("nutrient-data")
        assert dataset is not None
        assert dataset.fields is not None
        field = next(f for f in dataset.fields if f.name == "n_tonnes")
        assert field.custom_properties == {
            "qudt:hasQuantityKind": "http://qudt.org/vocab/quantitykind/Mass",
            "sosa:observedProperty": "http://vocab.nerc.ac.uk/collection/P01/current/TNITZZXX/",
        }

    def test_parse_fields_ignores_non_rdf_unknown_keys(self, tmp_path: Path) -> None:
        """Unknown non-RDF keys are still ignored (leniency preserved)."""
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Data\n"
            "    slug: data\n"
            "    location: outputs/data.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: number\n"
            "        bogus: ignored\n"
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("data")
        assert dataset is not None
        assert dataset.fields is not None
        assert dataset.fields[0].custom_properties is None


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

    def test_field_to_dict_includes_custom_properties(self) -> None:
        """Field-level custom RDF properties are emitted for round-tripping."""
        from sunstone.datasets import _field_schema_to_dict
        from sunstone.lineage import FieldSchema

        field = FieldSchema(
            name="n_tonnes",
            type="number",
            custom_properties={"sosa:observedProperty": "http://example.org/total-n"},
        )
        d = _field_schema_to_dict(field)
        assert d["sosa:observedProperty"] == "http://example.org/total-n"

    def test_field_custom_properties_round_trip(self, tmp_path: Path) -> None:
        """A field custom property survives parse -> serialize unchanged."""
        from sunstone.datasets import _field_schema_to_dict

        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            "inputs: []\n"
            "outputs:\n"
            "  - name: Data\n"
            "    slug: data\n"
            "    location: outputs/data.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: number\n"
            "        sosa:observedProperty: http://example.org/total-n\n"
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("data")
        assert dataset is not None
        assert dataset.fields is not None
        d = _field_schema_to_dict(dataset.fields[0])
        assert d["sosa:observedProperty"] == "http://example.org/total-n"


class TestPackageMetadata:
    """Tests for package metadata parsing."""

    def test_get_package_metadata(self, project_path: Path) -> None:
        """Test getting package metadata from datasets.yaml."""
        manager = sunstone.DatasetsManager(project_path)
        package = manager.get_package_metadata()

        assert package is not None
        assert package.title == "UN Member States Dataset"
        assert package.version == "1.0.0"
        assert package.license == "CC-BY-NC-3.0-IGO"

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


class TestCsvDialect:
    """Tests for parsing and serializing the per-dataset CSV dialect block."""

    def test_dialect_absent_yields_none(self, tmp_path: Path) -> None:
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            """
inputs:
  - name: Sample
    slug: sample
    location: inputs/sample.csv
outputs: []
"""
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("sample")
        assert dataset is not None
        assert dataset.dialect is None

    def test_dialect_parses_semicolon_delimiter(self, tmp_path: Path) -> None:
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            """
inputs:
  - name: Sample
    slug: sample
    location: inputs/sample.csv
    dialect:
      delimiter: ";"
      quoteChar: "'"
      header: true
outputs: []
"""
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("sample")
        assert dataset is not None
        assert dataset.dialect is not None
        assert dataset.dialect.delimiter == ";"
        assert dataset.dialect.quote_char == "'"
        assert dataset.dialect.header is True

    def test_dialect_defaults_match_pandas(self, tmp_path: Path) -> None:
        """An empty dialect block parses with pandas-default values."""
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            """
inputs:
  - name: Sample
    slug: sample
    location: inputs/sample.csv
    dialect: {}
outputs: []
"""
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("sample")
        assert dataset is not None
        assert dataset.dialect is not None
        assert dataset.dialect.delimiter == ","
        assert dataset.dialect.quote_char == '"'
        assert dataset.dialect.header is True

    def test_dialect_header_false(self, tmp_path: Path) -> None:
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            """
inputs:
  - name: Sample
    slug: sample
    location: inputs/sample.csv
    dialect:
      header: false
outputs: []
"""
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("sample")
        assert dataset is not None and dataset.dialect is not None
        assert dataset.dialect.header is False

    def test_dialect_not_in_custom_properties(self, tmp_path: Path) -> None:
        """dialect is a standard field, not a custom RDF property."""
        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text(
            """
inputs:
  - name: Sample
    slug: sample
    location: inputs/sample.csv
    dialect:
      delimiter: ";"
outputs: []
"""
        )
        manager = sunstone.DatasetsManager(tmp_path)
        dataset = manager.find_dataset_by_slug("sample")
        assert dataset is not None
        assert dataset.custom_properties is None or "dialect" not in dataset.custom_properties

    def test_add_output_persists_dialect(self, tmp_path: Path) -> None:
        from sunstone.lineage import CsvDialect, FieldSchema

        datasets_file = tmp_path / "datasets.yaml"
        datasets_file.write_text("inputs: []\noutputs: []\n")
        manager = sunstone.DatasetsManager(tmp_path)

        manager.add_output_dataset(
            name="Out",
            slug="out",
            location="outputs/out.csv",
            fields=[FieldSchema(name="a", type="integer")],
            dialect=CsvDialect(delimiter=";", quote_char='"', header=True),
        )

        # Re-read the file from disk to verify it was persisted
        manager2 = sunstone.DatasetsManager(tmp_path)
        dataset = manager2.find_dataset_by_slug("out", "output")
        assert dataset is not None and dataset.dialect is not None
        assert dataset.dialect.delimiter == ";"
        assert dataset.dialect.quote_char == '"'


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

    @pytest.mark.filterwarnings("ignore:fetch_from_url is deprecated:DeprecationWarning")
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

    @pytest.mark.filterwarnings("ignore:fetch_from_url is deprecated:DeprecationWarning")
    def test_fetch_from_url_with_file_scheme(self, project_path: Path) -> None:
        """Test that fetch_from_url raises ValueError for file:// URLs."""
        manager = sunstone.DatasetsManager(project_path)
        dataset = manager.find_dataset_by_slug("official-un-member-states")

        if dataset and dataset.source:
            # Mock the source URL to use file:// scheme
            dataset.source.location.data = "file:///etc/passwd"

            with pytest.raises(ValueError, match="No URL handler found"):
                manager.fetch_from_url(dataset, force=True)


@pytest.mark.filterwarnings("ignore:fetch_from_url is deprecated:DeprecationWarning")
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
                        # The second call should be to the resolved URL with the IP
                        # (DNS rebinding protection rewrites hostname to resolved IP)
                        assert mock_opener.open.call_count == 2
                        second_call_request = mock_opener.open.call_args_list[1][0][0]
                        # URL is rewritten to use resolved IP; check path is correct
                        assert "/new/data.csv" in second_call_request.full_url
                        assert "93.184.216.34" in second_call_request.full_url


class TestGetPackages:
    """Tests for DatasetsManager.get_packages()."""

    def _make_manager(self, yaml_content: str, tmp_path: Path) -> "sunstone.datasets.DatasetsManager":
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(yaml_content)
        return sunstone.datasets.DatasetsManager(tmp_path, yaml_file)

    def test_singular_package(self, tmp_path: Path) -> None:
        """package: (singular) produces one PackageEntry with datasets=None."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: My Package\n"
            "  version: '1.0.0'\n"
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/test/\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].metadata.title == "My Package"
        assert packages[0].metadata.version == "1.0.0"
        assert packages[0].datasets is None
        assert packages[0].name is None
        assert packages[0].publish is not None
        assert packages[0].publish.enabled is True
        assert packages[0].publish.to == "gs://bucket/test/"

    def test_singular_package_no_publish(self, tmp_path: Path) -> None:
        """package: without top-level publish: still works."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: My Package\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].publish is None

    def test_no_package_or_packages(self, tmp_path: Path) -> None:
        """No package: or packages: returns empty list."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 0

    def test_plural_packages(self, tmp_path: Path) -> None:
        """packages: (plural) produces multiple PackageEntry objects."""
        (tmp_path / "a.csv").write_text("col\nval")
        (tmp_path / "b.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg-a\n"
            "    title: Package A\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/a/\n"
            "    datasets:\n"
            "      - dataset-a\n"
            "  - name: pkg-b\n"
            "    title: Package B\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/b/\n"
            "    datasets:\n"
            "      - dataset-b\n"
            "outputs:\n"
            "  - name: Dataset A\n"
            "    slug: dataset-a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Dataset B\n"
            "    slug: dataset-b\n"
            "    location: b.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 2
        assert packages[0].name == "pkg-a"
        assert packages[0].metadata.title == "Package A"
        assert packages[0].datasets == ["dataset-a"]
        assert packages[1].name == "pkg-b"
        assert packages[1].datasets == ["dataset-b"]

    def test_both_package_and_packages_is_error(self, tmp_path: Path) -> None:
        """Having both package: and packages: raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "package:\n"
            "  title: Singular\n"
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="Cannot use both.*package.*and.*packages"):
            mgr.get_packages()

    def test_packages_with_top_level_publish_is_error(self, tmp_path: Path) -> None:
        """packages: with top-level publish: raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "publish:\n"
            "  enabled: true\n"
            "  to: gs://bucket/\n"
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="top-level.*publish.*not allowed.*packages"):
            mgr.get_packages()

    def test_packages_invalid_slug_is_error(self, tmp_path: Path) -> None:
        """A datasets: slug that doesn't exist raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    datasets:\n"
            "      - nonexistent-slug\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="nonexistent-slug.*not found"):
            mgr.get_packages()

    def test_packages_missing_name_is_error(self, tmp_path: Path) -> None:
        """A packages: entry without name raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - title: No Name\n"
            "    datasets:\n"
            "      - test\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="name.*required"):
            mgr.get_packages()

    def test_packages_missing_datasets_is_error(self, tmp_path: Path) -> None:
        """A packages: entry without datasets raises ValueError."""
        (tmp_path / "test.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    title: No Datasets\n"
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        with pytest.raises(ValueError, match="datasets.*required"):
            mgr.get_packages()

    def test_packages_dataset_from_inputs(self, tmp_path: Path) -> None:
        """packages: can reference input dataset slugs."""
        (tmp_path / "input.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: pkg\n"
            "    title: With Input\n"
            "    datasets:\n"
            "      - my-input\n"
            "inputs:\n"
            "  - name: My Input\n"
            "    slug: my-input\n"
            "    location: input.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 1
        assert packages[0].datasets == ["my-input"]

    def test_dataset_in_multiple_packages(self, tmp_path: Path) -> None:
        """A dataset can appear in multiple packages (e.g. full and lite)."""
        (tmp_path / "shared.csv").write_text("col\nval")
        (tmp_path / "extra.csv").write_text("col\nval")
        mgr = self._make_manager(
            "packages:\n"
            "  - name: full\n"
            "    title: Full\n"
            "    datasets:\n"
            "      - shared\n"
            "      - extra\n"
            "  - name: lite\n"
            "    title: Lite\n"
            "    datasets:\n"
            "      - shared\n"
            "outputs:\n"
            "  - name: Shared\n"
            "    slug: shared\n"
            "    location: shared.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
            "  - name: Extra\n"
            "    slug: extra\n"
            "    location: extra.csv\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n",
            tmp_path,
        )
        packages = mgr.get_packages()
        assert len(packages) == 2
        assert packages[0].datasets == ["shared", "extra"]
        assert packages[1].datasets == ["shared"]


class TestMinSunstoneVersion:
    """Tests for min_sunstone_version checking and auto-bumping."""

    def test_load_with_compatible_version(self, tmp_path: Path) -> None:
        """datasets.yaml with a low min_sunstone_version loads successfully."""
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.dump(
            {"min_sunstone_version": "1.0.0", "inputs": [], "outputs": []},
            tmp_path / "datasets.yaml",
        )
        manager = sunstone.DatasetsManager(tmp_path)
        assert manager is not None

    def test_load_with_incompatible_version(self, tmp_path: Path) -> None:
        """datasets.yaml requiring a future version raises RuntimeError."""
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.dump(
            {"min_sunstone_version": "99.0.0", "inputs": [], "outputs": []},
            tmp_path / "datasets.yaml",
        )
        with pytest.raises(RuntimeError, match="requires sunstone-py >= 99.0.0"):
            sunstone.DatasetsManager(tmp_path)

    def test_load_without_version_field(self, tmp_path: Path) -> None:
        """datasets.yaml without min_sunstone_version loads successfully."""
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.dump({"inputs": [], "outputs": []}, tmp_path / "datasets.yaml")
        manager = sunstone.DatasetsManager(tmp_path)
        assert manager is not None

    def test_auto_bump_on_lock_write(self, tmp_path: Path) -> None:
        """update_output_lineage sets min_sunstone_version in datasets.yaml."""
        from ruamel.yaml import YAML

        from sunstone.datasets import DatasetsManager
        from sunstone.lineage import LineageMetadata

        yaml = YAML()
        yaml.dump(
            {
                "inputs": [],
                "outputs": [{"name": "Out", "slug": "out", "location": "outputs/out.csv"}],
            },
            tmp_path / "datasets.yaml",
        )

        manager = DatasetsManager(tmp_path)
        manager.update_output_lineage(
            slug="out",
            lineage=LineageMetadata(),
            data_hash="sha256:" + "a" * 64,
        )

        # Re-read datasets.yaml and check min_sunstone_version was set
        with open(tmp_path / "datasets.yaml") as f:
            data = yaml.load(f)
        assert data["min_sunstone_version"] is not None
        # Should be set to the current running version
        from importlib.metadata import version as pkg_version

        try:
            expected = pkg_version("sunstone-py")
        except Exception:
            expected = "1.8.0"
        assert data["min_sunstone_version"] == expected


class TestPerDatasetPublishDeprecation:
    """Test that per-dataset publish: emits a deprecation warning."""

    def test_warns_on_per_dataset_publish(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "datasets.yaml"
        yaml_file.write_text(
            "outputs:\n"
            "  - name: Test\n"
            "    slug: test\n"
            "    location: test.csv\n"
            "    publish:\n"
            "      enabled: true\n"
            "      to: gs://bucket/test/\n"
            "    fields:\n"
            "      - name: col\n"
            "        type: string\n"
        )
        (tmp_path / "test.csv").write_text("col\nval")
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from sunstone.datasets import DatasetsManager

            mgr = DatasetsManager(tmp_path, yaml_file)
            mgr.get_all_outputs()
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 1
            assert "publish" in str(deprecation_warnings[0].message).lower()
            assert "packages:" in str(deprecation_warnings[0].message)
