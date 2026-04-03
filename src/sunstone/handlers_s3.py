"""S3/R2 URL handler. Requires boto3 (install with sunstone-py[s3])."""

from __future__ import annotations

import io
import logging
from typing import BinaryIO, Literal, TextIO, overload
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class _S3WriteStream(io.BytesIO):
    """A BytesIO that uploads to S3 on close()."""

    def __init__(self, client: object, bucket: str, key: str) -> None:
        super().__init__()
        self._client = client
        self._bucket = bucket
        self._key = key

    def close(self) -> None:
        if not self.closed:
            self.seek(0)
            self._client.upload_fileobj(self, self._bucket, self._key)  # type: ignore[attr-defined]
        super().close()


class S3URLHandler:
    """Handles s3:// and r2:// URLs using boto3."""

    def __init__(self, config: dict | None = None) -> None:
        import boto3  # type: ignore[import-untyped]

        config = config or {}
        endpoint_url = config.get("endpoint_url")
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme in ("s3", "r2")

    def _parse_url(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        return bucket, key

    @overload
    def open(self, url: str, mode: Literal["r"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"]) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"]) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        bucket, key = self._parse_url(url)

        if "w" in mode:
            stream: BinaryIO = _S3WriteStream(self._client, bucket, key)
            if "b" not in mode:
                return io.TextIOWrapper(stream, encoding="utf-8")
            return stream

        response = self._client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        logger.info("Downloaded %d bytes from %s", len(data), url)
        binary_stream = io.BytesIO(data)

        if "b" in mode:
            return binary_stream
        return io.TextIOWrapper(binary_stream, encoding="utf-8")
