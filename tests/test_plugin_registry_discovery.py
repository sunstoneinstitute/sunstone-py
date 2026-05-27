"""Tests for PluginRegistry discovery accessors (D5).

Covers ``known_content_descriptors()``, ``known_content_types()``,
``known_extensions()``, and ``handler_for_content()``.
"""

from __future__ import annotations

import pytest

from sunstone.handlers import BlobFormatHandler, BuiltinFormatHandler
from sunstone.handlers_meta import ContentDescriptor
from sunstone.plugins import PluginRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    PluginRegistry._instance = None
    PluginRegistry._instances = {}
    yield
    PluginRegistry._instance = None
    PluginRegistry._instances = {}


# --- known_content_types() ------------------------------------------------


def test_known_content_types_includes_tabular_mimes() -> None:
    types = PluginRegistry.get().known_content_types()
    assert "text/csv" in types
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in types
    assert "application/vnd.apache.parquet" in types


def test_known_content_types_includes_npz() -> None:
    pytest.importorskip("numpy")
    types = PluginRegistry.get().known_content_types()
    assert "application/x-numpy-npz" in types


def test_known_content_types_includes_blob_mimes() -> None:
    types = PluginRegistry.get().known_content_types()
    # The 4 simple ones plus the four Office Open XML MIMEs
    assert "application/pdf" in types
    assert "application/rtf" in types
    assert "text/plain" in types
    assert "application/msword" in types
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in types
    assert "application/vnd.ms-powerpoint" in types
    assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in types
    assert "application/vnd.ms-excel" in types


def test_known_content_types_includes_zarr_if_installed() -> None:
    pytest.importorskip("zarr")
    types = PluginRegistry.get().known_content_types()
    assert "application/x-zarr" in types


def test_known_content_types_includes_hdf5_if_installed() -> None:
    pytest.importorskip("h5py")
    types = PluginRegistry.get().known_content_types()
    assert "application/x-hdf5" in types
    assert "application/x-netcdf" in types


# --- known_content_descriptors() ------------------------------------------


def test_known_content_descriptors_returns_set_of_descriptors() -> None:
    descs = PluginRegistry.get().known_content_descriptors()
    assert isinstance(descs, set)
    assert ContentDescriptor("text/csv", None) in descs


# --- known_extensions() ---------------------------------------------------


def test_known_extensions_includes_tabular_extensions() -> None:
    exts = PluginRegistry.get().known_extensions()
    assert ".csv" in exts
    assert ".xlsx" in exts
    assert ".parquet" in exts


def test_known_extensions_includes_npz() -> None:
    pytest.importorskip("numpy")
    exts = PluginRegistry.get().known_extensions()
    assert ".npz" in exts


def test_known_extensions_includes_blob_extensions() -> None:
    exts = PluginRegistry.get().known_extensions()
    # All 8 blob extensions
    for ext in (".pdf", ".rtf", ".txt", ".doc", ".docx", ".ppt", ".pptx", ".xls"):
        assert ext in exts, f"missing {ext}"


def test_known_extensions_includes_zarr_if_installed() -> None:
    pytest.importorskip("zarr")
    exts = PluginRegistry.get().known_extensions()
    assert ".zarr" in exts


def test_known_extensions_includes_hdf5_if_installed() -> None:
    pytest.importorskip("h5py")
    exts = PluginRegistry.get().known_extensions()
    assert ".h5" in exts
    assert ".hdf5" in exts
    assert ".nc" in exts


# --- handler_for_content() -------------------------------------------------


def test_handler_for_csv_returns_builtin_handler() -> None:
    handler = PluginRegistry.get().handler_for_content("text/csv")
    assert isinstance(handler, BuiltinFormatHandler)


def test_handler_for_csv_strips_parameters_with_space() -> None:
    handler = PluginRegistry.get().handler_for_content("text/csv; charset=utf-8")
    assert isinstance(handler, BuiltinFormatHandler)


def test_handler_for_csv_strips_parameters_without_space() -> None:
    handler = PluginRegistry.get().handler_for_content("text/csv;charset=utf-8")
    assert isinstance(handler, BuiltinFormatHandler)


def test_handler_for_csv_with_gzip_encoding_returns_none() -> None:
    # No handler claims gzip-encoded CSV.
    handler = PluginRegistry.get().handler_for_content("text/csv", content_encoding="gzip")
    assert handler is None


def test_handler_for_unknown_mime_returns_none() -> None:
    handler = PluginRegistry.get().handler_for_content("application/x-this-mime-does-not-exist")
    assert handler is None


def test_handler_for_pdf_returns_blob_handler() -> None:
    handler = PluginRegistry.get().handler_for_content("application/pdf")
    assert isinstance(handler, BlobFormatHandler)


# --- legacy plugin compatibility ------------------------------------------


def test_legacy_handler_without_descriptor_methods_does_not_crash() -> None:
    """A v1-style handler missing content_descriptors/extensions must be tolerated."""

    class LegacyHandler:
        def supports_metadata(self) -> bool:
            return False

        def supports_native_metadata_extraction(self) -> bool:
            return False

        def supports_sunstone_metadata_embedding(self) -> bool:
            return False

        def can_read(self, path, format):
            return False

        def read(self, stream, **kwargs):
            return None

        def can_write(self, path, format):
            return False

        def write(self, payload, stream, **kwargs):
            return None

    # Use a fresh registry instance directly (not the singleton) so we don't
    # rely on monkey-patching entry points.
    registry = PluginRegistry()
    registry._format_handlers.append(LegacyHandler())  # type: ignore[arg-type]

    # Should not raise.
    types = registry.known_content_types()
    exts = registry.known_extensions()
    descs = registry.known_content_descriptors()

    assert isinstance(types, set)
    assert isinstance(exts, dict)
    assert isinstance(descs, set)
    # Legacy handler contributes nothing.
    assert types == set()
    assert exts == {}
    assert descs == set()
    # And handler_for_content returns None.
    assert registry.handler_for_content("text/csv") is None


# --- ordering: format handlers consulted before store handlers ------------


def test_format_handlers_consulted_before_store_handlers() -> None:
    """When both a format and a store handler claim the same MIME, format wins."""

    class FormatClaimant:
        def supports_metadata(self) -> bool:
            return False

        def supports_native_metadata_extraction(self) -> bool:
            return False

        def supports_sunstone_metadata_embedding(self) -> bool:
            return False

        def can_read(self, path, format):
            return False

        def read(self, stream, **kwargs):
            return None

        def can_write(self, path, format):
            return False

        def write(self, payload, stream, **kwargs):
            return None

        def content_descriptors(self):
            return (ContentDescriptor("application/x-shared-mime", None),)

        def extensions(self):
            return (".shared",)

    class StoreClaimant:
        def content_descriptors(self):
            return (ContentDescriptor("application/x-shared-mime", None),)

        def extensions(self):
            return (".shared",)

    registry = PluginRegistry()
    fmt = FormatClaimant()
    store = StoreClaimant()
    registry._format_handlers.append(fmt)  # type: ignore[arg-type]
    registry._store_format_handlers.append(store)

    result = registry.handler_for_content("application/x-shared-mime")
    assert result is fmt


def test_known_extensions_external_plugin_wins_over_builtin() -> None:
    """External plugins are registered before built-ins, so dispatch returns
    them first on overlapping extensions. ``known_extensions()`` must mirror
    that priority — discovery and dispatch should agree."""

    class _ExternalPdfPlugin:
        def supports_metadata(self) -> bool:
            return False

        def supports_native_metadata_extraction(self) -> bool:
            return False

        def supports_sunstone_metadata_embedding(self) -> bool:
            return False

        def can_read(self, path, format):
            return False

        def read(self, stream, **kwargs):
            return None

        def can_write(self, path, format):
            return False

        def write(self, payload, stream, **kwargs):
            return None

        def content_descriptors(self):
            return (ContentDescriptor("application/pdf", None),)

        def extensions(self):
            return (".pdf",)

    registry = PluginRegistry.get()
    external = _ExternalPdfPlugin()
    # External plugins are prepended/registered before internals; the registry
    # constructs _format_handlers with externals first, internals last. Mimic
    # that ordering by inserting at the front.
    registry._format_handlers.insert(0, external)  # type: ignore[arg-type]

    exts = registry.known_extensions()
    assert exts[".pdf"] is external, (
        "known_extensions() should report the external plugin for .pdf, "
        "matching dispatch priority — not the later-registered BlobFormatHandler."
    )
