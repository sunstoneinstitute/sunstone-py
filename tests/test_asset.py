import numpy as np
import pandas as pd
import pytest

from sunstone.asset import Asset, AssetKind
from sunstone.errors import IncompatibleAssetKindError
from sunstone.lineage import Metadata


def test_asset_kind_is_closed_enum():
    assert {k.value for k in AssetKind} == {"tabular", "raster", "array", "tiles"}


def test_incompatible_asset_kind_error_message():
    err = IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=AssetKind.RASTER)
    msg = str(err)
    assert "tabular" in msg.lower()
    assert "raster" in msg.lower()


def test_asset_construction_minimum_fields():
    df = pd.DataFrame({"x": [1, 2]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.payload is df
    assert asset.kind is AssetKind.TABULAR
    assert asset.metadata.slug is None
    assert asset.extras == {}


def test_extras_defaults_to_empty_dict_per_instance():
    a = Asset(payload=None, kind=AssetKind.RASTER, metadata=Metadata())
    b = Asset(payload=None, kind=AssetKind.RASTER, metadata=Metadata())
    a.extras["k"] = 1
    assert "k" not in b.extras


def test_profile_accessor_reads_extras():
    asset = Asset(
        payload=np.zeros((3, 4, 4)),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": {"count": 3, "dtype": "uint16"}, "crs": "EPSG:4326"},
    )
    assert asset.profile == {"count": 3, "dtype": "uint16"}
    assert asset.crs == "EPSG:4326"


def test_as_table_returns_payload_when_kind_matches():
    df = pd.DataFrame({"x": [1]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.as_table() is df


def test_as_table_raises_on_wrong_kind():
    asset = Asset(payload=np.zeros((2, 2)), kind=AssetKind.RASTER, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError) as exc_info:
        asset.as_table()
    assert exc_info.value.expected is AssetKind.TABULAR
    assert exc_info.value.actual is AssetKind.RASTER


def test_as_raster_as_array_as_tiles_round_trip():
    arr = np.zeros((2, 4, 4))
    asset = Asset(payload=arr, kind=AssetKind.RASTER, metadata=Metadata())
    assert asset.as_raster() is arr
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_array()
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_tiles()
