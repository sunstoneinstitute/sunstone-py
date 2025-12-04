from pathlib import Path

import sunstone


class TestLineagePersistence:
    """Tests to ensure lineage is preserved through standard pandas operations."""

    def test_head_preserves_lineage(self, project_path: Path) -> None:
        """Test that head() returns a sunstone DataFrame with lineage."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        # operation
        result = df.head(5)

        # Check type
        assert isinstance(result, sunstone.DataFrame), f"Expected sunstone.DataFrame, got {type(result)}"

        # Check lineage presence
        assert hasattr(result, "lineage")
        assert len(result.lineage.sources) == len(df.lineage.sources)

    def test_getitem_preserves_lineage(self, project_path: Path) -> None:
        """Test that boolean indexing/getitem returns sunstone DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        # Let's just slice columns, which returns a DataFrame
        result = df[["Member State", "ISO Code"]]

        assert isinstance(result, sunstone.DataFrame)
        assert len(result.lineage.sources) == len(df.lineage.sources)

    def test_sort_values_preserves_lineage(self, project_path: Path) -> None:
        """Test that sort_values returns sunstone DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        result = df.sort_values("Member State")

        assert isinstance(result, sunstone.DataFrame)
        assert len(result.lineage.sources) == len(df.lineage.sources)

    def test_setitem_preserves_lineage(self, project_path: Path) -> None:
        """Test that in-place modification preserves lineage."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        initial_sources = len(df.lineage.sources)
        df["NewCol"] = 1

        assert "NewCol" in df.data.columns
        # Lineage sources should be preserved after setitem
        assert len(df.lineage.sources) == initial_sources
