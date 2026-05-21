"""Tests for the optional Zarr store-format handler."""

from __future__ import annotations

import json

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")  # skip cleanly when [zarr] extra is absent

from sunstone.asset import Asset, AssetKind  # noqa: E402
from sunstone.component import ComponentSchema  # noqa: E402
from sunstone.errors import IncompatibleAssetKindError  # noqa: E402
from sunstone.handlers_zarr import ZarrStoreHandler  # noqa: E402
from sunstone.lineage import Metadata  # noqa: E402
from sunstone.resource import ResourceLocation  # noqa: E402


def _sample_payload() -> dict[str, np.ndarray]:
    return {
        "temperature": np.arange(24, dtype=np.float32).reshape(2, 3, 4),
        "pressure": np.linspace(900.0, 1050.0, 12, dtype=np.float64).reshape(3, 4),
        "mask": np.array([[1, 0, 1], [0, 1, 0]], dtype=np.uint8),
    }


def test_round_trip_arrays_only(tmp_path):
    """Write and read back a dict of mixed-dtype ndarrays without metadata."""
    handler = ZarrStoreHandler()
    target = tmp_path / "plain.zarr"

    asset = Asset(payload=_sample_payload(), kind=AssetKind.ARRAY, metadata=Metadata())
    handler.write(asset, ResourceLocation(path=str(target)))

    loaded = handler.read(ResourceLocation(path=str(target)))
    assert loaded.kind is AssetKind.ARRAY
    arrays = loaded.as_array()
    assert set(arrays.keys()) == set(asset.payload.keys())
    for name, expected in asset.payload.items():
        np.testing.assert_array_equal(arrays[name], expected)
        assert arrays[name].dtype == expected.dtype


def test_round_trip_with_metadata(tmp_path):
    """Slug/name/description and ComponentSchema entries all survive a round-trip."""
    handler = ZarrStoreHandler()
    target = tmp_path / "with_meta.zarr"

    meta = Metadata(
        slug="era5-test",
        name="ERA5 Test Slice",
        description="Toy slice for round-trip verification.",
    )
    meta.component_metadata["temperature"] = ComponentSchema(
        name="temperature",
        component_kind="variable",
        dtype="float32",
        units="kelvin",
        description="2-metre air temperature",
    )
    meta.component_metadata["pressure"] = ComponentSchema(
        name="pressure",
        component_kind="variable",
        dtype="float64",
        units="hPa",
        description="Surface pressure",
    )

    asset = Asset(payload=_sample_payload(), kind=AssetKind.ARRAY, metadata=meta)
    handler.write(asset, ResourceLocation(path=str(target)))

    loaded = handler.read(ResourceLocation(path=str(target)))
    assert loaded.metadata.slug == "era5-test"
    assert loaded.metadata.name == "ERA5 Test Slice"
    assert loaded.metadata.description == "Toy slice for round-trip verification."

    cm = loaded.metadata.component_metadata
    assert "temperature" in cm
    assert cm["temperature"].units == "kelvin"
    assert cm["temperature"].description == "2-metre air temperature"
    assert cm["pressure"].units == "hPa"
    assert cm["pressure"].description == "Surface pressure"


def test_cf_attrs_visible_on_disk(tmp_path):
    """Per-variable ``units`` / ``long_name`` attrs are exposed for xarray etc."""
    handler = ZarrStoreHandler()
    target = tmp_path / "cf_attrs.zarr"

    meta = Metadata(slug="cf-demo", name="CF Demo")
    meta.component_metadata["temperature"] = ComponentSchema(
        name="temperature",
        component_kind="variable",
        units="kelvin",
        description="Air temperature at 2m",
    )

    asset = Asset(
        payload={"temperature": np.arange(6, dtype=np.float32).reshape(2, 3)},
        kind=AssetKind.ARRAY,
        metadata=meta,
    )
    handler.write(asset, ResourceLocation(path=str(target)))

    # Now reach into the store with the raw zarr API — not the handler.
    group = zarr.open_group(str(target), mode="r")
    arr_attrs = dict(group["temperature"].attrs)
    assert arr_attrs.get("units") == "kelvin"
    assert arr_attrs.get("long_name") == "Air temperature at 2m"


def test_read_unknown_zarr_without_sunstone_attr(tmp_path):
    """A vanilla Zarr store (no ``sunstone`` attr) still reads as an empty-meta Asset."""
    target = tmp_path / "vanilla.zarr"
    group = zarr.open_group(str(target), mode="w")
    group["x"] = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    group["y"] = np.array([[1, 2], [3, 4]], dtype=np.int32)
    # Deliberately no group.attrs["sunstone"].

    handler = ZarrStoreHandler()
    asset = handler.read(ResourceLocation(path=str(target)))

    assert asset.kind is AssetKind.ARRAY
    assert asset.metadata.slug is None
    assert asset.metadata.name is None
    assert asset.metadata.description is None
    arrays = asset.as_array()
    np.testing.assert_array_equal(arrays["x"], np.array([1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(arrays["y"], np.array([[1, 2], [3, 4]]))


def test_write_rejects_non_array_kind(tmp_path):
    """Writing a TABULAR asset to the Zarr handler must raise."""
    import pandas as pd

    handler = ZarrStoreHandler()
    target = tmp_path / "wrong_kind.zarr"

    asset = Asset(
        payload=pd.DataFrame({"a": [1, 2, 3]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(),
    )
    with pytest.raises(IncompatibleAssetKindError):
        handler.write(asset, ResourceLocation(path=str(target)))


def test_top_level_read_dispatches_to_zarr(tmp_path):
    """``sunstone.read()`` of a ``.zarr`` directory routes to the store handler."""
    import sunstone

    target = tmp_path / "dispatch.zarr"
    handler = ZarrStoreHandler()

    asset = Asset(
        payload={"value": np.arange(8, dtype=np.float32).reshape(2, 4)},
        kind=AssetKind.ARRAY,
        metadata=Metadata(slug="dispatch-test", name="Dispatch Test"),
    )
    handler.write(asset, ResourceLocation(path=str(target)))

    # Reset the cached registry so the optional handler registration runs cleanly.
    from sunstone.plugins import PluginRegistry

    PluginRegistry._instance = None
    PluginRegistry._instances = {}

    loaded = sunstone.read(str(target))
    assert loaded.kind is AssetKind.ARRAY
    np.testing.assert_array_equal(
        loaded.as_array()["value"],
        np.arange(8, dtype=np.float32).reshape(2, 4),
    )
    assert loaded.metadata.slug == "dispatch-test"


def test_can_read_store_recognises_markers(tmp_path):
    """Sanity-check the directory-marker detection."""
    handler = ZarrStoreHandler()

    # .zarr suffix alone is sufficient
    assert handler.can_read_store(ResourceLocation(path="/tmp/anything.zarr"), None)
    assert handler.can_read_store(ResourceLocation(path="/tmp/anything.zarr"), "zarr")

    # An actual store on disk
    target = tmp_path / "store_dir"
    group = zarr.open_group(str(target), mode="w")
    group["x"] = np.array([0, 1, 2])
    assert handler.can_read_store(ResourceLocation(path=str(target)), None)

    # A bare empty directory is not a zarr store
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not handler.can_read_store(ResourceLocation(path=str(plain)), None)


def test_metadata_blob_is_valid_jsonld_string(tmp_path):
    """The root ``sunstone`` attr is a JSON string parseable as JSON-LD."""
    handler = ZarrStoreHandler()
    target = tmp_path / "jsonld.zarr"

    meta = Metadata(slug="jsonld-demo", name="JSON-LD Demo")
    asset = Asset(
        payload={"x": np.array([1.0, 2.0])},
        kind=AssetKind.ARRAY,
        metadata=meta,
    )
    handler.write(asset, ResourceLocation(path=str(target)))

    group = zarr.open_group(str(target), mode="r")
    raw = group.attrs[handler._METADATA_KEY]
    doc = json.loads(raw)
    assert doc.get("@type") == "dcat:Distribution"
    assert doc.get("dct:identifier") == "jsonld-demo"
