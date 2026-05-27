"""Tests for ``BlobFormatHandler`` — opaque binary/document formats (D2)."""

from __future__ import annotations

import io

import pytest

from sunstone.asset import Asset, AssetKind
from sunstone.errors import IncompatibleAssetKindError
from sunstone.handlers import BlobFormatHandler, BuiltinFormatHandler, ParquetFormatHandler
from sunstone.handlers_meta import ContentDescriptor
from sunstone.lineage import Metadata
from sunstone.plugins import PluginRegistry


# (extension, canonical_mime, sample_payload)
_ROUND_TRIP_CASES: list[tuple[str, str, bytes]] = [
    (".pdf", "application/pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nfake pdf body\n"),
    (".rtf", "application/rtf", b"{\\rtf1\\ansi tiny rtf body}"),
    (".txt", "text/plain", b"hello, world\nsecond line\n"),
    (".doc", "application/msword", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 fake-doc-body"),
    (
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04 fake-docx-zip-body",
    ),
    (".ppt", "application/vnd.ms-powerpoint", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 fake-ppt-body"),
    (
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        b"PK\x03\x04 fake-pptx-zip-body",
    ),
    (".xls", "application/vnd.ms-excel", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 fake-xls-body"),
]


@pytest.fixture
def handler() -> BlobFormatHandler:
    return BlobFormatHandler()


class TestBlobCapabilities:
    def test_protocol_v2(self, handler: BlobFormatHandler) -> None:
        assert getattr(handler, "__sunstone_handler_protocol__", 0) == 2

    def test_supports_native_extraction_false(self, handler: BlobFormatHandler) -> None:
        assert handler.supports_native_metadata_extraction() is False

    def test_supports_embedding_false(self, handler: BlobFormatHandler) -> None:
        assert handler.supports_sunstone_metadata_embedding() is False

    def test_supports_metadata_alias(self, handler: BlobFormatHandler) -> None:
        assert handler.supports_metadata() is False

    def test_supported_kinds(self, handler: BlobFormatHandler) -> None:
        assert handler.supported_kinds() == (AssetKind.BLOB,)


class TestBlobCanRead:
    @pytest.mark.parametrize("ext", [ext for ext, _, _ in _ROUND_TRIP_CASES])
    def test_can_read_known_extension(self, handler: BlobFormatHandler, ext: str) -> None:
        assert handler.can_read(f"/tmp/sample{ext}", None) is True

    @pytest.mark.parametrize("ext", [".csv", ".xlsx", ".parquet", ".npz", ".zarr", ".xyz"])
    def test_can_read_rejects_other_extensions(self, handler: BlobFormatHandler, ext: str) -> None:
        assert handler.can_read(f"/tmp/foo{ext}", None) is False

    @pytest.mark.parametrize("mime", [mime for _, mime, _ in _ROUND_TRIP_CASES])
    def test_can_read_known_mime_without_extension(self, handler: BlobFormatHandler, mime: str) -> None:
        # Path has no recognisable extension, but format= names the MIME.
        assert handler.can_read("/tmp/unknown-thing", mime) is True

    def test_can_read_url_path_with_known_extension(self, handler: BlobFormatHandler) -> None:
        assert handler.can_read("https://example.com/some/report.pdf?token=abc", None) is True

    def test_can_read_rejects_unknown_format(self, handler: BlobFormatHandler) -> None:
        assert handler.can_read("/tmp/no-ext", "application/x-nonsense") is False

    @pytest.mark.parametrize("short", ["pdf", "rtf", "txt", "doc", "docx", "ppt", "pptx", "xls"])
    def test_can_read_accepts_short_format_alias(self, handler: BlobFormatHandler, short: str) -> None:
        # Mirrors the BuiltinFormatHandler convention where format="csv" works
        # alongside format="text/csv". datasets.yaml rows often carry the short
        # form, so the blob handler must also accept it.
        assert handler.can_read("/tmp/unknown-thing", short) is True


class TestBlobCanWrite:
    @pytest.mark.parametrize("ext", [ext for ext, _, _ in _ROUND_TRIP_CASES])
    def test_can_write_known_extension(self, handler: BlobFormatHandler, ext: str) -> None:
        assert handler.can_write(f"/tmp/sample{ext}", None) is True

    @pytest.mark.parametrize("ext", [".csv", ".xlsx", ".parquet", ".npz", ".zarr", ".xyz"])
    def test_can_write_rejects_other_extensions(self, handler: BlobFormatHandler, ext: str) -> None:
        assert handler.can_write(f"/tmp/foo{ext}", None) is False

    @pytest.mark.parametrize("mime", [mime for _, mime, _ in _ROUND_TRIP_CASES])
    def test_can_write_known_mime_without_extension(self, handler: BlobFormatHandler, mime: str) -> None:
        assert handler.can_write("/tmp/unknown-thing", mime) is True


class TestBlobRoundTrip:
    @pytest.mark.parametrize(
        "ext,mime,data",
        _ROUND_TRIP_CASES,
        ids=[ext.lstrip(".") for ext, _, _ in _ROUND_TRIP_CASES],
    )
    def test_byte_exact_round_trip(
        self,
        handler: BlobFormatHandler,
        ext: str,
        mime: str,
        data: bytes,
    ) -> None:
        asset = Asset(payload=data, kind=AssetKind.BLOB, metadata=Metadata())
        write_buf = io.BytesIO()
        handler.write(asset, write_buf, path=f"/tmp/test{ext}")

        read_buf = io.BytesIO(write_buf.getvalue())
        restored = handler.read(read_buf, path=f"/tmp/test{ext}")

        assert isinstance(restored, Asset)
        assert restored.kind is AssetKind.BLOB
        assert restored.as_blob() == data
        assert restored.extras["media_type"] == mime

    def test_read_without_path_or_format_falls_back_to_octet_stream(self, handler: BlobFormatHandler) -> None:
        data = b"\x00\x01\x02opaque"
        buf = io.BytesIO(data)
        restored = handler.read(buf)
        assert restored.as_blob() == data
        assert restored.extras["media_type"] == "application/octet-stream"

    def test_read_format_kwarg_takes_precedence_over_unknown_path(self, handler: BlobFormatHandler) -> None:
        data = b"fake-pdf-data"
        buf = io.BytesIO(data)
        restored = handler.read(buf, path="/tmp/no-extension", format="application/pdf")
        assert restored.as_blob() == data
        assert restored.extras["media_type"] == "application/pdf"

    def test_read_pops_dispatch_kwargs(self, handler: BlobFormatHandler) -> None:
        # format / path / dialect must be consumed by read and not passed to anything else.
        buf = io.BytesIO(b"x")
        restored = handler.read(buf, path="/tmp/x.pdf", format=None, dialect=None)
        assert restored.as_blob() == b"x"


class TestBlobWrite:
    def test_write_raises_on_non_blob_kind(self, handler: BlobFormatHandler) -> None:
        import pandas as pd

        df = pd.DataFrame({"a": [1, 2]})
        asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
        buf = io.BytesIO()
        with pytest.raises(IncompatibleAssetKindError):
            handler.write(asset, buf, path="/tmp/x.pdf")

    def test_write_pops_dispatch_kwargs(self, handler: BlobFormatHandler) -> None:
        asset = Asset(payload=b"hi", kind=AssetKind.BLOB, metadata=Metadata())
        buf = io.BytesIO()
        handler.write(asset, buf, path="/tmp/x.pdf", format="application/pdf")
        assert buf.getvalue() == b"hi"


class TestBlobDescriptors:
    def test_content_descriptors_count(self, handler: BlobFormatHandler) -> None:
        descriptors = handler.content_descriptors()
        assert len(descriptors) == 8

    def test_content_descriptors_are_content_descriptor_instances(self, handler: BlobFormatHandler) -> None:
        descriptors = handler.content_descriptors()
        for desc in descriptors:
            assert isinstance(desc, ContentDescriptor)
            assert desc.content_encoding is None

    def test_content_descriptors_cover_expected_mimes(self, handler: BlobFormatHandler) -> None:
        descriptors = handler.content_descriptors()
        mimes = {d.content_type for d in descriptors}
        expected = {mime for _, mime, _ in _ROUND_TRIP_CASES}
        assert mimes == expected

    def test_extensions(self, handler: BlobFormatHandler) -> None:
        exts = handler.extensions()
        expected = tuple(ext for ext, _, _ in _ROUND_TRIP_CASES)
        assert exts == expected


class TestBlobRegistration:
    def test_registry_includes_blob_handler(self) -> None:
        # Use a clean registry to avoid cached test side-effects.
        PluginRegistry._instance = None
        registry = PluginRegistry.get()
        handlers = registry.get_format_handlers()
        assert any(isinstance(h, BlobFormatHandler) for h in handlers)

    def test_blob_handler_registered_last(self) -> None:
        PluginRegistry._instance = None
        registry = PluginRegistry.get()
        handlers = registry.get_format_handlers()

        blob_idx = next(i for i, h in enumerate(handlers) if isinstance(h, BlobFormatHandler))
        builtin_idx = next(i for i, h in enumerate(handlers) if isinstance(h, BuiltinFormatHandler))
        parquet_idx = next(i for i, h in enumerate(handlers) if isinstance(h, ParquetFormatHandler))

        assert blob_idx > builtin_idx
        assert blob_idx > parquet_idx
