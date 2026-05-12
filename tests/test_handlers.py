"""Tests for internal plugin handlers."""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sunstone.handlers import (
    BuiltinFormatHandler,
    HttpURLHandler,
    LocalFileHandler,
    ParquetFormatHandler,
    MAX_RESPONSE_SIZE,
    _read_response_with_limit,
)
from sunstone.ssrf import is_public_url


@pytest.fixture
def handler():
    return BuiltinFormatHandler()


class TestBuiltinFormatHandlerCanRead:
    def test_csv(self, handler):
        assert handler.can_read("data.csv", None)

    def test_csv_with_format(self, handler):
        assert handler.can_read("data.whatever", "csv")

    def test_json(self, handler):
        assert handler.can_read("data.json", None)

    def test_excel_xlsx(self, handler):
        assert handler.can_read("data.xlsx", None)

    def test_excel_xls(self, handler):
        assert handler.can_read("data.xls", None)

    def test_parquet_not_handled(self, handler):
        assert not handler.can_read("data.parquet", None)

    def test_tsv(self, handler):
        assert handler.can_read("data.tsv", None)

    def test_txt_as_tsv(self, handler):
        assert handler.can_read("data.txt", None)

    def test_unknown_extension(self, handler):
        assert not handler.can_read("data.hdf5", None)

    def test_unknown_format_string(self, handler):
        assert not handler.can_read("data.whatever", "hdf5")

    def test_url_path(self, handler):
        assert handler.can_read("gs://bucket/data.csv", None)

    def test_url_path_with_format(self, handler):
        assert handler.can_read("gs://bucket/data.whatever", "csv")


class TestBuiltinFormatHandlerCanWrite:
    def test_csv(self, handler):
        assert handler.can_write("data.csv", None)

    def test_csv_with_format(self, handler):
        assert handler.can_write("data.whatever", "csv")

    def test_unknown(self, handler):
        assert not handler.can_write("data.hdf5", None)


class TestBuiltinFormatHandlerRead:
    def test_read_csv(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_csv_with_format(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream, format="csv")
        assert list(df.columns) == ["a", "b"]

    def test_read_tsv_with_format(self, handler):
        stream = io.BytesIO(b"a\tb\n1\t2\n3\t4\n")
        df = handler.read(stream, format="tsv")
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_json(self, handler):
        stream = io.BytesIO(b'[{"a": 1, "b": 2}]')
        df = handler.read(stream, format="json")
        assert list(df.columns) == ["a", "b"]

    def test_read_with_path_kwarg(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream, path="data.csv")
        assert list(df.columns) == ["a", "b"]

    def test_read_passes_kwargs(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream, format="csv", usecols=["a"])
        assert list(df.columns) == ["a"]


class TestBuiltinFormatHandlerWrite:
    def test_write_csv(self, handler):
        stream = io.BytesIO()
        df = pd.DataFrame({"x": [1, 2]})
        handler.write(df, stream, index=False)
        stream.seek(0)
        result = pd.read_csv(stream)
        assert list(result.columns) == ["x"]
        assert len(result) == 2


class TestBuiltinFormatHandlerCsvDialect:
    """Dialect translation for text/csv read and write."""

    def test_read_uses_dialect_delimiter(self, handler):
        from sunstone.lineage import CsvDialect

        stream = io.BytesIO(b"a;b\n1;2\n3;4\n")
        df = handler.read(stream, format="csv", dialect=CsvDialect(delimiter=";"))
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_dialect_header_false_skips_header_row(self, handler):
        from sunstone.lineage import CsvDialect

        stream = io.BytesIO(b"1,2\n3,4\n")
        df = handler.read(stream, format="csv", dialect=CsvDialect(header=False))
        assert list(df.columns) == [0, 1]
        assert len(df) == 2

    def test_read_explicit_kwargs_win_over_dialect(self, handler):
        from sunstone.lineage import CsvDialect

        stream = io.BytesIO(b"a,b\n1,2\n")
        df = handler.read(stream, format="csv", sep=",", dialect=CsvDialect(delimiter=";"))
        assert list(df.columns) == ["a", "b"]

    def test_read_dialect_is_ignored_for_non_csv(self, handler):
        from sunstone.lineage import CsvDialect

        # JSON path must ignore dialect entirely (no kwarg leak to pd.read_json)
        stream = io.BytesIO(b'[{"a": 1, "b": 2}]')
        df = handler.read(stream, format="json", dialect=CsvDialect(delimiter=";"))
        assert list(df.columns) == ["a", "b"]

    def test_write_uses_dialect_delimiter(self, handler):
        from sunstone.lineage import CsvDialect

        stream = io.BytesIO()
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        handler.write(stream=stream, df=df, format="csv", index=False, dialect=CsvDialect(delimiter=";"))
        stream.seek(0)
        assert stream.read() == b"a;b\n1;3\n2;4\n"

    def test_write_dialect_header_false_omits_header(self, handler):
        from sunstone.lineage import CsvDialect

        stream = io.BytesIO()
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        handler.write(stream=stream, df=df, format="csv", index=False, dialect=CsvDialect(header=False))
        stream.seek(0)
        assert stream.read() == b"1,3\n2,4\n"

    def test_dialect_none_is_no_op(self, handler):
        # Passing dialect=None must not change default pandas behavior
        stream = io.BytesIO(b"a,b\n1,2\n")
        df = handler.read(stream, format="csv", dialect=None)
        assert list(df.columns) == ["a", "b"]


class TestBuiltinFormatHandlerParquetNoLongerHandled:
    """Verify that BuiltinFormatHandler no longer handles Parquet."""

    def test_cannot_write_parquet(self) -> None:
        handler = BuiltinFormatHandler()
        assert handler.can_write("output.parquet", None) is False

    def test_cannot_write_parquet_explicit_format(self) -> None:
        handler = BuiltinFormatHandler()
        assert handler.can_write("output.dat", "parquet") is False


class TestSupportsMetadata:
    """Test supports_metadata() on format handlers."""

    def test_builtin_does_not_support_metadata(self) -> None:
        assert BuiltinFormatHandler().supports_metadata() is False

    def test_parquet_supports_metadata(self) -> None:
        assert ParquetFormatHandler().supports_metadata() is True


class TestParquetFormatHandler:
    """Tests for the ParquetFormatHandler."""

    @pytest.fixture
    def handler(self):
        return ParquetFormatHandler()

    def test_can_read_parquet(self, handler):
        assert handler.can_read("data.parquet", None)

    def test_can_read_parquet_explicit_format(self, handler):
        assert handler.can_read("data.whatever", "parquet")

    def test_can_write_parquet(self, handler):
        assert handler.can_write("output.parquet", None)

    def test_can_write_parquet_explicit_format(self, handler):
        assert handler.can_write("output.dat", "parquet")

    def test_cannot_read_csv(self, handler):
        assert not handler.can_read("data.csv", None)

    def test_cannot_write_csv(self, handler):
        assert not handler.can_write("data.csv", None)

    def test_read_parquet_basic(self, handler, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        with open(path, "rb") as f:
            df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 3

    def test_write_parquet_basic(self, handler, tmp_path):
        import pyarrow.parquet as pq

        df = pd.DataFrame({"x": [10, 20], "y": ["a", "b"]})
        path = tmp_path / "out.parquet"
        with open(path, "wb") as f:
            handler.write(df, f)

        table = pq.read_table(path)
        result = table.to_pandas()
        assert list(result.columns) == ["x", "y"]
        assert len(result) == 2

    def test_write_embeds_metadata(self, handler, tmp_path):
        import pyarrow.parquet as pq

        from sunstone.lineage import Metadata

        meta = Metadata()
        meta.slug = "test-dataset"
        meta.name = "Test Dataset"
        meta.description = "A test"

        df = pd.DataFrame({"col": [1, 2, 3]})
        df.attrs["sunstone_metadata"] = meta

        path = tmp_path / "meta.parquet"
        with open(path, "wb") as f:
            handler.write(df, f)

        # Verify the b"sunstone" key exists in Parquet schema metadata
        pf = pq.ParquetFile(path)
        schema_meta = pf.schema_arrow.metadata
        assert b"sunstone" in schema_meta

    def test_read_extracts_metadata(self, handler, tmp_path):
        import json
        import pyarrow as pa
        import pyarrow.parquet as pq

        from sunstone.lineage import Metadata

        # Create metadata and serialize to JSON-LD
        meta = Metadata()
        meta.slug = "round-trip"
        meta.name = "Round Trip"
        meta.description = "Testing round-trip"
        doc = meta.to_jsonld()

        # Write a parquet file with sunstone metadata in footer
        table = pa.table({"val": [100, 200]})
        table = table.replace_schema_metadata(
            {
                b"sunstone": json.dumps(doc).encode("utf-8"),
            }
        )
        path = tmp_path / "with_meta.parquet"
        pq.write_table(table, path)

        # Read back via handler
        with open(path, "rb") as f:
            df = handler.read(f)

        assert "sunstone_metadata" in df.attrs
        restored = df.attrs["sunstone_metadata"]
        assert isinstance(restored, Metadata)
        assert restored.slug == "round-trip"
        assert restored.name == "Round Trip"

    def test_read_without_metadata(self, handler, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({"a": [1]})
        path = tmp_path / "plain.parquet"
        pq.write_table(table, path)

        with open(path, "rb") as f:
            df = handler.read(f)
        assert "sunstone_metadata" not in df.attrs


@pytest.fixture
def http_handler():
    return HttpURLHandler()


class TestHttpURLHandlerCanHandle:
    def test_http(self, http_handler):
        assert http_handler.can_handle("http://example.com/data.csv")

    def test_https(self, http_handler):
        assert http_handler.can_handle("https://example.com/data.csv")

    def test_s3(self, http_handler):
        assert not http_handler.can_handle("s3://bucket/data.csv")

    def test_gs(self, http_handler):
        assert not http_handler.can_handle("gs://bucket/data.csv")

    def test_ftp(self, http_handler):
        assert not http_handler.can_handle("ftp://example.com/data.csv")

    def test_bare_path(self, http_handler):
        assert not http_handler.can_handle("/local/path/data.csv")

    def test_relative_path(self, http_handler):
        assert not http_handler.can_handle("data.csv")


class TestHttpURLHandlerOpen:
    def _make_mock_response(self, data: bytes, status: int = 200, headers: dict | None = None):
        """Create a mock HTTP response with proper streaming read behavior."""
        mock = MagicMock()
        mock.status = status
        # Make read() behave like a stream: return data then empty bytes
        stream = io.BytesIO(data)
        mock.read = stream.read
        mock.headers = headers or {}
        return mock

    def test_read_binary(self, http_handler):
        mock_response = self._make_mock_response(b"a,b\n1,2\n")
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            stream = http_handler.open("https://example.com/data.csv", "rb")
            assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, http_handler):
        mock_response = self._make_mock_response(b"a,b\n1,2\n")
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            stream = http_handler.open("https://example.com/data.csv", "r")
            assert stream.read() == "a,b\n1,2\n"

    def test_write_raises(self, http_handler):
        with pytest.raises(NotImplementedError):
            http_handler.open("https://example.com/data.csv", "wb")

    def test_rejects_private_url(self, http_handler):
        with patch("sunstone.handlers.is_public_url", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                http_handler.open("http://192.168.1.1/data.csv", "rb")

    def test_follows_redirects(self, http_handler):
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "https://cdn.example.com/data.csv"}
        final_response = self._make_mock_response(b"a,b\n1,2\n")
        mock_opener = MagicMock()
        mock_opener.open.side_effect = [redirect_response, final_response]

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            stream = http_handler.open("https://example.com/redirect", "rb")
            assert stream.read() == b"a,b\n1,2\n"

    def test_strips_auth_on_cross_origin_redirect(self, http_handler):
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "https://other.com/data.csv"}
        final_response = self._make_mock_response(b"data")
        mock_opener = MagicMock()
        mock_opener.open.side_effect = [redirect_response, final_response]

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            http_handler.open("https://example.com/data.csv", "rb", headers={"Authorization": "Bearer secret"})
            # Second call should not have Authorization header
            second_request = mock_opener.open.call_args_list[1][0][0]
            assert "Authorization" not in second_request.headers

    def test_too_many_redirects(self, http_handler):
        http_handler = HttpURLHandler(max_redirects=1)
        redirect_responses = []
        for _ in range(2):
            response = MagicMock()
            response.status = 302
            response.headers = {"Location": "https://example.com/loop"}
            redirect_responses.append(response)
        mock_opener = MagicMock()
        mock_opener.open.side_effect = redirect_responses

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            with pytest.raises(ValueError, match="Too many redirects"):
                http_handler.open("https://example.com/data.csv", "rb")


class TestHttpResponseSizeLimits:
    """Tests for response size enforcement."""

    def test_content_length_above_cap_rejected(self):
        """Response with Content-Length exceeding MAX_RESPONSE_SIZE is rejected."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": str(MAX_RESPONSE_SIZE + 1)}
        mock_response.read.return_value = b""

        with pytest.raises(ValueError, match="Content-Length.*exceeds maximum"):
            _read_response_with_limit(mock_response, MAX_RESPONSE_SIZE)

    def test_content_length_within_cap_allowed(self):
        """Response with Content-Length within limit proceeds normally."""
        data = b"hello world"
        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": str(len(data))}
        stream = io.BytesIO(data)
        mock_response.read = stream.read

        result = _read_response_with_limit(mock_response, MAX_RESPONSE_SIZE)
        assert result == data

    def test_streaming_above_cap_rejected(self):
        """Response without Content-Length that exceeds limit during streaming is rejected."""
        small_limit = 100
        # Generate data larger than the limit
        data = b"x" * (small_limit + 50)
        mock_response = MagicMock()
        mock_response.headers = {}
        stream = io.BytesIO(data)
        mock_response.read = stream.read

        with pytest.raises(ValueError, match="exceeds maximum allowed size"):
            _read_response_with_limit(mock_response, small_limit)

    def test_handler_rejects_large_content_length(self):
        """HttpURLHandler rejects responses with Content-Length above its cap."""
        handler = HttpURLHandler(max_response_size=1024)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Length": "2048"}
        mock_response.read.return_value = b""
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            with pytest.raises(ValueError, match="Content-Length.*exceeds maximum"):
                handler.open("https://example.com/large.bin", "rb")

    def test_handler_rejects_streaming_overflow(self):
        """HttpURLHandler rejects responses that exceed limit during streaming."""
        handler = HttpURLHandler(max_response_size=100)

        data = b"x" * 200
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        stream = io.BytesIO(data)
        mock_response.read = stream.read
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            with pytest.raises(ValueError, match="exceeds maximum allowed size"):
                handler.open("https://example.com/large.bin", "rb")


class TestMetadataEndpointBlocking:
    """Tests for cloud metadata endpoint blocking."""

    def test_blocks_metadata_ip(self):
        """169.254.169.254 is blocked even before DNS resolution."""
        with patch("sunstone.ssrf.socket.getaddrinfo") as mock_dns:
            # Should not even reach DNS resolution
            assert not is_public_url("http://169.254.169.254/latest/meta-data/")
            mock_dns.assert_not_called()

    def test_blocks_metadata_google_internal(self):
        """metadata.google.internal is blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo") as mock_dns:
            assert not is_public_url("http://metadata.google.internal/computeMetadata/v1/")
            mock_dns.assert_not_called()

    def test_blocks_metadata_goog(self):
        """metadata.goog is blocked."""
        with patch("sunstone.ssrf.socket.getaddrinfo") as mock_dns:
            assert not is_public_url("http://metadata.goog/computeMetadata/v1/")
            mock_dns.assert_not_called()

    def test_handler_rejects_metadata_ip(self):
        """HttpURLHandler rejects metadata IP address."""
        handler = HttpURLHandler()
        with pytest.raises(ValueError, match="not allowed"):
            handler.open("http://169.254.169.254/latest/meta-data/", "rb")

    def test_handler_rejects_metadata_hostname(self):
        """HttpURLHandler rejects metadata hostname."""
        handler = HttpURLHandler()
        with pytest.raises(ValueError, match="not allowed"):
            handler.open("http://metadata.google.internal/computeMetadata/v1/", "rb")


class TestDnsRebindingProtection:
    """Tests for DNS TOCTOU mitigation via IP-pinned connections."""

    def test_connects_to_resolved_ip(self):
        """Handler rewrites URL to use resolved IP and sets Host header."""
        handler = HttpURLHandler()

        data = b"ok"
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        stream = io.BytesIO(data)
        mock_response.read = stream.read
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        resolved_ip = "93.184.216.34"
        with (
            patch("sunstone.handlers.is_public_url", return_value=True),
            patch(
                "sunstone.handlers._resolve_and_validate",
                return_value=[(None, None, None, None, (resolved_ip, 0))],
            ),
            patch("sunstone.handlers.build_opener", return_value=mock_opener),
        ):
            handler.open("https://example.com/data.csv", "rb")
            request = mock_opener.open.call_args[0][0]
            # URL should contain the resolved IP
            assert resolved_ip in request.full_url
            # Host header should be preserved
            assert request.get_header("Host") == "example.com"


@pytest.fixture
def local_handler():
    return LocalFileHandler()


class TestLocalFileHandlerCanHandle:
    def test_bare_relative_path(self, local_handler):
        assert local_handler.can_handle("data.csv")

    def test_bare_absolute_path(self, local_handler):
        assert local_handler.can_handle("/tmp/data.csv")

    def test_file_scheme(self, local_handler):
        assert local_handler.can_handle("file:///tmp/data.csv")

    def test_windows_drive_path(self, local_handler):
        assert local_handler.can_handle("C:\\Users\\data.csv")

    def test_http_scheme(self, local_handler):
        assert not local_handler.can_handle("http://example.com/data.csv")

    def test_gs_scheme(self, local_handler):
        assert not local_handler.can_handle("gs://bucket/data.csv")

    def test_s3_scheme(self, local_handler):
        assert not local_handler.can_handle("s3://bucket/data.csv")

    def test_r2_scheme(self, local_handler):
        assert not local_handler.can_handle("r2://bucket/data.csv")


class TestLocalFileHandlerOpen:
    def test_read_binary(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_bytes(b"a,b\n1,2\n")
        with local_handler.open(str(f), "rb") as stream:
            assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        with local_handler.open(str(f), "r") as stream:
            assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, local_handler, tmp_path):
        f = tmp_path / "out.csv"
        with local_handler.open(str(f), "wb") as stream:
            stream.write(b"a,b\n1,2\n")
        assert f.read_bytes() == b"a,b\n1,2\n"

    def test_write_text(self, local_handler, tmp_path):
        f = tmp_path / "out.csv"
        with local_handler.open(str(f), "w") as stream:
            stream.write("a,b\n1,2\n")
        assert f.read_text() == "a,b\n1,2\n"

    def test_file_scheme(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_bytes(b"a,b\n1,2\n")
        file_url = f.as_uri()  # produces correct file:///... on all platforms
        with local_handler.open(file_url, "rb") as stream:
            assert stream.read() == b"a,b\n1,2\n"

    def test_creates_parent_dirs_on_write(self, local_handler, tmp_path):
        f = tmp_path / "sub" / "dir" / "out.csv"
        with local_handler.open(str(f), "wb") as stream:
            stream.write(b"data")
        assert f.read_bytes() == b"data"


@pytest.mark.filterwarnings("ignore:fetch_from_url is deprecated:DeprecationWarning")
def test_fetch_from_url_delegates_auth_to_http_handler(tmp_path):
    """Auth providers set headers on the HttpURLHandler before fetch."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Test Dataset\n"
        "    slug: test-dataset\n"
        "    location: inputs/test.csv\n"
        "    source:\n"
        "      name: Test Source\n"
        "      location:\n"
        "        data: https://example.com/test.csv\n"
        "      attributedTo: Test Org\n"
        "      acquiredAt: '2026-01-01'\n"
        "      acquisitionMethod: manual-download\n"
        "      license: CC-BY-4.0\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()

    from sunstone.datasets import DatasetsManager
    from sunstone.plugins import PluginRegistry

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_slug("test-dataset")

    class TestAuth:
        def authenticate(self, url, headers, dataset):
            headers["Authorization"] = "Bearer test-token"
            return headers

    handler = HttpURLHandler()
    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())
    registry._url_handlers.append(handler)

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers = {}
    _stream = io.BytesIO(b"col1,col2\na,b\n")
    mock_response.read = _stream.read
    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.handlers.is_public_url", return_value=True),
        patch("sunstone.handlers._resolve_and_validate", return_value=[(None, None, None, None, ("93.184.216.34", 0))]),
        patch("sunstone.handlers.build_opener", return_value=mock_opener),
    ):
        manager.fetch_from_url(dataset, force=True)
        request_obj = mock_opener.open.call_args[0][0]
        assert request_obj.get_header("Authorization") == "Bearer test-token"
