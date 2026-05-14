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
