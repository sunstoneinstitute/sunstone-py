"""
Tests for Sunstone DataFrame functionality.
"""

from pathlib import Path

import pytest

import sunstone


class TestDataFrameBasics:
    """Tests for basic DataFrame operations."""

    def test_read_csv(self, project_path: Path):
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
        assert df.lineage.operations is not None

    def test_apply_operation(self, project_path: Path):
        """Test applying an operation to a DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )

        filtered = df.apply_operation(lambda d: d.head(10), description="Select first 10 rows")

        assert len(filtered.data) == 10
        assert len(filtered.lineage.operations) > len(df.lineage.operations)

    def test_read_second_dataset(self, project_path: Path):
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


class TestDataFrameMerge:
    """Tests for DataFrame merge operations."""

    @pytest.fixture
    def un_members_df1(self, project_path: Path):
        """Load UN members DataFrame (first instance)."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Filter to create a subset
        return df.apply_operation(
            lambda d: d[d["ISO Code"].notna()].head(50),
            description="Select first 50 countries with ISO codes",
        )

    @pytest.fixture
    def un_members_df2(self, project_path: Path):
        """Load UN members DataFrame (second instance)."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Select different columns as a second dataset
        return df.apply_operation(
            lambda d: d[["Member State", "ISO Code", "Start date"]].dropna(),
            description="Select subset of columns",
        )

    def test_merge_dataframes(self, un_members_df1, un_members_df2):
        """Test merging two DataFrames."""
        merged = un_members_df1.merge(un_members_df2, left_on="ISO Code", right_on="ISO Code", how="inner")

        assert merged is not None
        assert len(merged.data) > 0
        # Both sources come from the same file, but lineage should track them separately
        assert len(merged.lineage.sources) >= 1
        assert len(merged.lineage.operations) > 0

    def test_merge_lineage_tracking(self, un_members_df1, un_members_df2):
        """Test that merge properly tracks lineage."""
        merged = un_members_df1.merge(un_members_df2, left_on="ISO Code", right_on="ISO Code", how="inner")

        licenses = merged.lineage.get_licenses()
        assert licenses is not None
        assert len(licenses) > 0


class TestLineageMetadata:
    """Tests for lineage metadata functionality."""

    @pytest.fixture
    def processed_df(self, project_path: Path):
        """Create a processed DataFrame for testing."""
        un_members = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        # Apply some operations to build lineage
        filtered = un_members.apply_operation(
            lambda d: d[d["ISO Code"].notna()], description="Filter countries with ISO codes"
        )
        return filtered.apply_operation(lambda d: d.head(100), description="Select first 100 countries")

    def test_lineage_to_dict(self, processed_df):
        """Test converting lineage to dictionary."""
        lineage_dict = processed_df.lineage.to_dict()

        assert lineage_dict is not None
        assert "sources" in lineage_dict
        assert "operations" in lineage_dict
        assert "created_at" in lineage_dict
        assert "licenses" in lineage_dict
        assert len(lineage_dict["sources"]) > 0
        assert len(lineage_dict["operations"]) > 0


class TestStrictMode:
    """Tests for strict mode functionality."""

    def test_strict_mode_load(self, project_path: Path, monkeypatch):
        """Test loading DataFrame in strict mode."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")

        strict_df = sunstone.DataFrame.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path)

        assert strict_df.strict_mode is True

    def test_strict_mode_prevents_unregistered_write(self, project_path: Path, monkeypatch):
        """Test that strict mode prevents writing to unregistered locations."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")

        strict_df = sunstone.DataFrame.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path)

        with pytest.raises(sunstone.StrictModeError):
            strict_df.to_csv("/tmp/test_output.csv", index=False)


class TestReadDataset:
    """Tests for read_dataset() functionality with format auto-detection."""

    def test_read_dataset_by_slug(self, project_path: Path):
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
        # Check that the lineage operation mentions the format
        assert any("format=csv" in op for op in df.lineage.operations)

    def test_read_dataset_with_explicit_format(self, project_path: Path):
        """Test reading a dataset with explicit format override."""
        df = sunstone.DataFrame.read_dataset(
            "official-un-member-states",
            project_path=project_path,
            format="csv",
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        assert any("format=csv" in op for op in df.lineage.operations)

    def test_read_dataset_slug_not_found(self, project_path: Path):
        """Test that reading non-existent slug raises error."""
        with pytest.raises(sunstone.DatasetNotFoundError) as exc_info:
            sunstone.DataFrame.read_dataset(
                "nonexistent-dataset",
                project_path=project_path,
            )

        assert "not found in datasets.yaml" in str(exc_info.value)

    def test_read_dataset_via_pandas_api(self, project_path: Path):
        """Test reading dataset via pandas-like API."""
        from sunstone import pandas as pd

        df = pd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

        assert df is not None
        assert len(df.data) > 0
        assert isinstance(df, sunstone.DataFrame)

    def test_read_csv_with_slug_delegates_to_read_dataset(self, project_path: Path):
        """Test that read_csv with slug delegates to read_dataset."""
        df = sunstone.DataFrame.read_csv(
            "official-un-member-states",
            project_path=project_path,
            strict=False,
        )

        assert df is not None
        assert len(df.data) > 0
        # Should have the read_dataset operation in lineage
        assert any("read_dataset" in op for op in df.lineage.operations)
