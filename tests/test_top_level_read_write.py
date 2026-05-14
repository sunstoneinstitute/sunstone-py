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


def test_top_level_write_raises_incompatible_kind_when_handler_unsupported(tmp_path):
    import pytest

    import sunstone
    from sunstone.errors import IncompatibleAssetKindError
    from sunstone.lineage import Metadata

    # The CSV handler only supports TABULAR. Build a RASTER asset addressed
    # at a `.csv` path so dispatch picks the CSV handler but the kind check
    # then rejects it.
    asset = sunstone.Asset(
        payload=None,
        kind=sunstone.AssetKind.RASTER,
        metadata=Metadata(slug="r"),
    )
    with pytest.raises(IncompatibleAssetKindError) as exc:
        sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    assert "raster" in str(exc.value).lower()
    assert "tabular" in str(exc.value).lower()


def test_top_level_write_materialises_default_identity_when_none(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "1.2.3"\n')
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug="my-output", name="My Output"),
    )
    assert asset.metadata.identity is None

    sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    assert asset.metadata.identity == "sunstone://demo-pkg/my-output@1.2.3"


def test_top_level_write_preserves_user_supplied_identity(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "1.2.3"\n')
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(
            slug="my-output",
            identity="https://${DATASET_BASE_URL}/table@1.0.0",
        ),
    )
    sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    # User-supplied template preserved as-is.
    assert asset.metadata.identity == "https://${DATASET_BASE_URL}/table@1.0.0"


def test_top_level_write_skips_default_identity_when_slug_missing(tmp_path, monkeypatch):
    import pandas as pd

    import sunstone
    from sunstone.lineage import Metadata

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "1.2.3"\n')
    monkeypatch.chdir(tmp_path)
    sunstone.set_project_path(tmp_path)

    asset = sunstone.Asset(
        payload=pd.DataFrame({"a": [1]}),
        kind=sunstone.AssetKind.TABULAR,
        metadata=Metadata(slug=None, name="No Slug"),
    )
    # No slug → no default identity (the writer will raise for slug=None
    # via its own contract; the identity helper just leaves identity=None).
    try:
        sunstone.write(asset, str(tmp_path / "out.csv"), format="csv")
    except Exception:
        pass
    assert asset.metadata.identity is None
