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
        assert len(df.lineage.sources) > 0

    def test_head_preserves_lineage(self, project_path: Path) -> None:
        """Test that head() preserves lineage."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )

        filtered = df.head(10)

        assert len(filtered.data) == 10
        assert len(filtered.lineage.sources) == len(df.lineage.sources)

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
        assert len(members1.lineage.sources) > 0
        assert len(members2.lineage.sources) > 0


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
        assert len(df.lineage.sources) > 0
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
        assert len(df.lineage.sources) > 0

    def test_read_excel_preserves_lineage(self, project_path: Path) -> None:
        """Test that read_excel tracks lineage correctly."""
        df = sunstone.DataFrame.read_excel(
            "inputs/un_member_states_sample.xlsx",
            project_path=project_path,
            strict=False,
        )

        assert df.lineage.sources[0].slug == "un-member-states-sample-excel"

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
        assert len(merged.lineage.sources) >= 1

    def test_merge_lineage_tracking(self, un_members_df1: Any, un_members_df2: Any) -> None:
        """Test that merge properly tracks lineage."""
        merged = un_members_df1.merge(un_members_df2, left_on="ISO Code", right_on="ISO Code", how="inner")

        licenses = merged.lineage.get_licenses()
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
        lineage_dict = processed_df.lineage.to_dict()

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
        assert len(df.lineage.sources) > 0
        # Check that the source is tracked
        assert df.lineage.sources[0].slug == "official-un-member-states"

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
        assert len(df.lineage.sources) > 0

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
        assert len(df.lineage.sources) > 0


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

        # Read the datasets.yaml and check for content_hash
        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data = yaml.load(f)

        # Find the output dataset
        output = next((d for d in data.get("outputs", []) if d["slug"] == "test-output"), None)
        assert output is not None
        assert "lineage" in output
        assert "content_hash" in output["lineage"]
        assert "created_at" in output["lineage"]
        # Hash should be a 64-character hex string (SHA256)
        assert len(output["lineage"]["content_hash"]) == 64

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

        # Read the first timestamp and hash
        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data1 = yaml.load(f)

        output1 = next((d for d in data1.get("outputs", []) if d["slug"] == "stable-output"), None)
        assert output1 is not None
        first_timestamp = output1["lineage"]["created_at"]
        first_hash = output1["lineage"]["content_hash"]

        # Wait a bit to ensure different timestamp would be generated
        time.sleep(0.1)

        # Reload the manager and write again with the same data
        df2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )
        df2.to_csv(output_path, slug="stable-output", name="Stable Output", index=False)

        # Read the second timestamp and hash
        with open(project_copy / "datasets.yaml") as f:
            data2 = yaml.load(f)

        output2 = next((d for d in data2.get("outputs", []) if d["slug"] == "stable-output"), None)
        assert output2 is not None
        second_timestamp = output2["lineage"]["created_at"]
        second_hash = output2["lineage"]["content_hash"]

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

        # Read the first timestamp and hash
        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data1 = yaml.load(f)

        output1 = next((d for d in data1.get("outputs", []) if d["slug"] == "changing-output"), None)
        assert output1 is not None
        first_timestamp = output1["lineage"]["created_at"]
        first_hash = output1["lineage"]["content_hash"]

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

        # Read the second timestamp and hash
        with open(project_copy / "datasets.yaml") as f:
            data2 = yaml.load(f)

        output2 = next((d for d in data2.get("outputs", []) if d["slug"] == "changing-output"), None)
        assert output2 is not None
        second_timestamp = output2["lineage"]["created_at"]
        second_hash = output2["lineage"]["content_hash"]

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
        assert len(df.lineage.sources) > 0
        source_slug = df.lineage.sources[0].slug

        # Write the output
        output_path = "outputs/source_tracking_output.csv"
        df.to_csv(output_path, slug="source-tracking-output", name="Source Tracking Output", index=False)

        # Read the datasets.yaml
        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data = yaml.load(f)

        # Find the output dataset
        output = next((d for d in data.get("outputs", []) if d["slug"] == "source-tracking-output"), None)
        assert output is not None
        assert "lineage" in output
        assert "sources" in output["lineage"]

        # Sources should be a list of dicts with just slug
        sources = output["lineage"]["sources"]
        assert len(sources) > 0
        assert sources[0] == {"slug": source_slug}

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

        # Read dataset.yaml and verify sources
        yaml = YAML()
        with open(project_copy / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next((d for d in data.get("outputs", []) if d["slug"] == "update-sources-output"), None)
        assert output is not None
        assert "sources" in output["lineage"]
        assert len(output["lineage"]["sources"]) == 1

        # Write again - sources should still be present
        df2 = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_copy,
            strict=False,
        )
        df2.to_csv(output_path, slug="update-sources-output", name="Update Sources Output", index=False)

        # Verify sources are still there
        with open(project_copy / "datasets.yaml") as f:
            data2 = yaml.load(f)

        output2 = next((d for d in data2.get("outputs", []) if d["slug"] == "update-sources-output"), None)
        assert output2 is not None
        assert "sources" in output2["lineage"]
        assert len(output2["lineage"]["sources"]) == 1
