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
    # Scheme-less, environment-relative path — the consumer binds the scheme.
    assert asset.metadata.identity == "demo-pkg/my-output@1.2.3"


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


def test_read_no_overrides_returns_handler_metadata_for_csv(tmp_path):
    """Baseline: with no overrides, the handler's Asset is returned untouched."""
    import sunstone

    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n3,4\n")

    asset = sunstone.read(str(csv), format="csv")
    assert asset.kind is sunstone.AssetKind.TABULAR
    # No slug was provided; handler doesn't invent one.
    assert asset.metadata.slug is None


def test_read_no_overrides_preserves_blob_handler_extras(tmp_path):
    """Baseline: BlobFormatHandler emits ``extras={'media_type': ...}`` and a bare
    ``Metadata()``; passing no overrides leaves both intact."""
    import sunstone

    pdf = tmp_path / "foo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall")

    asset = sunstone.read(str(pdf))
    assert asset.kind is sunstone.AssetKind.BLOB
    assert asset.extras == {"media_type": "application/pdf"}
    assert asset.metadata.slug is None


def test_read_metadata_override_replaces_handler_metadata(tmp_path):
    """``metadata=`` fully replaces what the handler produced (catalog wins)."""
    import sunstone
    from sunstone.lineage import Metadata

    pdf = tmp_path / "foo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall")

    asset = sunstone.read(str(pdf), metadata=Metadata(slug="x"))
    assert asset.metadata.slug == "x"


def test_read_extras_override_replaces_handler_extras(tmp_path):
    """``extras=`` fully replaces the handler's extras dict (no merge)."""
    import sunstone

    pdf = tmp_path / "foo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall")

    asset = sunstone.read(str(pdf), extras={"custom": "value"})
    # Handler-produced ``media_type`` is gone; only the override remains.
    assert asset.extras == {"custom": "value"}


def test_read_kind_override_replaces_handler_kind(tmp_path):
    """``kind=`` overrides even when the file is clearly a PDF (BLOB).

    Contrived but documents the override semantics: catalog rows are the
    source of truth when reconstructing Assets.
    """
    import sunstone

    pdf = tmp_path / "foo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall")

    asset = sunstone.read(str(pdf), kind=sunstone.AssetKind.RASTER)
    assert asset.kind is sunstone.AssetKind.RASTER


def test_read_all_three_overrides_applied_together(tmp_path):
    import sunstone
    from sunstone.lineage import Metadata

    pdf = tmp_path / "foo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsmall")

    asset = sunstone.read(
        str(pdf),
        kind=sunstone.AssetKind.RASTER,
        metadata=Metadata(slug="catalog-row"),
        extras={"from": "catalog"},
    )
    assert asset.kind is sunstone.AssetKind.RASTER
    assert asset.metadata.slug == "catalog-row"
    assert asset.extras == {"from": "catalog"}


def test_read_uses_datasets_yaml_format_field(tmp_path, monkeypatch):
    """When a `datasets.yaml` entry declares `format: csv` for a path with a
    misleading extension, dispatch should follow the declared format."""
    import sunstone

    project = tmp_path
    (project / "datasets.yaml").write_text(
        "inputs:\n  - name: Weird\n    slug: weird\n    location: inputs/data.bin\n    format: csv\n"
    )
    (project / "inputs").mkdir()
    (project / "inputs" / "data.bin").write_text("x,y\n1,2\n")

    monkeypatch.chdir(project)
    sunstone.set_project_path(project)

    asset = sunstone.read("inputs/data.bin")  # no explicit format=
    assert asset.kind is sunstone.AssetKind.TABULAR
    assert list(asset.payload.columns) == ["x", "y"]
