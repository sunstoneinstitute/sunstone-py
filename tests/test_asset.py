import numpy as np
import pandas as pd
import pytest

from sunstone.asset import Asset, AssetKind
from sunstone.errors import IncompatibleAssetKindError
from sunstone.lineage import Metadata


def test_asset_kind_is_closed_enum():
    assert {k.value for k in AssetKind} == {"tabular", "raster", "array", "tiles", "blob", "geofeatures"}


def test_asset_kind_blob_exists_with_expected_value():
    assert AssetKind.BLOB.value == "blob"


def test_as_blob_returns_payload_when_kind_matches():
    data = b"hello world"
    asset = Asset(payload=data, kind=AssetKind.BLOB, metadata=Metadata())
    assert asset.as_blob() == b"hello world"
    assert asset.as_blob() is data


def test_as_blob_raises_on_wrong_kind():
    asset = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError) as exc_info:
        asset.as_blob()
    assert exc_info.value.expected is AssetKind.BLOB
    assert exc_info.value.actual is AssetKind.TABULAR


def test_blob_asset_derive_preserves_kind_and_records_parent_lineage():
    parent = Asset(
        payload=b"old bytes",
        kind=AssetKind.BLOB,
        metadata=Metadata(slug="parent-blob", name="Parent Blob"),
    )
    child = parent.derive(b"new bytes", slug="child", name="Child")
    assert child.kind is AssetKind.BLOB
    assert child.payload == b"new bytes"
    assert child.as_blob() == b"new bytes"
    source_slugs = [s.slug for s in child.metadata.lineage.sources]
    assert "parent-blob" in source_slugs


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


def test_as_pandas_returns_payload_when_kind_matches():
    df = pd.DataFrame({"x": [1]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.as_pandas() is df


def test_as_pandas_raises_on_wrong_kind():
    asset = Asset(payload=np.zeros((2, 2)), kind=AssetKind.RASTER, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError) as exc_info:
        asset.as_pandas()
    assert exc_info.value.expected is AssetKind.TABULAR
    assert exc_info.value.actual is AssetKind.RASTER


def test_as_table_is_backwards_compatible_alias():
    df = pd.DataFrame({"x": [1]})
    asset = Asset(payload=df, kind=AssetKind.TABULAR, metadata=Metadata())
    assert asset.as_table() is asset.as_pandas()


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


def test_derive_multi_parent_records_all_slugged_parents():
    a = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata(slug="parent-a", name="A"))
    b = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata(slug="parent-b", name="B"))
    child = a.derive(payload=None, slug="mosaic", derived_from=[a, b])
    slugs = [s.slug for s in child.metadata.lineage.sources]
    assert set(slugs) == {"parent-a", "parent-b"}


def test_derive_collapses_unsaved_intermediate_parent():
    # A (slugged) -> B (no slug, transient) -> C
    a = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata(slug="grandparent", name="Grandparent"))
    b = a.derive(payload=None)  # no slug
    assert b.metadata.slug is None
    c = b.derive(payload=None, slug="grandchild")
    # C's sources should reference A directly, not the slugless B.
    source_slugs = [s.slug for s in c.metadata.lineage.sources]
    assert source_slugs == ["grandparent"]


def test_derive_chains_activities_through_transient_intermediate():
    from sunstone.lineage import Activity, AgentType, Agent

    a_meta = Metadata(slug="root")
    a_meta.lineage.activity = Activity(
        id="op-1",
        was_associated_with=[Agent(id="user", type=AgentType.PERSON)],
    )
    a = Asset(payload=None, kind=AssetKind.TABULAR, metadata=a_meta)

    b = a.derive(payload=None)  # transient; carries forward A's activity
    c = b.derive(payload=None, slug="child")

    # The plan: child.lineage.activity is populated (not None).
    # Specific identity of the activity chain shape is implementation-defined;
    # but provenance of the root must be preserved either via sources or activity.
    source_slugs = [s.slug for s in c.metadata.lineage.sources]
    assert source_slugs == ["root"]
    assert c.metadata.lineage.activity is not None
    assert c.metadata.lineage.activity.id == "op-1"


# --- as_polars() ---


def _tabular(payload) -> Asset:
    return Asset(payload=payload, kind=AssetKind.TABULAR, metadata=Metadata())


def test_as_polars_returns_payload() -> None:
    pl = pytest.importorskip("polars")
    frame = pl.DataFrame({"a": [1, 2]})
    asset = _tabular(frame)
    assert asset.as_polars() is frame


def test_as_polars_wrong_kind_raises() -> None:
    pytest.importorskip("polars")
    asset = Asset(payload=b"x", kind=AssetKind.BLOB, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_polars()


def test_as_polars_on_pandas_payload_raises_typeerror() -> None:
    pytest.importorskip("polars")
    import pandas as pd

    asset = _tabular(pd.DataFrame({"a": [1]}))
    with pytest.raises(TypeError, match="pl.from_pandas"):
        asset.as_polars()
