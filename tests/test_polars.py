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


def test_group_by_agg_returns_facade_with_sources(project_path) -> None:
    import sunstone.polars as spl

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    col = df.data.columns[0]
    result = df.group_by(col).agg(spl.len())
    assert isinstance(result, spl.DataFrame)
    assert not isinstance(result, pl.DataFrame)
    assert result.metadata.lineage.sources == df.metadata.lineage.sources
    assert result.metadata.lineage.engine == "polars"


def test_group_by_agg_result_is_writable() -> None:
    df = DataFrame(pl.DataFrame({"k": ["a", "a", "b"], "v": [1, 2, 3]}))
    result = df.group_by("k").agg(pl.col("v").sum())
    assert isinstance(result, DataFrame)
    assert callable(getattr(result, "write_csv"))


def test_lazy_returns_proxy_not_raw_lazyframe() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3]}))
    lazy = df.lazy()
    assert not isinstance(lazy, pl.LazyFrame)


def test_lazy_roundtrip_returns_facade_with_sources(project_path) -> None:
    import sunstone.polars as spl

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    col = df.data.columns[0]
    result = df.lazy().filter(pl.col(col).is_not_null()).collect()
    assert isinstance(result, spl.DataFrame)
    assert not isinstance(result, pl.DataFrame)
    assert result.metadata.lineage.sources == df.metadata.lineage.sources
    assert result.metadata.lineage.engine == "polars"


def test_lazy_chain_stays_proxied_then_collects() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3, 4], "b": [10, 20, 30, 40]}))
    result = df.lazy().filter(pl.col("a") >= 2).select("b").collect()
    assert isinstance(result, DataFrame)
    assert not isinstance(result, pl.DataFrame)
    assert result.data.columns == ["b"]
    assert result.data.height == 3


def test_non_dataframe_intermediate_results_pass_through() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3]}))
    assert df.shape == (3, 1)
    assert isinstance(df.shape, tuple)
    assert df.columns == ["a"]
    assert isinstance(df.columns, list)


def test_group_by_remains_iterable() -> None:
    df = DataFrame(pl.DataFrame({"k": ["a", "a", "b"], "v": [1, 2, 3]}))
    groups = list(df.group_by("k"))
    assert len(groups) == 2
    # Iteration yields raw polars (key, sub_frame) tuples, matching pre-proxy behavior.
    for _key, sub in groups:
        assert isinstance(sub, pl.DataFrame)


def test_lazy_proxy_repr_preserves_underlying() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3]}))
    text = repr(df.lazy())
    assert "_Proxy" not in text
    assert "LazyFrame" in text


def test_group_by_dynamic_returns_facade() -> None:
    df = DataFrame(pl.DataFrame({"t": [0, 1, 2, 3, 4], "v": [1, 2, 3, 4, 5]}))
    result = df.group_by_dynamic("t", every="2i").agg(pl.col("v").sum())
    assert isinstance(result, DataFrame)
    assert not isinstance(result, pl.DataFrame)


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
