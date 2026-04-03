"""Tests for S3/R2 URL handler (mocked — no real AWS calls)."""

from unittest.mock import MagicMock

import pytest


from sunstone.handlers_s3 import S3URLHandler


@pytest.fixture
def s3_handler():
    handler = S3URLHandler.__new__(S3URLHandler)
    handler._client = MagicMock()
    return handler


@pytest.fixture
def r2_handler():
    handler = S3URLHandler.__new__(S3URLHandler)
    handler._client = MagicMock()
    return handler


class TestS3URLHandlerCanHandle:
    def test_s3_scheme(self, s3_handler):
        assert s3_handler.can_handle("s3://bucket/data.csv")

    def test_r2_scheme(self, s3_handler):
        assert s3_handler.can_handle("r2://bucket/data.csv")

    def test_gs_scheme(self, s3_handler):
        assert not s3_handler.can_handle("gs://bucket/data.csv")

    def test_http_scheme(self, s3_handler):
        assert not s3_handler.can_handle("http://example.com/data.csv")

    def test_local_path(self, s3_handler):
        assert not s3_handler.can_handle("data.csv")


class TestS3URLHandlerOpen:
    def test_read_binary(self, s3_handler):
        mock_body = MagicMock()
        mock_body.read.return_value = b"a,b\n1,2\n"
        s3_handler._client.get_object.return_value = {"Body": mock_body}

        stream = s3_handler.open("s3://my-bucket/data.csv", "rb")
        assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, s3_handler):
        mock_body = MagicMock()
        mock_body.read.return_value = b"a,b\n1,2\n"
        s3_handler._client.get_object.return_value = {"Body": mock_body}

        stream = s3_handler.open("s3://my-bucket/data.csv", "r")
        assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, s3_handler):
        stream = s3_handler.open("s3://my-bucket/out.csv", "wb")
        stream.write(b"a,b\n1,2\n")
        stream.close()

        s3_handler._client.upload_fileobj.assert_called_once()

    def test_write_text(self, s3_handler):
        stream = s3_handler.open("s3://my-bucket/out.csv", "w")
        stream.write("a,b\n1,2\n")
        stream.close()

        s3_handler._client.upload_fileobj.assert_called_once()

    def test_r2_uses_correct_bucket_key(self, r2_handler):
        mock_body = MagicMock()
        mock_body.read.return_value = b"data"
        r2_handler._client.get_object.return_value = {"Body": mock_body}

        r2_handler.open("r2://my-bucket/data.csv", "rb")
        r2_handler._client.get_object.assert_called_once_with(Bucket="my-bucket", Key="data.csv")
