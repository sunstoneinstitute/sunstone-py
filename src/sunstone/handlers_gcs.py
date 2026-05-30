"""GCS URL handler. Requires google-cloud-storage (install with sunstone-py[gcs])."""

from __future__ import annotations

import io
import logging
from typing import BinaryIO, Literal, TextIO, overload
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class _GcsWriteStream(io.BytesIO):
    """A BytesIO that uploads to GCS on close()."""

    def __init__(self, blob: object) -> None:
        super().__init__()
        self._blob = blob

    def close(self) -> None:
        if not self.closed:
            self.seek(0)
            self._blob.upload_from_file(self)  # type: ignore[attr-defined]
        super().close()


class GcsURLHandler:
    """Handles gs:// URLs using google-cloud-storage."""

    def __init__(self, config: dict | None = None) -> None:
        # Import (but do NOT instantiate) the client here. The import raises
        # ImportError when google-cloud-storage is missing, which the plugin
        # registry relies on to skip this handler cleanly. Constructing
        # storage.Client() eagerly would call google.auth.default() and raise
        # DefaultCredentialsError in credential-less environments (e.g. CI),
        # crashing plugin discovery. Defer client construction to first use.
        from google.cloud import storage  # type: ignore[import-untyped] # noqa: F401

        self._client: object | None = None

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme == "gs"

    def _get_client(self) -> object:
        """Lazily construct and cache the GCS client on first use."""
        if self._client is None:
            from google.cloud import storage  # type: ignore[import-untyped]

            self._client = storage.Client()
        return self._client

    def _get_blob(self, url: str) -> object:
        parsed = urlparse(url)
        bucket = self._get_client().bucket(parsed.netloc)  # type: ignore[attr-defined]
        blob_path = parsed.path.lstrip("/")
        return bucket.blob(blob_path)

    @overload
    def open(self, url: str, mode: Literal["r"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"]) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"]) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        blob = self._get_blob(url)

        if "w" in mode:
            stream: BinaryIO = _GcsWriteStream(blob)
            if "b" not in mode:
                return io.TextIOWrapper(stream, encoding="utf-8")
            return stream

        data = blob.download_as_bytes()  # type: ignore[attr-defined]
        logger.info("Downloaded %d bytes from %s", len(data), url)
        binary_stream = io.BytesIO(data)

        if "b" in mode:
            return binary_stream
        return io.TextIOWrapper(binary_stream, encoding="utf-8")
