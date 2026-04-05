"""Tests for internal plugin handlers."""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sunstone.handlers import BuiltinFormatHandler, HttpURLHandler, LocalFileHandler


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

    def test_parquet(self, handler):
        assert handler.can_read("data.parquet", None)

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

    def test_read_parquet(self, handler, tmp_path):
        f = tmp_path / "data.parquet"
        pd.DataFrame({"a": [1], "b": [2]}).to_parquet(f)
        stream = io.BytesIO(f.read_bytes())
        df = handler.read(stream, format="parquet")
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
    def test_read_binary(self, http_handler):
        mock_response = MagicMock()
        mock_response.read.return_value = b"a,b\n1,2\n"

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", return_value=mock_response),
        ):
            stream = http_handler.open("https://example.com/data.csv", "rb")
            assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, http_handler):
        mock_response = MagicMock()
        mock_response.read.return_value = b"a,b\n1,2\n"

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", return_value=mock_response),
        ):
            stream = http_handler.open("https://example.com/data.csv", "r")
            assert stream.read() == "a,b\n1,2\n"

    def test_write_raises(self, http_handler):
        with pytest.raises(NotImplementedError):
            http_handler.open("https://example.com/data.csv", "wb")

    def test_rejects_private_url(self, http_handler):
        with patch("sunstone.handlers._is_public_url", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                http_handler.open("http://192.168.1.1/data.csv", "rb")

    def test_follows_redirects(self, http_handler):
        from urllib.error import HTTPError as UrllibHTTPError

        redirect_error = UrllibHTTPError(
            "https://example.com/data.csv",
            302,
            "Found",
            {"Location": "https://cdn.example.com/data.csv"},
            io.BytesIO(b""),
        )
        final_response = MagicMock()
        final_response.read.return_value = b"a,b\n1,2\n"

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", side_effect=[redirect_error, final_response]),
        ):
            stream = http_handler.open("https://example.com/redirect", "rb")
            assert stream.read() == b"a,b\n1,2\n"

    def test_strips_auth_on_cross_origin_redirect(self, http_handler):
        from urllib.error import HTTPError as UrllibHTTPError

        redirect_error = UrllibHTTPError(
            "https://example.com/data.csv", 302, "Found", {"Location": "https://other.com/data.csv"}, io.BytesIO(b"")
        )
        final_response = MagicMock()
        final_response.read.return_value = b"data"

        http_handler.headers = {"Authorization": "Bearer secret"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", side_effect=[redirect_error, final_response]) as mock_urlopen,
        ):
            http_handler.open("https://example.com/data.csv", "rb")
            # Second call should not have Authorization header
            second_request = mock_urlopen.call_args_list[1][0][0]
            assert "Authorization" not in second_request.headers

    def test_too_many_redirects(self, http_handler):
        from urllib.error import HTTPError as UrllibHTTPError

        redirect_error = UrllibHTTPError(
            "https://example.com/loop", 302, "Found", {"Location": "https://example.com/loop"}, io.BytesIO(b"")
        )

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", side_effect=redirect_error),
        ):
            with pytest.raises(ValueError, match="Too many redirects"):
                http_handler.open("https://example.com/data.csv", "rb")


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
    mock_response.read.return_value = b"col1,col2\na,b\n"

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.handlers._is_public_url", return_value=True),
        patch("sunstone.handlers.urlopen", return_value=mock_response) as mock_urlopen,
    ):
        manager.fetch_from_url(dataset, force=True)
        request_obj = mock_urlopen.call_args[0][0]
        assert request_obj.get_header("Authorization") == "Bearer test-token"
