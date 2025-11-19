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

        filtered = df.apply_operation(
            lambda d: d.head(10), description="Select first 10 rows"
        )

        assert len(filtered.data) == 10
        assert len(filtered.lineage.operations) > len(df.lineage.operations)

    def test_read_second_dataset(self, project_path: Path):
        """Test reading a second dataset."""
        schools = sunstone.DataFrame.read_csv(
            "inputs/amount_school_data.csv", project_path=project_path, strict=False
        )

        assert schools is not None
        assert len(schools.data) > 0
        assert len(schools.lineage.sources) > 0


class TestDataFrameMerge:
    """Tests for DataFrame merge operations."""

    @pytest.fixture
    def un_members_df(self, project_path: Path):
        """Load UN members DataFrame."""
        return sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )

    @pytest.fixture
    def schools_df(self, project_path: Path):
        """Load schools DataFrame."""
        return sunstone.DataFrame.read_csv(
            "inputs/amount_school_data.csv", project_path=project_path, strict=False
        )

    def test_merge_dataframes(self, schools_df, un_members_df):
        """Test merging two DataFrames."""
        merged = schools_df.merge(
            un_members_df, left_on="Country Code", right_on="ISO Code", how="left"
        )

        assert merged is not None
        assert len(merged.data) > 0
        assert len(merged.lineage.sources) == 2
        assert len(merged.lineage.operations) > 0

    def test_merge_lineage_tracking(self, schools_df, un_members_df):
        """Test that merge properly tracks lineage."""
        merged = schools_df.merge(
            un_members_df, left_on="Country Code", right_on="ISO Code", how="left"
        )

        licenses = merged.lineage.get_licenses()
        assert licenses is not None
        assert len(licenses) > 0


class TestLineageMetadata:
    """Tests for lineage metadata functionality."""

    @pytest.fixture
    def merged_df(self, project_path: Path):
        """Create a merged DataFrame for testing."""
        schools = sunstone.DataFrame.read_csv(
            "inputs/amount_school_data.csv", project_path=project_path, strict=False
        )
        un_members = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        return schools.merge(
            un_members, left_on="Country Code", right_on="ISO Code", how="left"
        )

    def test_lineage_to_dict(self, merged_df):
        """Test converting lineage to dictionary."""
        lineage_dict = merged_df.lineage.to_dict()

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

        strict_df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path
        )

        assert strict_df.strict_mode is True

    def test_strict_mode_prevents_unregistered_write(
        self, project_path: Path, monkeypatch
    ):
        """Test that strict mode prevents writing to unregistered locations."""
        monkeypatch.setenv("SUNSTONE_DATAFRAME_STRICT", "1")

        strict_df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path
        )

        with pytest.raises(sunstone.StrictModeError):
            strict_df.to_csv("/tmp/test_output.csv", index=False)
