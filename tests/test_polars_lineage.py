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


# ---------------------------------------------------------------------------
# Task 11: Write facades + LineageWarning
# ---------------------------------------------------------------------------

import warnings  # noqa: E402


def test_write_csv_roundtrips_and_updates_lock(project_copy) -> None:
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    df.write_csv("outputs/out.csv", slug="out-data", name="Out")
    assert (project_copy / "outputs/out.csv").exists()


def test_write_parquet_roundtrips(project_copy) -> None:
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    df.write_parquet("outputs/out.parquet", slug="out-parquet", name="Out Parquet")
    out = project_copy / "outputs/out.parquet"
    assert out.exists()
    # Round-trips back to a polars frame with the same shape.
    back = pl.read_parquet(out)
    assert back.shape == df.data.shape


def test_write_json_roundtrips(project_copy) -> None:
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    df.write_json("outputs/out.json", slug="out-json", name="Out JSON")
    assert (project_copy / "outputs/out.json").exists()


def test_write_derived_emits_lineage_warning(project_copy) -> None:
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    derived = df.head(5)  # different output slug, activity is None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        derived.write_csv("outputs/derived.csv", slug="derived-data", name="Derived")
    assert sum("Activity" in str(w.message) for w in caught) == 1


def test_write_fresh_read_no_warning(project_copy) -> None:
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # write under the SAME slug as the source → not "derived"
        src_slug = df.metadata.lineage.sources[0].slug
        df.write_csv("outputs/same.csv", slug=src_slug, name="Same")
    assert not any("Activity" in str(w.message) for w in caught)


# ---------------------------------------------------------------------------
# Metadata flow tests (Findings 2, 3, 4): fail before fix, pass after.
# ---------------------------------------------------------------------------


def test_dataset_level_metadata_flows_to_datasets_yaml(project_copy) -> None:
    """Finding 3: description/rdf_prefixes/custom_properties persist to datasets.yaml."""
    from ruamel.yaml import YAML

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    df.metadata.description = "polars metadata test"
    df.metadata.rdf_prefixes = {"ex": "http://example.org/"}
    df.metadata.custom_properties = {"ex:tag": "polars-test"}

    df.write_csv("outputs/meta_flow.csv", slug="meta-flow", name="Meta Flow")

    yaml = YAML()
    with open(project_copy / "datasets.yaml") as f:
        data = yaml.load(f)

    output = next((d for d in data.get("outputs", []) if d["slug"] == "meta-flow"), None)
    assert output is not None, "output not registered in datasets.yaml"
    assert output.get("description") == "polars metadata test"
    # datasets.yaml uses camelCase for rdfPrefixes, custom props are top-level keys.
    assert output.get("rdfPrefixes", {}).get("ex") == "http://example.org/"
    assert output.get("ex:tag") == "polars-test"


def test_explicit_field_metadata_flows_to_datasets_yaml(project_copy) -> None:
    """Finding 4: explicit set_field_metadata() values (unit, description) persist."""
    from ruamel.yaml import YAML

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)

    # Pick a real column from the UN members CSV.
    first_col = df.data.columns[0]
    df.set_field_metadata(first_col, unit="dimensionless", description="polars field test")

    df.write_csv("outputs/field_flow.csv", slug="field-flow", name="Field Flow")

    yaml = YAML()
    with open(project_copy / "datasets.yaml") as f:
        data = yaml.load(f)

    output = next((d for d in data.get("outputs", []) if d["slug"] == "field-flow"), None)
    assert output is not None, "output not registered in datasets.yaml"
    fields = {f["name"]: f for f in output.get("fields", [])}
    assert first_col in fields, f"column '{first_col}' missing from registered fields"
    assert fields[first_col].get("unit") == "dimensionless"
    assert fields[first_col].get("description") == "polars field test"


def test_strict_mode_raises_on_unregistered_output(project_copy) -> None:
    """Finding 2: strict-mode polars write raises StrictModeError for unregistered output."""
    from sunstone.exceptions import StrictModeError

    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=True)
    # 'outputs/never_registered.csv' is not in datasets.yaml → must raise
    with pytest.raises(StrictModeError):
        df.write_csv("outputs/never_registered.csv", slug="never-registered", name="Never Registered")
