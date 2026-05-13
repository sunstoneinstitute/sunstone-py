from sunstone.asset import AssetKind
from sunstone.errors import IncompatibleAssetKindError


def test_asset_kind_is_closed_enum():
    assert {k.value for k in AssetKind} == {"tabular", "raster", "array", "tiles"}


def test_incompatible_asset_kind_error_message():
    err = IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=AssetKind.RASTER)
    msg = str(err)
    assert "tabular" in msg.lower()
    assert "raster" in msg.lower()
