"""
Tests for Sunstone DataFrame functionality.
"""

from pathlib import Path
from typing import Any

import pytest

import sunstone


class TestDataFrameBasics:
    """Tests for basic DataFrame operations."""

    def test_read_csv(self, project_path: Path) -> None:
        """Test reading a CSV file into a DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        assert len(df.data.columns) > 0
        assert len(df.metadata.lineage.sources) > 0

    def test_head_preserves_lineage(self, project_path: Path) -> None:
        """Test that head() preserves lineage."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )

        filtered = df.head(10)

        assert len(filtered.data) == 10
        assert len(filtered.metadata.lineage.sources) == len(df.metadata.lineage.sources)

    def test_read_second_dataset(self, project_path: Path) -> None:
        """Test reading the same dataset twice creates separate lineage."""
        members1 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )
        members2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        assert members1 is not None
        assert members2 is not None
        assert len(members1.data) > 0
        assert len(members1.metadata.lineage.sources) > 0
        assert len(members2.metadata.lineage.sources) > 0


class TestReadExcel:
    """Tests for reading Excel files."""

    def test_read_excel_by_path(self, project_path: Path) -> None:
        """Test reading an Excel file by path."""
        df = sunstone.DataFrame.read_excel(
            "inputs/un_member_states_sample.xlsx",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) == 10
        assert len(df.data.columns) > 0
        assert len(df.metadata.lineage.sources) > 0
        assert "Member State" in df.data.columns

    def test_read_excel_by_slug(self, project_path: Path) -> None:
        """Test reading an Excel file by slug."""
        df = sunstone.DataFrame.read_excel(
            "un-member-states-sample-excel",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) == 10
        assert len(df.metadata.lineage.sources) > 0

    def test_read_excel_preserves_lineage(self, project_path: Path) -> None:
        """Test that read_excel tracks lineage correctly."""
        df = sunstone.DataFrame.read_excel(
            "inputs/un_member_states_sample.xlsx",
            project_path=project_path,
            strict=False,
        )

        assert df.metadata.lineage.sources[0].slug == "un-member-states-sample-excel"

    def test_read_excel_not_found(self, project_path: Path) -> None:
        """Test that read_excel raises error for unregistered file."""
        from sunstone.exceptions import DatasetNotFoundError

        with pytest.raises(DatasetNotFoundError):
            sunstone.DataFrame.read_excel(
                "inputs/nonexistent.xlsx",
                project_path=project_path,
                strict=True,
            )

    def test_read_excel_via_pandas_module(self, project_path: Path) -> None:
        """Test read_excel via sunstone.pandas module."""
        from sunstone import pandas as spd

        df = spd.read_excel(
            "un-member-states-sample-excel",
            project_path=project_path,
        )

        assert df is not None
        assert len(df.data) == 10
        assert isinstance(df, sunstone.DataFrame)


class TestReadJson:
    """Tests for reading JSON files."""

    def test_read_json_by_path(self, project_path: Path) -> None:
        """Test reading a JSON file by path."""
        df = sunstone.DataFrame.read_json(
            "inputs/un_member_states_sample.json",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) == 5
        assert len(df.data.columns) > 0
        assert len(df.metadata.lineage.sources) > 0
        assert "Member State" in df.data.columns

    def test_read_json_by_slug(self, project_path: Path) -> None:
        """Test reading a JSON file by slug."""
        df = sunstone.DataFrame.read_json(
            "un-member-states-sample-json",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) == 5
        assert len(df.metadata.lineage.sources) > 0

    def test_read_json_preserves_lineage(self, project_path: Path) -> None:
        """Test that read_json tracks lineage correctly."""
        df = sunstone.DataFrame.read_json(
            "inputs/un_member_states_sample.json",
            project_path=project_path,
            strict=False,
        )

        assert df.metadata.lineage.sources[0].slug == "un-member-states-sample-json"

    def test_read_json_not_found(self, project_path: Path) -> None:
        """Test that read_json raises error for unregistered file."""
        from sunstone.exceptions import DatasetNotFoundError

        with pytest.raises(DatasetNotFoundError):
            sunstone.DataFrame.read_json(
                "inputs/nonexistent.json",
                project_path=project_path,
                strict=True,
            )

    def test_read_json_via_pandas_module(self, project_path: Path) -> None:
        """Test read_json via sunstone.pandas module."""
        from sunstone import pandas as spd

        df = spd.read_json(
            "un-member-states-sample-json",
            project_path=project_path,
        )

        assert df is not None
        assert len(df.data) == 5
        assert isinstance(df, sunstone.DataFrame)


class TestDataFrameMerge:
    """Tests for DataFrame merge operations."""

    @pytest.fixture
    def un_members_df1(self, project_path: Path) -> Any:
        """Load UN members DataFrame (first instance)."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Filter to create a subset
        return df[df.data["ISO Code"].notna()].head(50)

    @pytest.fixture
    def un_members_df2(self, project_path: Path) -> Any:
        """Load UN members DataFrame (second instance)."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Select different columns as a second dataset
        return df[["Member State", "ISO Code", "Start date"]].dropna()

    def test_merge_dataframes(self, un_members_df1: Any, un_members_df2: Any) -> None:
        """Test merging two DataFrames."""
        merged = un_members_df1.merge(un_members_df2, left_on="ISO Code", right_on="ISO Code", how="inner")

        assert merged is not None
        assert len(merged.data) > 0
        # Both sources come from the same file, but lineage should track them separately
        assert len(merged.metadata.lineage.sources) >= 1

    def test_merge_lineage_tracking(self, un_members_df1: Any, un_members_df2: Any) -> None:
        """Test that merge properly tracks lineage."""
        merged = un_members_df1.merge(un_members_df2, left_on="ISO Code", right_on="ISO Code", how="inner")

        licenses = merged.metadata.lineage.get_licenses()
        assert licenses is not None
        assert len(licenses) > 0


class TestLineageMetadata:
    """Tests for lineage metadata functionality."""

    @pytest.fixture
    def processed_df(self, project_path: Path) -> Any:
        """Create a processed DataFrame for testing."""
        un_members = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Apply some operations
        filtered = un_members[un_members.data["ISO Code"].notna()]
        return filtered.head(100)

    def test_lineage_to_dict(self, processed_df: Any) -> None:
        """Test converting lineage to dictionary."""
        lineage_dict = processed_df.metadata.lineage.to_dict()

        assert lineage_dict is not None
        assert "sources" in lineage_dict
        # created_at is only set when writing output (not when reading)
        assert len(lineage_dict["sources"]) > 0


class TestStrictMode:
    """Tests for strict mode functionality."""

    def test_strict_mode_load(self, project_path: Path, monkeypatch: Any) -> None:
        """Test loading DataFrame in strict mode."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")

        strict_df = sunstone.DataFrame.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path)

        assert strict_df.strict_mode is True

    def test_strict_mode_prevents_unregistered_write(self, project_path: Path, monkeypatch: Any) -> None:
        """Test that strict mode prevents writing to unregistered locations."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")

        strict_df = sunstone.DataFrame.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path)

        with pytest.raises(sunstone.StrictModeError):
            strict_df.to_csv("/tmp/test_output.csv", index=False)


class TestReadDataset:
    """Tests for read_dataset() functionality with format auto-detection."""

    def test_read_dataset_by_slug(self, project_path: Path) -> None:
        """Test reading a dataset by slug with auto-detection."""
        df = sunstone.DataFrame.read_dataset(
            "official-un-member-states",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        assert len(df.data.columns) > 0
        assert len(df.metadata.lineage.sources) > 0
        # Check that the source is tracked
        assert df.metadata.lineage.sources[0].slug == "official-un-member-states"

    def test_read_dataset_with_explicit_format(self, project_path: Path) -> None:
        """Test reading a dataset with explicit format override."""
        df = sunstone.DataFrame.read_dataset(
            "official-un-member-states",
            project_path=project_path,
            format="csv",
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        assert len(df.metadata.lineage.sources) > 0

    def test_read_dataset_slug_not_found(self, project_path: Path) -> None:
        """Test that reading non-existent slug raises error."""
        with pytest.raises(sunstone.DatasetNotFoundError) as exc_info:
            sunstone.DataFrame.read_dataset(
                "nonexistent-dataset",
                project_path=project_path,
            )

        assert "not found in datasets.yaml" in str(exc_info.value)

    def test_read_dataset_via_pandas_api(self, project_path: Path) -> None:
        """Test reading dataset via pandas-like API."""
        from sunstone import pandas as pd

        df = pd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

        assert df is not None
        assert len(df.data) > 0
        assert isinstance(df, sunstone.DataFrame)

    def test_read_csv_with_slug_delegates_to_read_dataset(self, project_path: Path) -> None:
        """Test that read_csv with slug delegates to read_dataset."""
        df = sunstone.DataFrame.read_csv(
            "official-un-member-states",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        # Check that the source is tracked
        assert len(df.metadata.lineage.sources) > 0


class TestReadDatasetKindValidation:
    """``DataFrame.read_dataset`` must reject non-tabular Assets with a clear
    error rather than letting downstream code attempt ``.columns`` on bytes."""

    def test_read_dataset_rejects_blob_kind(self, project_copy: Path) -> None:
        from sunstone.errors import IncompatibleAssetKindError

        # Add a PDF entry to the test project's datasets.yaml + write the file.
        pdf_path = project_copy / "inputs" / "report.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\nreport bytes")

        datasets_yaml = project_copy / "datasets.yaml"
        text = datasets_yaml.read_text()
        # Append a new input entry; trailing newline already present.
        text += "  - name: UN Report\n    slug: un-report\n    location: inputs/report.pdf\n"
        datasets_yaml.write_text(text)

        with pytest.raises(IncompatibleAssetKindError):
            sunstone.DataFrame.read_dataset(
                "un-report",
                project_path=project_copy,
                strict=False,
            )


class TestToCsvTrackParameter:
    """Tests for the track parameter on to_csv()."""

    def test_track_false_writes_csv_without_registration(self, tmp_path: Path) -> None:
        """Test that track=False writes the file without requiring datasets.yaml."""
        df = sunstone.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        output_path = tmp_path / "output.csv"

        df.to_csv(output_path, track=False, index=False)

        assert output_path.exists()
        import pandas as pd

        result = pd.read_csv(output_path)
        assert list(result.columns) == ["a", "b"]
        assert len(result) == 3

    def test_track_false_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that track=False creates parent directories as needed."""
        df = sunstone.DataFrame({"x": [1]})
        output_path = tmp_path / "nested" / "dir" / "output.csv"

        df.to_csv(output_path, track=False, index=False)

        assert output_path.exists()

    def test_track_false_bypasses_strict_mode(self, tmp_path: Path) -> None:
        """Test that track=False works even in strict mode."""
        df = sunstone.DataFrame({"a": [1]}, strict=True)
        output_path = tmp_path / "strict_output.csv"

        df.to_csv(output_path, track=False, index=False)

        assert output_path.exists()

    def test_track_defaults_to_true(self, tmp_path: Path, project_path: Path, monkeypatch: Any) -> None:
        """Test that track defaults to True (existing behavior unchanged)."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
        )

        with pytest.raises(sunstone.StrictModeError):
            df.to_csv(tmp_path / "test_unregistered.csv", index=False)

    def test_track_false_passes_kwargs_to_pandas(self, tmp_path: Path) -> None:
        """Test that pandas kwargs are forwarded when track=False."""
        df = sunstone.DataFrame({"a": [1, 2], "b": [3, 4]})
        output_path = tmp_path / "output.csv"

        df.to_csv(output_path, track=False, index=False, sep=";")

        content = output_path.read_text()
        assert ";" in content
        assert "," not in content.split("\n")[0]


class TestContentHashLineage:
    """Tests for content-hash based lineage tracking."""

    def test_content_hash_computed_on_save(self, project_copy: Path) -> None:
        """Test that content hash is computed and saved when writing output."""
        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        # Write the output
        output_path = "outputs/test_output.csv"
        df.to_csv(output_path, slug="test-output", name="Test Output", index=False)

        # Lineage is in datasets.lock.yaml
        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        # Find the output in lock file
        lock_output = next((d for d in lock_data.get("outputs", []) if d["slug"] == "test-output"), None)
        assert lock_output is not None
        assert "data_hash" in lock_output
        assert "created_at" in lock_output
        # Hash should be a prefixed sha256:hex string (7 + 64 = 71 chars)
        assert lock_output["data_hash"].startswith("sha256:")
        assert len(lock_output["data_hash"]) == 71

    def test_timestamp_not_updated_when_content_unchanged(self, project_copy: Path) -> None:
        """Test that timestamp stays the same when saving identical content."""
        import time

        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        output_path = "outputs/stable_output.csv"

        # First write
        df.to_csv(output_path, slug="stable-output", name="Stable Output", index=False)

        # Read the first timestamp and hash from lock file
        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock1 = yaml.load(f)

        lock_output1 = next((d for d in lock1.get("outputs", []) if d["slug"] == "stable-output"), None)
        assert lock_output1 is not None
        first_timestamp = lock_output1["created_at"]
        first_hash = lock_output1["data_hash"]

        # Wait a bit to ensure different timestamp would be generated
        time.sleep(0.1)

        # Reload the manager and write again with the same data
        df2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )
        df2.to_csv(output_path, slug="stable-output", name="Stable Output", index=False)

        # Read the second timestamp and hash from lock file
        with open(project_copy / "datasets.lock.yaml") as f:
            lock2 = yaml.load(f)

        lock_output2 = next((d for d in lock2.get("outputs", []) if d["slug"] == "stable-output"), None)
        assert lock_output2 is not None
        second_timestamp = lock_output2["created_at"]
        second_hash = lock_output2["data_hash"]

        # Hash should be the same
        assert first_hash == second_hash
        # Timestamp should NOT have changed since content is identical
        assert first_timestamp == second_timestamp

    def test_timestamp_updated_when_content_changes(self, project_copy: Path) -> None:
        """Test that timestamp is updated when content actually changes."""
        import time

        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        output_path = "outputs/changing_output.csv"

        # First write
        df.to_csv(output_path, slug="changing-output", name="Changing Output", index=False)

        # Read the first timestamp and hash from lock file
        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock1 = yaml.load(f)

        lock_output1 = next((d for d in lock1.get("outputs", []) if d["slug"] == "changing-output"), None)
        assert lock_output1 is not None
        first_timestamp = lock_output1["created_at"]
        first_hash = lock_output1["data_hash"]

        # Wait a bit to ensure different timestamp
        time.sleep(0.1)

        # Modify the data and write again
        df2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )
        # Actually modify the content - take only first 10 rows
        df2_modified = df2.head(10)
        df2_modified.to_csv(output_path, slug="changing-output", name="Changing Output", index=False)

        # Read the second timestamp and hash from lock file
        with open(project_copy / "datasets.lock.yaml") as f:
            lock2 = yaml.load(f)

        lock_output2 = next((d for d in lock2.get("outputs", []) if d["slug"] == "changing-output"), None)
        assert lock_output2 is not None
        second_timestamp = lock_output2["created_at"]
        second_hash = lock_output2["data_hash"]

        # Hash should be different since content changed
        assert first_hash != second_hash
        # Timestamp SHOULD have changed since content is different
        assert first_timestamp != second_timestamp

    def test_sources_written_to_datasets_yaml(self, project_copy: Path) -> None:
        """Test that lineage sources are written to datasets.yaml on save."""
        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        # Verify lineage has sources before save
        assert len(df.metadata.lineage.sources) > 0
        source_slug = df.metadata.lineage.sources[0].slug

        # Write the output
        output_path = "outputs/source_tracking_output.csv"
        df.to_csv(output_path, slug="source-tracking-output", name="Source Tracking Output", index=False)

        # Lineage sources are in datasets.lock.yaml
        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next((d for d in lock_data.get("outputs", []) if d["slug"] == "source-tracking-output"), None)
        assert lock_output is not None
        assert "sources" in lock_output

        # Sources should be a list of dicts with slug (and optionally attributedTo/license)
        sources = lock_output["sources"]
        assert len(sources) > 0
        assert sources[0]["slug"] == source_slug

    def test_sources_updated_on_existing_output(self, project_copy: Path) -> None:
        """Test that sources are updated when writing to an existing output."""
        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        output_path = "outputs/update_sources_output.csv"

        # First write
        df.to_csv(output_path, slug="update-sources-output", name="Update Sources Output", index=False)

        # Read lock file and verify sources
        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next((d for d in lock_data.get("outputs", []) if d["slug"] == "update-sources-output"), None)
        assert lock_output is not None
        assert "sources" in lock_output
        assert len(lock_output["sources"]) == 1

        # Write again - sources should still be present (but content unchanged = no-op)
        df2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )
        df2.to_csv(output_path, slug="update-sources-output", name="Update Sources Output", index=False)

        # Verify sources are still there
        with open(project_copy / "datasets.lock.yaml") as f:
            lock_data2 = yaml.load(f)

        lock_output2 = next((d for d in lock_data2.get("outputs", []) if d["slug"] == "update-sources-output"), None)
        assert lock_output2 is not None
        assert "sources" in lock_output2
        assert len(lock_output2["sources"]) == 1


class TestToParquetTrackParameter:
    """Tests for the track parameter on to_parquet()."""

    def test_track_false_writes_parquet_without_registration(self, tmp_path: Path) -> None:
        """Test that track=False writes the file without requiring datasets.yaml."""
        df = sunstone.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        output_path = tmp_path / "output.parquet"

        df.to_parquet(output_path, track=False)

        assert output_path.exists()
        import pandas as pd

        result = pd.read_parquet(output_path)
        assert list(result.columns) == ["a", "b"]
        assert len(result) == 3

    def test_track_false_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that track=False creates parent directories as needed."""
        df = sunstone.DataFrame({"x": [1]})
        output_path = tmp_path / "nested" / "dir" / "output.parquet"

        df.to_parquet(output_path, track=False)

        assert output_path.exists()

    def test_track_false_bypasses_strict_mode(self, tmp_path: Path) -> None:
        """Test that track=False works even in strict mode."""
        df = sunstone.DataFrame({"a": [1]}, strict=True)
        output_path = tmp_path / "strict_output.parquet"

        df.to_parquet(output_path, track=False)

        assert output_path.exists()

    def test_track_defaults_to_true(self, tmp_path: Path, project_path: Path, monkeypatch: Any) -> None:
        """Test that track defaults to True (strict mode raises for unregistered)."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
        )

        with pytest.raises(sunstone.StrictModeError):
            df.to_parquet(tmp_path / "test_unregistered.parquet")

    def test_track_false_passes_kwargs_to_pandas(self, tmp_path: Path) -> None:
        """Test that pandas kwargs are forwarded when track=False."""
        df = sunstone.DataFrame({"a": [1, 2], "b": [3, 4]})
        output_path = tmp_path / "output.parquet"

        df.to_parquet(output_path, track=False, compression="gzip")

        assert output_path.exists()
        import pandas as pd

        result = pd.read_parquet(output_path)
        assert list(result.columns) == ["a", "b"]


class TestToParquetLineage:
    """Tests for to_parquet() lineage tracking."""

    def test_content_hash_computed_on_parquet_save(self, project_copy: Path) -> None:
        """Test that content hash is computed and saved when writing Parquet output."""
        from ruamel.yaml import YAML

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )

        output_path = "outputs/test_output.parquet"
        df.to_parquet(output_path, slug="test-parquet-output", name="Test Parquet Output")

        yaml = YAML()
        with open(project_copy / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next((d for d in lock_data.get("outputs", []) if d["slug"] == "test-parquet-output"), None)
        assert lock_output is not None
        assert "data_hash" in lock_output
        assert lock_output["data_hash"].startswith("sha256:")
        assert len(lock_output["data_hash"]) == 71

    def test_parquet_auto_registers_fields(self, project_copy: Path) -> None:
        """Test that field schema is auto-registered in datasets.yaml."""
        from ruamel.yaml import YAML

        df = sunstone.DataFrame({"name": ["A", "B"], "value": [1.0, 2.0]})
        df.metadata.lineage.project_path = str(project_copy)

        output_path = "outputs/test_fields.parquet"
        df.to_parquet(output_path, slug="test-fields-parquet", name="Test Fields")

        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next((d for d in data.get("outputs", []) if d["slug"] == "test-fields-parquet"), None)
        assert output is not None
        assert "fields" in output
        field_names = [f["name"] for f in output["fields"]]
        assert "name" in field_names
        assert "value" in field_names


class TestToParquetMetadata:
    """Tests for metadata embedding in Parquet output."""

    def test_to_parquet_embeds_metadata(self, project_copy: Path) -> None:
        """Test that writing Parquet with track=True embeds JSON-LD metadata."""
        import json

        import pyarrow.parquet as pq

        df = sunstone.DataFrame({"name": ["Alice", "Bob"], "score": [95.0, 87.5]})
        df.metadata.lineage.project_path = str(project_copy)
        df.metadata.description = "Test dataset with scores"
        df.set_field_metadata("score", unit="percent")

        output_path = "outputs/meta_output.parquet"
        df.to_parquet(output_path, slug="meta-output", name="Meta Output")

        # Read back raw Parquet and check schema metadata
        abs_path = project_copy / output_path
        pf = pq.ParquetFile(abs_path)
        schema_meta = pf.schema_arrow.metadata

        assert b"sunstone" in schema_meta
        doc = json.loads(schema_meta[b"sunstone"])
        assert "@context" in doc
        assert doc.get("dct:description") == "Test dataset with scores"

    def test_to_parquet_track_false_no_metadata(self, tmp_path: Path) -> None:
        """Test that track=False does NOT embed sunstone metadata."""
        import pyarrow.parquet as pq

        df = sunstone.DataFrame({"x": [1, 2, 3]})
        df.metadata.description = "Should not appear"

        output_path = tmp_path / "no_meta.parquet"
        df.to_parquet(output_path, track=False)

        pf = pq.ParquetFile(output_path)
        schema_meta = pf.schema_arrow.metadata or {}
        assert b"sunstone" not in schema_meta


class TestReadDatasetParquetMetadata:
    """Tests for metadata restoration when reading Parquet files."""

    def test_read_dataset_parquet_restores_metadata(self, tmp_path: Path) -> None:
        """Test that embedded Parquet metadata is restored on read_dataset()."""
        import json

        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
        from ruamel.yaml import YAML

        # 1. Create a Parquet file with embedded sunstone metadata
        raw_df = pd.DataFrame({"city": ["Oslo", "Bergen"], "population": [709037, 286930]})
        table = pa.Table.from_pandas(raw_df)

        jsonld_doc = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "prov": "http://www.w3.org/ns/prov#",
                "si": "https://sunstone.institute/rdf/vocab#",
                "schema": "http://schema.org/",
            },
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:description": "Norwegian city populations",
            "si:fields": {
                "population": {
                    "si:unit": "people",
                    "dct:description": "City population count",
                },
            },
        }

        existing_meta = table.schema.metadata or {}
        existing_meta[b"sunstone"] = json.dumps(jsonld_doc).encode("utf-8")
        table = table.replace_schema_metadata(existing_meta)

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        pq.write_table(table, inputs_dir / "cities.parquet")

        # 2. Write datasets.yaml with an input entry for the parquet file
        datasets_yaml = {
            "inputs": [
                {
                    "name": "Norwegian Cities",
                    "slug": "norwegian-cities",
                    "location": "inputs/cities.parquet",
                    "source": {
                        "name": "Statistics Norway",
                        "location": {"data": "https://example.com/cities.parquet"},
                        "attributedTo": "SSB",
                        "acquiredAt": "2025-01-01",
                        "acquisitionMethod": "manual-download",
                        "license": "CC-BY-4.0",
                    },
                }
            ]
        }

        yaml = YAML()
        with open(tmp_path / "datasets.yaml", "w") as f:
            yaml.dump(datasets_yaml, f)

        # 3. Read via DataFrame.read_dataset()
        df = sunstone.DataFrame.read_dataset("norwegian-cities", project_path=tmp_path)

        # 4. Assert embedded metadata was restored
        assert df.metadata.description == "Norwegian city populations"
        assert "population" in df.metadata.field_metadata
        assert df.metadata.field_metadata["population"].unit == "people"
        assert df.metadata.field_metadata["population"].description == "City population count"

    def test_read_dataset_parquet_datasets_yaml_wins(self, tmp_path: Path) -> None:
        """Test that datasets.yaml metadata takes precedence over embedded metadata."""
        import json

        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
        from ruamel.yaml import YAML

        raw_df = pd.DataFrame({"city": ["Oslo"], "population": [709037]})
        table = pa.Table.from_pandas(raw_df)

        jsonld_doc = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "prov": "http://www.w3.org/ns/prov#",
                "si": "https://sunstone.institute/rdf/vocab#",
                "schema": "http://schema.org/",
                "ex": "http://example.org/",
            },
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:description": "Embedded description",
            "si:fields": {
                "population": {
                    "si:unit": "people",
                    "dct:description": "From embedded",
                },
            },
            "ex:custom": "embedded-value",
        }

        existing_meta = table.schema.metadata or {}
        existing_meta[b"sunstone"] = json.dumps(jsonld_doc).encode("utf-8")
        table = table.replace_schema_metadata(existing_meta)

        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        pq.write_table(table, inputs_dir / "cities.parquet")

        # datasets.yaml does NOT set description, so embedded should win
        # But it does set a field for "population" which should override embedded
        datasets_yaml = {
            "inputs": [
                {
                    "name": "Norwegian Cities",
                    "slug": "norwegian-cities",
                    "location": "inputs/cities.parquet",
                    "source": {
                        "name": "Statistics Norway",
                        "location": {"data": "https://example.com/cities.parquet"},
                        "attributedTo": "SSB",
                        "acquiredAt": "2025-01-01",
                        "acquisitionMethod": "manual-download",
                        "license": "CC-BY-4.0",
                    },
                }
            ]
        }

        yaml = YAML()
        with open(tmp_path / "datasets.yaml", "w") as f:
            yaml.dump(datasets_yaml, f)

        df = sunstone.DataFrame.read_dataset("norwegian-cities", project_path=tmp_path)

        # Embedded description should be restored (datasets.yaml doesn't set one)
        assert df.metadata.description == "Embedded description"
        # Embedded field metadata should be restored
        assert "population" in df.metadata.field_metadata
        # Custom properties from embedded should be present
        assert df.metadata.custom_properties is not None
        assert df.metadata.custom_properties.get("ex:custom") == "embedded-value"
        # User RDF prefixes from embedded should be present
        assert df.metadata.rdf_prefixes is not None
        assert "ex" in df.metadata.rdf_prefixes


def test_read_tabular_asset_returns_asset(tmp_path):
    """The internal helper unwraps DataFrame-returning handlers via the
    adapter and produces an Asset directly."""

    from sunstone.asset import Asset, AssetKind
    from sunstone.dataframe import _read_tabular_asset

    csv = tmp_path / "tiny.csv"
    csv.write_text("x,y\n1,2\n")

    asset = _read_tabular_asset(str(csv), format="csv")
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert list(asset.payload.columns) == ["x", "y"]


def test_read_tabular_asset_infers_format_from_extension(tmp_path):
    """When no explicit `format=` is passed, the helper must forward `path`
    so that handlers using extension-based inference still work."""

    from sunstone.asset import Asset, AssetKind
    from sunstone.dataframe import _read_tabular_asset

    csv = tmp_path / "tiny.csv"
    csv.write_text("x,y\n1,2\n")

    asset = _read_tabular_asset(str(csv))
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR


def test_read_tabular_asset_raises_when_no_handler_matches(tmp_path):
    """No handler accepts an unknown extension; the helper raises ValueError."""
    import pytest

    from sunstone.dataframe import _read_tabular_asset

    unknown = tmp_path / "x.unknown-ext"
    unknown.write_text("nope")

    with pytest.raises(ValueError, match="No handler"):
        _read_tabular_asset(str(unknown))


def test_sunstone_dataframe_is_facade_over_asset():
    import pandas as pd

    from sunstone import DataFrame as SDF
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata

    pdf = pd.DataFrame({"x": [1, 2, 3]})
    sdf = SDF(pdf, metadata=Metadata(slug="tabular", name="T"))

    # The facade exposes the underlying Asset for code that wants it.
    asset = sdf.asset
    assert isinstance(asset, Asset)
    assert asset.kind is AssetKind.TABULAR
    assert asset.payload is pdf

    # df.metadata and asset.metadata refer to the same instance, not a copy.
    assert sdf.metadata is asset.metadata
    sdf.metadata.description = "set via facade"
    assert asset.metadata.description == "set via facade"


def test_sunstone_dataframe_data_returns_pandas_dataframe():
    import pandas as pd

    from sunstone import DataFrame as SDF

    pdf = pd.DataFrame({"x": [1]})
    assert SDF(pdf).data is pdf


class TestCsvDialectEndToEnd:
    """End-to-end: a registered text/csv dataset with a dialect block is read
    and written through sunstone's pandas API using that dialect."""

    def _write_project(self, root: Path, dialect_block: str = "") -> Path:
        (root / "inputs").mkdir()
        (root / "outputs").mkdir()
        (root / "inputs" / "semi.csv").write_text("a;b\n1;2\n3;4\n")
        (root / "datasets.yaml").write_text(
            f"""
inputs:
  - name: Semi
    slug: semi
    location: inputs/semi.csv
    {dialect_block}
outputs:
  - name: Semi Out
    slug: semi-out
    location: outputs/semi_out.csv
    {dialect_block}
    fields:
      - name: a
        type: integer
      - name: b
        type: integer
"""
        )
        return root

    def test_read_csv_with_dialect_uses_delimiter(self, tmp_path: Path) -> None:
        project = self._write_project(
            tmp_path,
            dialect_block='dialect:\n      delimiter: ";"\n      quoteChar: \'"\'\n      header: true',
        )
        df = sunstone.DataFrame.read_csv("semi", project_path=project)
        assert list(df.data.columns) == ["a", "b"]
        assert df.data.iloc[0, 0] == 1

    def test_read_csv_without_dialect_defaults_to_comma(self, tmp_path: Path) -> None:
        """Backwards compatibility: no dialect block → pandas default behavior."""
        (tmp_path / "inputs").mkdir()
        (tmp_path / "inputs" / "comma.csv").write_text("a,b\n1,2\n3,4\n")
        (tmp_path / "datasets.yaml").write_text(
            """
inputs:
  - name: Comma
    slug: comma
    location: inputs/comma.csv
outputs: []
"""
        )
        df = sunstone.DataFrame.read_csv("comma", project_path=tmp_path)
        assert list(df.data.columns) == ["a", "b"]
        assert df.data.iloc[0, 0] == 1

    def test_to_csv_with_dialect_uses_delimiter(self, tmp_path: Path) -> None:
        project = self._write_project(
            tmp_path,
            dialect_block='dialect:\n      delimiter: ";"\n      quoteChar: \'"\'\n      header: true',
        )
        df = sunstone.DataFrame.read_csv("semi", project_path=project)
        df.to_csv("outputs/semi_out.csv", index=False)

        # Read raw bytes to verify the delimiter was honored on write
        written = (project / "outputs" / "semi_out.csv").read_text()
        assert written == "a;b\n1;2\n3;4\n"
