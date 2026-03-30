"""Tests for internal plugin handlers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sunstone.handlers import BuiltinFormatHandler, HttpURLHandler


@pytest.fixture
def handler():
    return BuiltinFormatHandler()


class TestBuiltinFormatHandlerCanRead:
    def test_csv(self, handler):
        assert handler.can_read(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_read(Path("data.whatever"), "csv")

    def test_json(self, handler):
        assert handler.can_read(Path("data.json"), None)

    def test_excel_xlsx(self, handler):
        assert handler.can_read(Path("data.xlsx"), None)

    def test_excel_xls(self, handler):
        assert handler.can_read(Path("data.xls"), None)

    def test_parquet(self, handler):
        assert handler.can_read(Path("data.parquet"), None)

    def test_tsv(self, handler):
        assert handler.can_read(Path("data.tsv"), None)

    def test_txt_as_tsv(self, handler):
        assert handler.can_read(Path("data.txt"), None)

    def test_unknown_extension(self, handler):
        assert not handler.can_read(Path("data.hdf5"), None)

    def test_unknown_format_string(self, handler):
        assert not handler.can_read(Path("data.whatever"), "hdf5")


class TestBuiltinFormatHandlerCanWrite:
    def test_csv(self, handler):
        assert handler.can_write(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_write(Path("data.whatever"), "csv")

    def test_unknown(self, handler):
        assert not handler.can_write(Path("data.hdf5"), None)


class TestBuiltinFormatHandlerRead:
    def test_read_csv(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_tsv(self, handler, tmp_path):
        f = tmp_path / "data.tsv"
        f.write_text("a\tb\n1\t2\n3\t4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_txt_as_tsv(self, handler, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("a\tb\n1\t2\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_json(self, handler, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('[{"a": 1, "b": 2}]')
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_parquet(self, handler, tmp_path):
        f = tmp_path / "data.parquet"
        pd.DataFrame({"a": [1], "b": [2]}).to_parquet(f)
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_passes_kwargs(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f, usecols=["a"])
        assert list(df.columns) == ["a"]


class TestBuiltinFormatHandlerWrite:
    def test_write_csv(self, handler, tmp_path):
        f = tmp_path / "out.csv"
        df = pd.DataFrame({"x": [1, 2]})
        handler.write(df, f, index=False)
        result = pd.read_csv(f)
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


class TestHttpURLHandlerFetch:
    def test_fetches_to_dest(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.content = b"a,b\n1,2\n"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", return_value=mock_response),
        ):
            result = http_handler.fetch("https://example.com/data.csv", dest)
            assert result == dest
            assert dest.read_bytes() == b"a,b\n1,2\n"

    def test_rejects_private_url(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        with patch("sunstone.handlers._is_public_url", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                http_handler.fetch("http://192.168.1.1/data.csv", dest)

    def test_follows_redirects(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://cdn.example.com/data.csv"}

        final_response = MagicMock()
        final_response.is_redirect = False
        final_response.content = b"a,b\n1,2\n"
        final_response.raise_for_status = MagicMock()

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", side_effect=[redirect_response, final_response]),
        ):
            result = http_handler.fetch("https://example.com/redirect", dest)
            assert result == dest

    def test_strips_auth_on_cross_origin_redirect(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"

        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://other.com/data.csv"}

        final_response = MagicMock()
        final_response.is_redirect = False
        final_response.content = b"data"
        final_response.raise_for_status = MagicMock()

        http_handler.headers = {"Authorization": "Bearer secret"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", side_effect=[redirect_response, final_response]) as mock_get,
        ):
            http_handler.fetch("https://example.com/data.csv", dest)
            # Second call (redirect) should not have Authorization header
            second_call_headers = mock_get.call_args_list[1][1]["headers"]
            assert "Authorization" not in second_call_headers

    def test_too_many_redirects(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://example.com/loop"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", return_value=redirect_response),
        ):
            with pytest.raises(ValueError, match="Too many redirects"):
                http_handler.fetch("https://example.com/data.csv", dest)


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

    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())
    registry._url_handlers.append(HttpURLHandler())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.handlers._is_public_url", return_value=True),
        patch("sunstone.handlers.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
