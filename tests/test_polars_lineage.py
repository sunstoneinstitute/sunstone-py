"""Lineage tests for sunstone.polars read facades (Task 9)."""

import hashlib

import pytest

pl = pytest.importorskip("polars")
import sunstone.polars as spl  # noqa: E402
from sunstone.exceptions import DatasetNotFoundError  # noqa: E402

CSV = "inputs/official_un_member_states_raw.csv"
CSV_SLUG = "official-un-member-states"


def test_read_csv_returns_facade_with_polars_payload(project_path) -> None:
    df = spl.read_csv(CSV, project_path=project_path, strict=False)
    assert isinstance(df, spl.DataFrame)
    assert isinstance(df.data, pl.DataFrame)
    assert df.data.height > 0


def test_read_csv_lineage(project_path) -> None:
    df = spl.read_csv(CSV, project_path=project_path, strict=False)
    lin = df.metadata.lineage
    assert lin.engine == "polars"
    assert len(lin.sources) == 1
    assert lin.activity is None
    expected = "sha256:" + hashlib.sha256((project_path / CSV).read_bytes()).hexdigest()
    assert lin.data_hash == expected
    assert lin.field_derivations and len(lin.field_derivations) == len(df.data.columns)


def test_read_dataset_by_slug(project_path) -> None:
    df = spl.read_dataset(CSV_SLUG, project_path=project_path, strict=False)
    assert isinstance(df.data, pl.DataFrame)
    assert df.metadata.lineage.sources[0].slug == CSV_SLUG


def test_read_csv_by_slug_via_read_csv(project_path) -> None:
    # A bare slug (no separator, no suffix) routes through read_dataset.
    df = spl.read_csv(CSV_SLUG, project_path=project_path, strict=False)
    assert df.metadata.lineage.sources[0].slug == CSV_SLUG


def test_read_csv_unregistered_raises(project_path) -> None:
    # The raise is unconditional for an unregistered path (matches the pandas
    # sibling), regardless of the strict flag.
    with pytest.raises(DatasetNotFoundError):
        spl.read_csv("inputs/nope.csv", project_path=project_path, strict=True)


def test_read_unregistered_slug_raises(project_path) -> None:
    with pytest.raises(DatasetNotFoundError):
        spl.read_dataset("no-such-slug", project_path=project_path, strict=False)
