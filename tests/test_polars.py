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
