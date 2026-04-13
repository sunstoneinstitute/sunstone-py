from pathlib import Path

import sunstone
from sunstone.lineage import FieldDerivation, LineageMetadata, Metadata


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
        assert hasattr(result, "metadata")
        assert len(result.metadata.lineage.sources) == len(df.metadata.lineage.sources)

    def test_getitem_preserves_lineage(self, project_path: Path) -> None:
        """Test that boolean indexing/getitem returns sunstone DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        # Let's just slice columns, which returns a DataFrame
        result = df[["Member State", "ISO Code"]]

        assert isinstance(result, sunstone.DataFrame)
        assert len(result.metadata.lineage.sources) == len(df.metadata.lineage.sources)

    def test_sort_values_preserves_lineage(self, project_path: Path) -> None:
        """Test that sort_values returns sunstone DataFrame."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        result = df.sort_values("Member State")

        assert isinstance(result, sunstone.DataFrame)
        assert len(result.metadata.lineage.sources) == len(df.metadata.lineage.sources)

    def test_setitem_preserves_lineage(self, project_path: Path) -> None:
        """Test that in-place modification preserves lineage."""
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False
        )

        initial_sources = len(df.metadata.lineage.sources)
        df["NewCol"] = 1

        assert "NewCol" in df.data.columns
        # Lineage sources should be preserved after setitem
        assert len(df.metadata.lineage.sources) == initial_sources


class TestFieldDerivationPersistence:
    """Tests to ensure field_derivations are preserved through pandas operations."""

    def _make_df_with_derivations(self) -> sunstone.DataFrame:
        """Create a DataFrame with field_derivations set."""
        meta = Metadata(
            lineage=LineageMetadata(
                field_derivations=[
                    FieldDerivation(output_field="Member State", source_entity="raw-data"),
                    FieldDerivation(output_field="ISO Code", source_entity="raw-data", source_field="code"),
                    FieldDerivation(output_field="Year", source_entity="dates-data"),
                ]
            )
        )
        import pandas as pd

        df = sunstone.DataFrame(
            data=pd.DataFrame(
                {
                    "Member State": ["A", "B"],
                    "ISO Code": ["AA", "BB"],
                    "Year": [2020, 2021],
                }
            ),
            metadata=meta,
        )
        return df

    def test_head_preserves_field_derivations(self) -> None:
        df = self._make_df_with_derivations()
        result = df.head(1)
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 3

    def test_sort_values_preserves_field_derivations(self) -> None:
        df = self._make_df_with_derivations()
        result = df.sort_values("Year")
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 3

    def test_getitem_drops_removed_field_derivations(self) -> None:
        """Column selection should drop derivations for removed columns."""
        df = self._make_df_with_derivations()
        result = df[["Member State", "Year"]]
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 2
        fields = {d.output_field for d in result.metadata.lineage.field_derivations}
        assert fields == {"Member State", "Year"}

    def test_merge_combines_field_derivations(self) -> None:
        """Merge should union field_derivations from both sides."""
        import pandas as pd

        left = sunstone.DataFrame(
            data=pd.DataFrame({"key": [1], "val_l": [10]}),
            metadata=Metadata(
                lineage=LineageMetadata(
                    field_derivations=[FieldDerivation(output_field="val_l", source_entity="ds-left")]
                )
            ),
        )
        right = sunstone.DataFrame(
            data=pd.DataFrame({"key": [1], "val_r": [20]}),
            metadata=Metadata(
                lineage=LineageMetadata(
                    field_derivations=[FieldDerivation(output_field="val_r", source_entity="ds-right")]
                )
            ),
        )
        result = left.merge(right, on="key")
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 2
        fields = {d.output_field for d in result.metadata.lineage.field_derivations}
        assert fields == {"val_l", "val_r"}

    def test_join_combines_field_derivations(self) -> None:
        """Join should union field_derivations from both sides."""
        import pandas as pd

        left = sunstone.DataFrame(
            data=pd.DataFrame({"val_l": [10]}, index=[0]),
            metadata=Metadata(
                lineage=LineageMetadata(
                    field_derivations=[FieldDerivation(output_field="val_l", source_entity="ds-left")]
                )
            ),
        )
        right = sunstone.DataFrame(
            data=pd.DataFrame({"val_r": [20]}, index=[0]),
            metadata=Metadata(
                lineage=LineageMetadata(
                    field_derivations=[FieldDerivation(output_field="val_r", source_entity="ds-right")]
                )
            ),
        )
        result = left.join(right)
        assert result.metadata.lineage.field_derivations is not None
        assert len(result.metadata.lineage.field_derivations) == 2

    def test_concat_combines_field_derivations(self) -> None:
        """Concat should union field_derivations from all DataFrames."""
        import pandas as pd

        df1 = sunstone.DataFrame(
            data=pd.DataFrame({"a": [1]}),
            metadata=Metadata(
                lineage=LineageMetadata(field_derivations=[FieldDerivation(output_field="a", source_entity="ds1")])
            ),
        )
        df2 = sunstone.DataFrame(
            data=pd.DataFrame({"a": [2]}),
            metadata=Metadata(
                lineage=LineageMetadata(field_derivations=[FieldDerivation(output_field="a", source_entity="ds2")])
            ),
        )
        result = df1.concat([df2])
        assert result.metadata.lineage.field_derivations is not None
        # Both derivations: (a, ds1) and (a, ds2) are distinct because source_entity differs
        assert len(result.metadata.lineage.field_derivations) == 2
