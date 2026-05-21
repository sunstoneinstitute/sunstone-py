import numpy as np
import pandas as pd

from sunstone.asset import Asset, AssetKind
from sunstone.derive_policies import (
    apply_kind_derive_policy,
    no_op_policy,
)
from sunstone.lineage import Metadata


def test_registry_has_no_op_default_for_all_kinds():
    for kind in AssetKind:
        # apply must succeed for every kind even without a registered policy.
        parent = Asset(payload=None, kind=kind, metadata=Metadata())
        child = Asset(payload=None, kind=kind, metadata=Metadata())
        result = apply_kind_derive_policy(parent, child)
        assert result is child


def test_no_op_policy_returns_child_unchanged():
    parent = Asset(payload=None, kind=AssetKind.TABULAR, metadata=Metadata())
    child = Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=AssetKind.TABULAR,
        metadata=Metadata(),
        extras={"k": "v"},
    )
    out = no_op_policy(parent, child)
    assert out is child
    assert out.extras == {"k": "v"}


def test_raster_policy_invalidates_count_dtype_nodata_when_shape_differs():
    from sunstone.derive_policies import raster_invalidate_stale_profile

    parent = Asset(
        payload=np.zeros((4, 8, 8), dtype="uint16"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={
            "profile": {
                "count": 4,
                "dtype": "uint16",
                "nodata": 0,
                "crs": "EPSG:4326",
                "transform": (1, 0, 0, 0, -1, 0),
            }
        },
    )
    child = Asset(
        payload=np.zeros((8, 8), dtype="float32"),  # shape and dtype changed
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras=dict(parent.extras),  # caller inherited shallow
    )
    # Deep-copy of extras is the caller's responsibility (handled in Asset.derive).
    child.extras["profile"] = dict(child.extras["profile"])

    out = raster_invalidate_stale_profile(parent, child)
    assert "count" not in out.extras["profile"]
    assert "dtype" not in out.extras["profile"]
    assert "nodata" not in out.extras["profile"]
    # Geographic fields are preserved by default.
    assert out.extras["profile"]["crs"] == "EPSG:4326"
    assert out.extras["profile"]["transform"] == (1, 0, 0, 0, -1, 0)


def test_raster_policy_preserves_profile_when_shape_unchanged():
    from sunstone.derive_policies import raster_invalidate_stale_profile

    profile = {"count": 1, "dtype": "uint8", "nodata": 0}
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    child = Asset(
        payload=np.full((1, 8, 8), 5, dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    out = raster_invalidate_stale_profile(parent, child)
    assert out.extras["profile"] == {"count": 1, "dtype": "uint8", "nodata": 0}


def test_raster_policy_invalidates_profile_when_only_dtype_differs():
    from sunstone.derive_policies import raster_invalidate_stale_profile

    profile = {"count": 1, "dtype": "uint8", "nodata": 0, "crs": "EPSG:4326"}
    parent = Asset(
        payload=np.zeros((1, 8, 8), dtype="uint8"),
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    child = Asset(
        payload=np.zeros((1, 8, 8), dtype="float32"),  # same shape, new dtype
        kind=AssetKind.RASTER,
        metadata=Metadata(),
        extras={"profile": profile.copy()},
    )
    out = raster_invalidate_stale_profile(parent, child)
    assert "dtype" not in out.extras["profile"]
    assert "count" not in out.extras["profile"]
    assert "nodata" not in out.extras["profile"]
    # Geographic field preserved.
    assert out.extras["profile"]["crs"] == "EPSG:4326"


def test_raster_policy_registered_in_global_registry():
    from sunstone.derive_policies import KIND_DERIVE_POLICIES, raster_invalidate_stale_profile

    assert KIND_DERIVE_POLICIES[AssetKind.RASTER] is raster_invalidate_stale_profile
