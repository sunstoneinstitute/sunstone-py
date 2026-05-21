"""Tests for ``NpzFormatHandler`` (NumPy ``.npz`` round-trip)."""

from __future__ import annotations

import numpy as np
import numpy.testing as npt
import pytest

import sunstone
from sunstone.asset import Asset, AssetKind
from sunstone.component import ComponentSchema
from sunstone.errors import IncompatibleAssetKindError
from sunstone.handlers_npz import NpzFormatHandler
from sunstone.lineage import Metadata


@pytest.fixture
def handler() -> NpzFormatHandler:
    return NpzFormatHandler()


class TestNpzCapabilities:
    def test_protocol_v2(self, handler):
        assert getattr(handler, "__sunstone_handler_protocol__", 0) == 2

    def test_supports_native_extraction(self, handler):
        assert handler.supports_native_metadata_extraction() is True

    def test_supports_embedding(self, handler):
        assert handler.supports_sunstone_metadata_embedding() is True

    def test_supports_metadata_alias(self, handler):
        assert handler.supports_metadata() is True

    def test_supported_kinds(self, handler):
        assert handler.supported_kinds() == (AssetKind.ARRAY,)

    def test_can_read_npz(self, handler):
        assert handler.can_read("data.npz", None)

    def test_can_read_explicit_format(self, handler):
        assert handler.can_read("data.whatever", "npz")

    def test_can_write_npz(self, handler):
        assert handler.can_write("out.npz", None)

    def test_can_write_explicit_format(self, handler):
        assert handler.can_write("out.dat", "npz")

    def test_cannot_read_parquet(self, handler):
        assert not handler.can_read("data.parquet", None)

    def test_cannot_write_csv(self, handler):
        assert not handler.can_write("data.csv", None)


class TestNpzRoundTrip:
    def test_round_trip_arrays_only(self, handler, tmp_path):
        arrays = {
            "temperature": np.arange(24, dtype=np.float32).reshape(2, 3, 4),
            "labels": np.array(["a", "b", "c"]),
        }
        asset = Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=Metadata())

        path = tmp_path / "vars.npz"
        with open(path, "wb") as f:
            handler.write(asset, f)

        with open(path, "rb") as f:
            restored = handler.read(f)

        assert isinstance(restored, Asset)
        assert restored.kind is AssetKind.ARRAY
        restored_arrays = restored.as_array()
        assert set(restored_arrays) == {"temperature", "labels"}
        npt.assert_array_equal(restored_arrays["temperature"], arrays["temperature"])
        assert restored_arrays["temperature"].dtype == np.float32
        npt.assert_array_equal(restored_arrays["labels"], arrays["labels"])

    def test_round_trip_with_metadata(self, handler, tmp_path):
        meta = Metadata()
        meta.slug = "era5-snapshot"
        meta.name = "ERA5 Snapshot"
        meta.description = "Two variables from ERA5 reanalysis"
        meta.component_metadata["temperature"] = ComponentSchema(
            name="temperature",
            component_kind="variable",
            dtype="float32",
            units="kelvin",
            description="2-metre air temperature",
        )

        arrays = {
            "temperature": np.array([[273.15, 280.0], [290.5, 300.0]], dtype=np.float32),
            "pressure": np.array([[101.3, 100.8]], dtype=np.float64),
        }
        asset = Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=meta)

        path = tmp_path / "era5.npz"
        with open(path, "wb") as f:
            handler.write(asset, f)

        with open(path, "rb") as f:
            restored = handler.read(f)

        assert restored.metadata.slug == "era5-snapshot"
        assert restored.metadata.name == "ERA5 Snapshot"
        assert restored.metadata.description == "Two variables from ERA5 reanalysis"

        comp = restored.metadata.component_metadata["temperature"]
        assert isinstance(comp, ComponentSchema)
        assert comp.name == "temperature"
        assert comp.component_kind == "variable"
        assert comp.dtype == "float32"
        assert comp.units == "kelvin"
        assert comp.description == "2-metre air temperature"

        # Payload arrays survive intact.
        restored_arrays = restored.as_array()
        npt.assert_array_equal(restored_arrays["temperature"], arrays["temperature"])
        npt.assert_array_equal(restored_arrays["pressure"], arrays["pressure"])
        assert restored_arrays["temperature"].dtype == np.float32
        assert restored_arrays["pressure"].dtype == np.float64

    def test_read_legacy_npz_without_metadata(self, handler, tmp_path):
        """A plain ``np.savez`` archive reads as an ARRAY asset with empty metadata."""
        path = tmp_path / "plain.npz"
        x = np.arange(6, dtype=np.int32).reshape(2, 3)
        y = np.linspace(0.0, 1.0, 5)
        np.savez(path, x=x, y=y)

        with open(path, "rb") as f:
            asset = handler.read(f)

        assert isinstance(asset, Asset)
        assert asset.kind is AssetKind.ARRAY
        arrays = asset.as_array()
        npt.assert_array_equal(arrays["x"], x)
        npt.assert_array_equal(arrays["y"], y)

        # Empty Metadata — no slug/name, no components, no lineage sources.
        meta = asset.metadata
        assert meta.slug is None
        assert meta.name is None
        assert meta.description is None
        assert meta.component_metadata == {}
        assert meta.lineage.sources == []


class TestNpzKindEnforcement:
    def test_write_rejects_non_array_kind(self, handler, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"x": [1, 2, 3]})
        asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())

        path = tmp_path / "wrong.npz"
        with pytest.raises(IncompatibleAssetKindError) as excinfo:
            with open(path, "wb") as f:
                handler.write(asset, f)
        assert excinfo.value.expected is AssetKind.ARRAY
        assert excinfo.value.actual is AssetKind.TABULAR

    def test_write_rejects_reserved_variable_name(self, handler, tmp_path):
        arrays = {NpzFormatHandler._METADATA_KEY: np.zeros(3)}
        asset = Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=Metadata())

        path = tmp_path / "reserved.npz"
        with pytest.raises(ValueError, match="reserved"):
            with open(path, "wb") as f:
                handler.write(asset, f)


class TestTopLevelDispatch:
    def test_top_level_read_dispatches_to_npz(self, handler, tmp_path):
        arrays = {
            "a": np.arange(10, dtype=np.int64),
            "b": np.linspace(-1.0, 1.0, 7, dtype=np.float32),
        }
        meta = Metadata()
        meta.slug = "dispatch-test"
        meta.name = "Dispatch Test"
        asset = Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=meta)

        path = tmp_path / "dispatch.npz"
        with open(path, "wb") as f:
            handler.write(asset, f)

        restored = sunstone.read(str(path))
        assert isinstance(restored, Asset)
        assert restored.kind is AssetKind.ARRAY
        assert restored.metadata.slug == "dispatch-test"
        assert restored.metadata.name == "Dispatch Test"

        restored_arrays = restored.as_array()
        npt.assert_array_equal(restored_arrays["a"], arrays["a"])
        npt.assert_array_equal(restored_arrays["b"], arrays["b"])
