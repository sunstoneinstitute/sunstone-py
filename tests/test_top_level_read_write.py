def test_top_level_read_returns_asset_for_csv(tmp_path):
    import sunstone

    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n3,4\n")

    asset = sunstone.read(str(csv), format="csv")
    assert asset.kind is sunstone.AssetKind.TABULAR
    assert list(asset.payload.columns) == ["a", "b"]


def test_top_level_read_raises_for_unknown_format(tmp_path):
    import sunstone

    p = tmp_path / "thing.xyz"
    p.write_text("noop")
    with __import__("pytest").raises(ValueError, match="handler"):
        sunstone.read(str(p), format="xyz")


def test_top_level_write_round_trips_tabular_asset(tmp_path):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    out = tmp_path / "out.csv"
    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="out", name="Out"),
    )
    sunstone.write(asset, str(out), format="csv")
    text = out.read_text()
    assert "a,b" in text
    assert "1,3" in text


def test_top_level_write_raises_for_no_handler(tmp_path):
    import pandas as pd
    import pytest

    import sunstone
    from sunstone.lineage import Metadata

    asset = sunstone.Asset(
        payload=pd.DataFrame({"x": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="x"),
    )
    with pytest.raises(ValueError, match="handler"):
        sunstone.write(asset, str(tmp_path / "out.xyz"), format="xyz")
