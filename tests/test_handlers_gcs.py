"""Tests for GCS URL handler (mocked — no real GCS calls)."""

from unittest.mock import MagicMock

import pytest


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
