"""Tests for the HDF5 / NetCDF-4 store-format handler."""

from __future__ import annotations

import pytest

h5py = pytest.importorskip("h5py")

import numpy as np  # noqa: E402

import sunstone  # noqa: E402
from sunstone.asset import Asset, AssetKind  # noqa: E402
from sunstone.component import ComponentSchema  # noqa: E402
from sunstone.errors import IncompatibleAssetKindError  # noqa: E402
from sunstone.handlers_hdf5 import Hdf5StoreHandler  # noqa: E402
from sunstone.lineage import Metadata  # noqa: E402
from sunstone.resource import ResourceLocation  # noqa: E402


def _make_array_asset(payload: dict[str, np.ndarray], *, metadata: Metadata | None = None) -> Asset:
    return Asset(
        payload=payload,
        kind=AssetKind.ARRAY,
        metadata=metadata or Metadata(),
    )


def test_round_trip_arrays_only(tmp_path):
    payload = {
        "temperature": np.array([[273.15, 280.5], [290.0, 295.25]], dtype="float32"),
        "pressure": np.array([1013, 1009, 1005, 1001], dtype="int32"),
        "humidity": np.linspace(0.0, 1.0, 8, dtype="float64"),
    }
    asset = _make_array_asset(payload)

    target = tmp_path / "vars.h5"
    handler = Hdf5StoreHandler()
    loc = ResourceLocation(path=str(target))

    assert handler.can_write_store(loc, None) is True
    handler.write(asset, loc)
    assert target.exists()

    assert handler.can_read_store(loc, None) is True
    read_back = handler.read(loc)

    assert read_back.kind is AssetKind.ARRAY
    arrays = read_back.as_array()
    assert set(arrays.keys()) == set(payload.keys())
    for name, original in payload.items():
        np.testing.assert_array_equal(arrays[name], original)
        assert arrays[name].dtype == original.dtype


def test_round_trip_with_metadata(tmp_path):
    payload = {
        "temperature": np.array([273.15, 290.0, 305.0], dtype="float32"),
        "wind_speed": np.array([1.5, 2.3, 0.8], dtype="float32"),
    }
    metadata = Metadata(
        slug="weather-sample",
        name="Weather Sample",
        description="Tiny synthetic weather sample for round-trip testing.",
    )
    metadata.component_metadata["temperature"] = ComponentSchema(
        name="temperature",
        component_kind="variable",
        units="kelvin",
        description="2-metre air temperature",
    )
    asset = _make_array_asset(payload, metadata=metadata)

    target = tmp_path / "weather.h5"
    handler = Hdf5StoreHandler()
    loc = ResourceLocation(path=str(target))
    handler.write(asset, loc)

    read_back = handler.read(loc)
    assert read_back.metadata.slug == "weather-sample"
    assert read_back.metadata.name == "Weather Sample"
    assert read_back.metadata.description.startswith("Tiny synthetic")

    cs = read_back.metadata.component_metadata.get("temperature")
    assert cs is not None
    assert cs.component_kind == "variable"
    assert cs.units == "kelvin"
    assert cs.description == "2-metre air temperature"


def test_cf_attrs_visible_on_disk(tmp_path):
    payload = {"temperature": np.array([273.15, 290.0], dtype="float32")}
    metadata = Metadata(slug="cf-demo", name="CF demo")
    metadata.component_metadata["temperature"] = ComponentSchema(
        name="temperature",
        component_kind="variable",
        units="kelvin",
        description="2-metre air temperature",
    )
    asset = _make_array_asset(payload, metadata=metadata)

    target = tmp_path / "cf.h5"
    Hdf5StoreHandler().write(asset, ResourceLocation(path=str(target)))

    # Open with raw h5py to verify on-disk CF attrs are present.
    with h5py.File(target, "r") as f:
        ds = f["temperature"]
        units = ds.attrs["units"]
        long_name = ds.attrs["long_name"]
        if isinstance(units, bytes):
            units = units.decode("utf-8")
        if isinstance(long_name, bytes):
            long_name = long_name.decode("utf-8")
        assert units == "kelvin"
        assert long_name == "2-metre air temperature"
        # Root-level sunstone JSON-LD blob also there.
        assert "sunstone" in f.attrs


def test_read_unknown_hdf5_without_sunstone_attr(tmp_path):
    target = tmp_path / "plain.h5"
    # Build a plain HDF5 file with raw h5py and no sunstone attr.
    with h5py.File(target, "w") as f:
        f.create_dataset("alpha", data=np.arange(6, dtype="int16"))
        f.create_dataset("beta", data=np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float64"))

    asset = Hdf5StoreHandler().read(ResourceLocation(path=str(target)))
    assert asset.kind is AssetKind.ARRAY
    assert asset.metadata.slug is None
    assert asset.metadata.name is None
    arrays = asset.as_array()
    np.testing.assert_array_equal(arrays["alpha"], np.arange(6, dtype="int16"))
    np.testing.assert_array_equal(arrays["beta"], np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float64"))


def test_write_rejects_non_array_kind(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2, 3]})
    tabular_asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())

    target = tmp_path / "wrong.h5"
    with pytest.raises(IncompatibleAssetKindError):
        Hdf5StoreHandler().write(tabular_asset, ResourceLocation(path=str(target)))


def test_top_level_read_dispatches_to_hdf5(tmp_path):
    # Sanity check: top-level sunstone.read() routes a single-file HDF5 path
    # through the store-handler path even though it's not a directory.
    payload = {"counts": np.array([10, 20, 30], dtype="int64")}
    asset = _make_array_asset(payload, metadata=Metadata(slug="top-level", name="Top level"))

    target = tmp_path / "single.h5"
    Hdf5StoreHandler().write(asset, ResourceLocation(path=str(target)))

    result = sunstone.read(str(target))
    assert result.kind is AssetKind.ARRAY
    arrays = result.as_array()
    np.testing.assert_array_equal(arrays["counts"], payload["counts"])


def test_nc_extension_also_works(tmp_path):
    # NetCDF-4 files are HDF5 underneath — the .nc extension must also be
    # recognised by the handler.
    payload = {"temperature": np.array([280.0, 290.0, 300.0], dtype="float32")}
    asset = _make_array_asset(payload)

    target = tmp_path / "sample.nc"
    handler = Hdf5StoreHandler()
    loc = ResourceLocation(path=str(target))

    assert handler.can_write_store(loc, None) is True
    handler.write(asset, loc)

    assert handler.can_read_store(loc, None) is True
    read_back = sunstone.read(str(target))
    assert read_back.kind is AssetKind.ARRAY
    arrays = read_back.as_array()
    np.testing.assert_array_equal(arrays["temperature"], payload["temperature"])
