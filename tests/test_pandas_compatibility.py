"""
Tests for pandas compatibility of Sunstone DataFrames.

These tests are inspired by and adapted from pandas test suite to ensure
that Sunstone DataFrames behave like pandas DataFrames for common operations.
"""

from pathlib import Path
from typing import Any

import pytest

import sunstone
from sunstone import pandas as spd


class TestBasicOperations:
    """Tests for basic DataFrame operations that should match pandas behavior."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

    def test_shape(self, sample_df: sunstone.DataFrame) -> None:
        """Test that shape attribute works like pandas."""
        assert hasattr(sample_df, "shape")
        assert isinstance(sample_df.shape, tuple)
        assert len(sample_df.shape) == 2
        assert sample_df.shape[0] > 0
        assert sample_df.shape[1] > 0

    def test_columns(self, sample_df: sunstone.DataFrame) -> None:
        """Test that columns attribute works like pandas."""
        assert hasattr(sample_df, "columns")
        assert "Member State" in sample_df.columns
        assert "ISO Code" in sample_df.columns

    def test_head(self, sample_df: sunstone.DataFrame) -> None:
        """Test head() method like pandas."""
        result = sample_df.head()
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == min(5, len(sample_df))

        # Test with custom n
        result = sample_df.head(10)
        assert len(result) == min(10, len(sample_df))

    def test_tail(self, sample_df: sunstone.DataFrame) -> None:
        """Test tail() method like pandas."""
        result = sample_df.tail()
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == min(5, len(sample_df))

        # Test with custom n
        result = sample_df.tail(3)
        assert len(result) == min(3, len(sample_df))

    def test_len(self, sample_df: sunstone.DataFrame) -> None:
        """Test len() works like pandas."""
        assert len(sample_df) > 0
        assert len(sample_df) == len(sample_df.data)

    def test_iter(self, sample_df: sunstone.DataFrame) -> None:
        """Test iteration over column names like pandas."""
        columns = list(sample_df)
        assert "Member State" in columns
        assert len(columns) == len(sample_df.columns)

    def test_dtypes(self, sample_df: sunstone.DataFrame) -> None:
        """Test dtypes attribute like pandas."""
        assert hasattr(sample_df, "dtypes")
        dtypes = sample_df.dtypes
        assert len(dtypes) == len(sample_df.columns)


class TestSelectionAndIndexing:
    """Tests for selection and indexing operations."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

    def test_getitem_single_column(self, sample_df: sunstone.DataFrame) -> None:
        """Test selecting a single column like pandas."""
        result = sample_df["Member State"]
        # Result should be a Series (from underlying pandas)
        assert result is not None
        assert len(result) == len(sample_df)

    def test_getitem_multiple_columns(self, sample_df: sunstone.DataFrame) -> None:
        """Test selecting multiple columns like pandas."""
        result = sample_df[["Member State", "ISO Code"]]
        assert isinstance(result, sunstone.DataFrame)
        assert len(result.columns) == 2
        assert "Member State" in result.columns
        assert "ISO Code" in result.columns

    def test_boolean_indexing(self, sample_df: sunstone.DataFrame) -> None:
        """Test boolean indexing like pandas."""
        # Filter for rows where ISO Code is not null
        result = sample_df[sample_df["ISO Code"].notna()]
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) <= len(sample_df)
        # Verify lineage is preserved
        assert len(result.lineage.sources) > 0

    def test_loc(self, sample_df: sunstone.DataFrame) -> None:
        """Test .loc accessor like pandas."""
        # Just test that it exists and is accessible
        assert hasattr(sample_df, "loc")
        # Access a row
        result = sample_df.loc[0]
        assert result is not None

    def test_iloc(self, sample_df: sunstone.DataFrame) -> None:
        """Test .iloc accessor like pandas."""
        assert hasattr(sample_df, "iloc")
        # Access first row
        result = sample_df.iloc[0]
        assert result is not None

    def test_setitem(self, sample_df: sunstone.DataFrame) -> None:
        """Test setting column values like pandas."""
        # Create a copy to avoid modifying fixture
        df = sample_df.head()
        df["test_column"] = "test_value"
        assert "test_column" in df.columns
        # Lineage should track this operation
        assert any("setitem" in op.lower() for op in df.lineage.operations)


class TestDataManipulation:
    """Tests for data manipulation operations."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

    def test_sort_values(self, sample_df: sunstone.DataFrame) -> None:
        """Test sort_values() like pandas."""
        result = sample_df.sort_values("Member State")
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == len(sample_df)
        # Check lineage is preserved
        assert len(result.lineage.sources) > 0

    def test_drop(self, sample_df: sunstone.DataFrame) -> None:
        """Test drop() method like pandas."""
        columns_before = len(sample_df.columns)
        result = sample_df.drop(columns=["M49 Code"])
        assert isinstance(result, sunstone.DataFrame)
        assert len(result.columns) == columns_before - 1
        assert "M49 Code" not in result.columns

    def test_rename(self, sample_df: sunstone.DataFrame) -> None:
        """Test rename() method like pandas."""
        result = sample_df.rename(columns={"Member State": "Country"})
        assert isinstance(result, sunstone.DataFrame)
        assert "Country" in result.columns
        assert "Member State" not in result.columns

    def test_fillna(self, sample_df: sunstone.DataFrame) -> None:
        """Test fillna() method like pandas."""
        result = sample_df.fillna("N/A")
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == len(sample_df)

    def test_dropna(self, sample_df: sunstone.DataFrame) -> None:
        """Test dropna() method like pandas."""
        result = sample_df.dropna(subset=["ISO Code"])
        assert isinstance(result, sunstone.DataFrame)
        # Should have removed rows with null ISO Code
        assert len(result) <= len(sample_df)


class TestGroupByAndAggregation:
    """Tests for groupby and aggregation operations."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame with data suitable for grouping."""
        df = spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )
        # Add a test column for grouping
        df["has_iso"] = df["ISO Code"].notna()
        return df

    def test_groupby_simple(self, sample_df: sunstone.DataFrame) -> None:
        """Test basic groupby operation."""
        result = sample_df.groupby("has_iso").size()
        assert result is not None
        assert len(result) > 0

    def test_groupby_count(self, sample_df: sunstone.DataFrame) -> None:
        """Test groupby with count."""
        result = sample_df.groupby("has_iso").count()
        assert result is not None

    def test_groupby_first(self, sample_df: sunstone.DataFrame) -> None:
        """Test groupby with first."""
        result = sample_df.groupby("has_iso").first()
        assert result is not None


class TestMergeAndJoin:
    """Tests for merge and join operations."""

    @pytest.fixture
    def df1(self, project_path: Path) -> Any:
        """First DataFrame for merge/join tests."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        ).head(50)

    @pytest.fixture
    def df2(self, project_path: Path) -> Any:
        """Second DataFrame for merge/join tests."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        ).tail(50)

    def test_merge_basic(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test basic merge operation like pandas."""
        result = spd.merge(df1, df2, on="ISO Code", how="inner")
        assert isinstance(result, sunstone.DataFrame)
        # Check that lineage includes both sources
        assert len(result.lineage.sources) > 0

    def test_merge_left(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test left merge like pandas."""
        result = spd.merge(df1, df2, on="ISO Code", how="left")
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) >= len(df1[df1["ISO Code"].notna()])

    def test_merge_method(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test DataFrame.merge() method like pandas."""
        result = df1.merge(df2, on="ISO Code", how="inner")
        assert isinstance(result, sunstone.DataFrame)

    def test_join(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test join operation like pandas."""
        # Set index for join
        df1_indexed = df1.set_index("ISO Code")
        df2_indexed = df2.set_index("ISO Code")
        result = df1_indexed.join(df2_indexed, lsuffix="_left", rsuffix="_right")
        assert isinstance(result, sunstone.DataFrame)


class TestConcat:
    """Tests for concatenation operations."""

    @pytest.fixture
    def df1(self, project_path: Path) -> Any:
        """First DataFrame for concat tests."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        ).head(10)

    @pytest.fixture
    def df2(self, project_path: Path) -> Any:
        """Second DataFrame for concat tests."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        ).tail(10)

    def test_concat_basic(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test basic concatenation like pandas."""
        result = spd.concat([df1, df2])
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == len(df1) + len(df2)
        # Check lineage combines both sources
        assert len(result.lineage.sources) > 0

    def test_concat_ignore_index(self, df1: sunstone.DataFrame, df2: sunstone.DataFrame) -> None:
        """Test concat with ignore_index like pandas."""
        result = spd.concat([df1, df2], ignore_index=True)
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) == len(df1) + len(df2)


class TestStringMethods:
    """Tests for string methods on DataFrame columns."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

    def test_str_contains(self, sample_df: sunstone.DataFrame) -> None:
        """Test .str.contains() like pandas."""
        result = sample_df[sample_df["Member State"].str.contains("United", na=False)]
        assert isinstance(result, sunstone.DataFrame)
        assert len(result) >= 0

    def test_str_lower(self, sample_df: sunstone.DataFrame) -> None:
        """Test .str.lower() like pandas."""
        result = sample_df["Member State"].str.lower()
        assert result is not None
        assert len(result) == len(sample_df)

    def test_str_upper(self, sample_df: sunstone.DataFrame) -> None:
        """Test .str.upper() like pandas."""
        result = sample_df["Member State"].str.upper()
        assert result is not None


class TestNullHandling:
    """Tests for null handling like pandas."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> sunstone.DataFrame:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        )

    def test_isna(self, sample_df: sunstone.DataFrame) -> None:
        """Test isna() method like pandas."""
        result = sample_df["ISO Code"].isna()
        assert result is not None
        assert len(result) == len(sample_df)

    def test_notna(self, sample_df: sunstone.DataFrame) -> None:
        """Test notna() method like pandas."""
        result = sample_df["ISO Code"].notna()
        assert result is not None
        assert len(result) == len(sample_df)

    def test_isnull(self, sample_df: sunstone.DataFrame) -> None:
        """Test isnull() method (alias for isna)."""
        result = sample_df["ISO Code"].isnull()
        assert result is not None

    def test_notnull(self, sample_df: sunstone.DataFrame) -> None:
        """Test notnull() method (alias for notna)."""
        result = sample_df["ISO Code"].notnull()
        assert result is not None


class TestUtilities:
    """Tests for utility functions like pandas."""

    def test_pandas_timestamp_available(self) -> None:
        """Test that pandas Timestamp is available."""
        assert hasattr(spd, "Timestamp")
        ts = spd.Timestamp("2025-01-01")
        assert ts is not None

    def test_pandas_nat_available(self) -> None:
        """Test that pandas NaT is available."""
        assert hasattr(spd, "NaT")

    def test_isna_function(self) -> None:
        """Test that isna() function is available."""
        assert hasattr(spd, "isna")
        result = spd.isna(None)
        assert result is True

    def test_to_datetime(self) -> None:
        """Test to_datetime() function like pandas."""
        assert hasattr(spd, "to_datetime")
        result = spd.to_datetime("2025-01-01")
        assert result is not None


class TestDataFrameCreation:
    """Tests for creating DataFrames like pandas."""

    def test_create_from_dict(self) -> None:
        """Test creating DataFrame from dict like pandas."""
        data = {"A": [1, 2, 3], "B": ["a", "b", "c"]}
        df = sunstone.DataFrame(data)
        assert isinstance(df, sunstone.DataFrame)
        assert len(df) == 3
        assert "A" in df.columns
        assert "B" in df.columns

    def test_create_from_list_of_dicts(self) -> None:
        """Test creating DataFrame from list of dicts like pandas."""
        data = [{"A": 1, "B": "a"}, {"A": 2, "B": "b"}, {"A": 3, "B": "c"}]
        df = sunstone.DataFrame(data)
        assert isinstance(df, sunstone.DataFrame)
        assert len(df) == 3

    def test_create_empty(self) -> None:
        """Test creating empty DataFrame like pandas."""
        df = sunstone.DataFrame()
        assert isinstance(df, sunstone.DataFrame)
        assert len(df) == 0


class TestRepr:
    """Tests for string representation."""

    @pytest.fixture
    def sample_df(self, project_path: Path) -> Any:
        """Create a sample DataFrame for testing."""
        return spd.read_dataset(
            "official-un-member-states",
            project_path=project_path,
        ).head(5)

    def test_repr(self, sample_df: sunstone.DataFrame) -> None:
        """Test __repr__() includes DataFrame content and lineage."""
        repr_str = repr(sample_df)
        assert repr_str is not None
        # Should include lineage info
        assert "Lineage" in repr_str
        assert "source" in repr_str.lower()

    def test_str(self, sample_df: sunstone.DataFrame) -> None:
        """Test __str__() returns string representation."""
        str_rep = str(sample_df)
        assert str_rep is not None
        assert len(str_rep) > 0
