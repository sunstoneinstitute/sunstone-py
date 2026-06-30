"""Tests for sunstone.polars.DataFrame facade (Task 8)."""

import pytest

pl = pytest.importorskip("polars")
from sunstone.asset import Asset, AssetKind  # noqa: E402
from sunstone.lineage import Metadata  # noqa: E402
from sunstone.polars import DataFrame  # noqa: E402


def test_construct_from_polars_frame() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2]}))
    assert df.asset.kind is AssetKind.TABULAR
    assert isinstance(df.data, pl.DataFrame)
    assert df.data.columns == ["a"]


def test_construct_from_asset() -> None:
    asset = Asset(payload=pl.DataFrame({"a": [1]}), kind=AssetKind.TABULAR, metadata=Metadata())
    df = DataFrame(asset=asset)
    assert df.asset is asset


def test_construct_from_pandas_converts() -> None:
    import pandas as pd

    df = DataFrame(pd.DataFrame({"a": [1, 2]}))
    assert isinstance(df.data, pl.DataFrame)


def test_construct_from_none_is_empty() -> None:
    df = DataFrame()
    assert isinstance(df.data, pl.DataFrame)
    assert df.data.height == 0


def test_construct_from_raw_dict() -> None:
    df = DataFrame({"a": [1, 2, 3]})
    assert df.data.columns == ["a"]
    assert len(df) == 3


def test_set_field_metadata_chainable() -> None:
    df = DataFrame(pl.DataFrame({"a": [1]}))
    out = df.set_field_metadata("a", description="amount", unit="kg")
    assert out is df
    assert df.metadata.field_metadata["a"].unit == "kg"


def test_set_field_metadata_source_records_field_derivation() -> None:
    df = DataFrame(pl.DataFrame({"a": [1]}))
    df.set_field_metadata("a", source="raw-input")
    derivations = df.metadata.lineage.field_derivations
    assert derivations is not None
    assert any(d.output_field == "a" and d.source_entity == "raw-input" for d in derivations)


def test_filter_returns_wrapped_with_parent_sources(project_path) -> None:
    import sunstone.polars as spl

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    out = df.filter(pl.col(df.data.columns[0]).is_not_null())
    assert isinstance(out, spl.DataFrame)
    assert out.metadata.lineage.sources == df.metadata.lineage.sources
    assert out.metadata.lineage.activity is None
    assert out.metadata.lineage.engine == "polars"


def test_scalar_attrs_pass_through() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3]}))
    assert df.height == 3
    assert df.columns == ["a"]
    assert df.shape == (3, 1)


def test_chained_ops_propagate_sources(project_path) -> None:
    import sunstone.polars as spl

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    col = df.data.columns[0]
    out = df.filter(pl.col(col).is_not_null()).select(col)
    assert isinstance(out, spl.DataFrame)
    assert out.metadata.lineage.sources == df.metadata.lineage.sources
    assert out.metadata.lineage.engine == "polars"


def test_getitem_dataframe_result_is_wrapped() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2], "b": [3, 4]}))
    out = df[["a", "b"]]  # column projection returns a polars DataFrame
    assert isinstance(out, DataFrame)
    assert out.data.columns == ["a", "b"]


def test_derived_frame_keeps_project_path(project_path) -> None:
    import sunstone.polars as spl

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    out = df.filter(pl.col(df.data.columns[0]).is_not_null())
    assert out.metadata.lineage.project_path == df.metadata.lineage.project_path


def test_unknown_symbols_forward_to_real_polars() -> None:
    import sunstone.polars as spl

    # Functions and dtypes not explicitly re-exported should resolve to the real polars objects.
    assert spl.concat is pl.concat
    assert spl.struct is pl.struct
    assert spl.Float64 is pl.Float64
    assert spl.LazyFrame is pl.LazyFrame


def test_nonexistent_symbol_raises_attribute_error() -> None:
    import sunstone.polars as spl

    with pytest.raises(AttributeError):
        spl.definitely_not_a_real_symbol


def test_facade_names_win_over_real_polars() -> None:
    import sunstone.polars as spl
    from sunstone.polars.core import DataFrame as FacadeDataFrame

    assert spl.DataFrame is FacadeDataFrame
    assert spl.DataFrame is not pl.DataFrame


def test_reader_wins_over_real_polars() -> None:
    import sunstone.polars as spl

    # The facade reader must not be shadowed by polars.read_csv.
    assert spl.read_csv is not pl.read_csv
    assert spl.read_csv.__module__ == "sunstone.polars.io"


def test_facade_submodule_not_shadowed_by_real_polars() -> None:
    # On a fresh import, accessing the bare `io` name must resolve to the facade
    # submodule, never the real polars.io (regression guard for the fallback).
    import subprocess
    import sys

    code = (
        "import sunstone.polars as spl, polars;"
        "assert spl.io is not polars.io, spl.io;"
        "assert spl.io.__name__ == 'sunstone.polars.io', spl.io.__name__;"
        "print('ok')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
