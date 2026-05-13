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


def test_as_array_returns_payload_when_kind_matches():
    arrays = {"band1": np.zeros((4, 4))}
    asset = Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=Metadata())
    assert asset.as_array() is arrays


def test_as_tiles_returns_payload_when_kind_matches():
    pyramid = object()  # opaque tile-pyramid descriptor stand-in
    asset = Asset(payload=pyramid, kind=AssetKind.TILES, metadata=Metadata())
    assert asset.as_tiles() is pyramid


def test_derive_returns_new_asset_with_new_payload():
    parent_df = pd.DataFrame({"x": [1, 2, 3]})
    parent = Asset(
        payload=parent_df,
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="parent", name="Parent"),
    )
    new_df = pd.DataFrame({"x": [10, 20, 30]})
    child = parent.derive(payload=new_df, slug="child", name="Child")
    assert child is not parent
    assert child.payload is new_df
    assert child.kind is parent.kind
    assert child.metadata.slug == "child"
    assert child.metadata.name == "Child"


def test_derive_clears_slug_and_name_when_not_provided():
    parent = Asset(
        payload=None,
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent", name="Parent"),
    )
    child = parent.derive(payload=None)
    assert child.metadata.slug is None
    assert child.metadata.name is None


def test_derive_does_not_inherit_custom_properties_by_default():
    parent_meta = Metadata(slug="parent")
    parent_meta["sosa:observedProperty"] = "surface-reflectance"
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)

    child = parent.derive(payload=None)
    assert child.metadata.custom_properties in (None, {})


def test_derive_inherits_custom_properties_when_opted_in():
    parent_meta = Metadata(slug="parent")
    parent_meta["sosa:observedProperty"] = "surface-reflectance"
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)

    child = parent.derive(payload=None, inherit_custom_properties=True)
    assert child.metadata["sosa:observedProperty"] == "surface-reflectance"


def test_derive_metadata_updates_overrides_individual_keys():
    parent_meta = Metadata(slug="parent")
    parent = Asset(payload=None, kind=AssetKind.RASTER, metadata=parent_meta)
    child = parent.derive(
        payload=None,
        metadata_updates={"sosa:observedProperty": "ndvi"},
    )
    assert child.metadata["sosa:observedProperty"] == "ndvi"


def test_derive_deep_copies_extras():
    profile = {"count": 1, "dtype": "uint8"}
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": profile},
    )
    child = parent.derive(payload=np.zeros((1, 8, 8), dtype="uint8"))
    # Mutating child must not affect parent.
    child.extras["profile"]["count"] = 99
    assert parent.extras["profile"]["count"] == 1


def test_derive_applies_extras_updates_after_inheritance():
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": {"count": 1}, "crs": "EPSG:4326"},
    )
    child = parent.derive(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        extras_updates={"crs": "EPSG:3857"},
    )
    assert child.extras["crs"] == "EPSG:3857"
    assert child.extras["profile"] == {"count": 1}  # untouched


def test_derive_runs_kind_derive_policy():
    # Raster policy drops stale profile fields when shape changes.
    parent = Asset(
        payload=np.zeros((4, 8, 8), dtype="uint16"),
        kind=AssetKind.RASTER,
        metadata=Metadata(slug="parent"),
        extras={"profile": {"count": 4, "dtype": "uint16", "nodata": 0, "crs": "EPSG:4326"}},
    )
    child = parent.derive(payload=np.zeros((8, 8), dtype="float32"))
    assert "count" not in child.extras["profile"]
    assert "dtype" not in child.extras["profile"]
    assert child.extras["profile"]["crs"] == "EPSG:4326"


def test_derive_records_wasderivedfrom_for_slugged_parent():
    parent = Asset(
        payload=None,
        kind=AssetKind.TABULAR,
        metadata=Metadata(slug="parent-slug", name="Parent"),
    )
    child = parent.derive(payload=None, slug="child")
    # Child's lineage.sources contains a snapshot referencing parent's slug.
    source_slugs = [s.slug for s in child.metadata.lineage.sources]
    assert "parent-slug" in source_slugs
