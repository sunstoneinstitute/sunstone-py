"""Tests for GCS URL handler (mocked — no real GCS calls)."""

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_gcs_storage(monkeypatch):
    """Inject a fake ``google.cloud.storage`` module whose ``Client`` raises
    on instantiation, mimicking ``DefaultCredentialsError`` in a credential-less
    environment. Lets us assert the handler never constructs a client eagerly.
    """
    storage = types.ModuleType("google.cloud.storage")

    def _client_factory(*args, **kwargs):
        raise AssertionError("storage.Client() must not be constructed eagerly")

    storage.Client = MagicMock(side_effect=_client_factory)

    # Build the package chain google -> google.cloud -> google.cloud.storage
    google_mod = sys.modules.get("google") or types.ModuleType("google")
    cloud_mod = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
    cloud_mod.storage = storage
    google_mod.cloud = cloud_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_mod)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage)
    return storage


@pytest.fixture
def gcs_handler():
    from sunstone.handlers_gcs import GcsURLHandler

    handler = GcsURLHandler.__new__(GcsURLHandler)
    handler._client = MagicMock()
    return handler


class TestGcsURLHandlerCanHandle:
    def test_gs_scheme(self, gcs_handler):
        assert gcs_handler.can_handle("gs://bucket/path/data.csv")

    def test_http_scheme(self, gcs_handler):
        assert not gcs_handler.can_handle("http://example.com/data.csv")

    def test_s3_scheme(self, gcs_handler):
        assert not gcs_handler.can_handle("s3://bucket/data.csv")

    def test_local_path(self, gcs_handler):
        assert not gcs_handler.can_handle("data.csv")


class TestGcsURLHandlerOpen:
    def test_read_binary(self, gcs_handler):
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"a,b\n1,2\n"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/data.csv", "rb")
        assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, gcs_handler):
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"a,b\n1,2\n"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/data.csv", "r")
        assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, gcs_handler):
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/out.csv", "wb")
        stream.write(b"a,b\n1,2\n")
        stream.close()

        mock_blob.upload_from_file.assert_called_once()

    def test_write_text(self, gcs_handler):
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/out.csv", "w")
        stream.write("a,b\n1,2\n")
        stream.close()

        mock_blob.upload_from_file.assert_called_once()


class TestGcsURLHandlerLazyAuth:
    """Regression tests: constructing the handler must not touch GCP credentials.

    Eager ``storage.Client()`` in ``__init__`` calls ``google.auth.default()``,
    which raises ``DefaultCredentialsError`` without Application Default
    Credentials. That propagated out of plugin discovery and crashed every URL
    handler — not just GCS — in credential-less environments (e.g. CI).
    """

    def test_construct_without_credentials(self, fake_gcs_storage):
        """Instantiating the handler must NOT construct storage.Client()."""
        from sunstone.handlers_gcs import GcsURLHandler

        handler = GcsURLHandler()  # must not raise

        fake_gcs_storage.Client.assert_not_called()
        assert handler._client is None

    def test_missing_dependency_raises_import_error(self, monkeypatch):
        """With google-cloud-storage absent, construction raises ImportError so
        the plugin registry's ``except ImportError`` cleanly skips the handler."""
        monkeypatch.setitem(sys.modules, "google.cloud.storage", None)

        from sunstone.handlers_gcs import GcsURLHandler

        with pytest.raises(ImportError):
            GcsURLHandler()

    def test_client_constructed_on_first_use(self, fake_gcs_storage):
        """The client is built lazily the first time a blob is resolved."""
        from sunstone.handlers_gcs import GcsURLHandler

        mock_client = MagicMock()
        fake_gcs_storage.Client.side_effect = None
        fake_gcs_storage.Client.return_value = mock_client
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"x"
        mock_client.bucket.return_value.blob.return_value = mock_blob

        handler = GcsURLHandler()
        fake_gcs_storage.Client.assert_not_called()

        handler.open("gs://bucket/key", "rb")

        fake_gcs_storage.Client.assert_called_once()
        # Cached: a second access reuses the same client.
        handler.open("gs://bucket/key", "rb")
        fake_gcs_storage.Client.assert_called_once()
