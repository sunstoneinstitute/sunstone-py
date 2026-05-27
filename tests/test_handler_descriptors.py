"""Tests for ``content_descriptors()`` and ``extensions()`` on built-in handlers (D4).

These methods expose the discovery view declared by the AssetKind.BLOB and
content-type discovery design: each built-in handler advertises the canonical
MIME(s) and file extension(s) it owns in the discovery surface. The dispatch
surface (``can_read`` / ``_resolve_format`` / ``_EXTENSION_MAP``) is wider and
remains untouched here.
"""

from __future__ import annotations

import pytest

from sunstone.handlers import BuiltinFormatHandler, ParquetFormatHandler
from sunstone.handlers_meta import ContentDescriptor
from sunstone.handlers_npz import NpzFormatHandler


def _builtin_case() -> tuple[object, tuple[ContentDescriptor, ...], tuple[str, ...]]:
    return (
        BuiltinFormatHandler(),
        (
            ContentDescriptor("text/csv"),
            ContentDescriptor("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ContentDescriptor("application/json"),
            ContentDescriptor("text/tab-separated-values"),
        ),
        (".csv", ".xlsx", ".json", ".tsv"),
    )


def _parquet_case() -> tuple[object, tuple[ContentDescriptor, ...], tuple[str, ...]]:
    return (
        ParquetFormatHandler(),
        (ContentDescriptor("application/vnd.apache.parquet"),),
        (".parquet",),
    )


def _npz_case() -> tuple[object, tuple[ContentDescriptor, ...], tuple[str, ...]]:
    return (
        NpzFormatHandler(),
        (ContentDescriptor("application/x-numpy-npz"),),
        (".npz",),
    )


def _zarr_case() -> tuple[object, tuple[ContentDescriptor, ...], tuple[str, ...]]:
    pytest.importorskip("zarr")
    from sunstone.handlers_zarr import ZarrStoreHandler

    return (
        ZarrStoreHandler(),
        (ContentDescriptor("application/x-zarr"),),
        (".zarr",),
    )


def _hdf5_case() -> tuple[object, tuple[ContentDescriptor, ...], tuple[str, ...]]:
    pytest.importorskip("h5py")
    from sunstone.handlers_hdf5 import Hdf5StoreHandler

    return (
        Hdf5StoreHandler(),
        (
            ContentDescriptor("application/x-hdf5"),
            ContentDescriptor("application/x-netcdf"),
        ),
        (".h5", ".hdf5", ".he5", ".nc", ".nc4"),
    )


_CASE_BUILDERS = [
    ("builtin", _builtin_case),
    ("parquet", _parquet_case),
    ("npz", _npz_case),
    ("zarr", _zarr_case),
    ("hdf5", _hdf5_case),
]


@pytest.mark.parametrize("name,builder", _CASE_BUILDERS, ids=[n for n, _ in _CASE_BUILDERS])
def test_content_descriptors_match_spec(name: str, builder) -> None:
    handler, expected_descriptors, _expected_exts = builder()
    assert handler.content_descriptors() == expected_descriptors


@pytest.mark.parametrize("name,builder", _CASE_BUILDERS, ids=[n for n, _ in _CASE_BUILDERS])
def test_extensions_match_spec(name: str, builder) -> None:
    handler, _expected_descriptors, expected_exts = builder()
    assert handler.extensions() == expected_exts


@pytest.mark.parametrize("name,builder", _CASE_BUILDERS, ids=[n for n, _ in _CASE_BUILDERS])
def test_content_encoding_is_none(name: str, builder) -> None:
    handler, _expected_descriptors, _expected_exts = builder()
    for desc in handler.content_descriptors():
        assert desc.content_encoding is None
