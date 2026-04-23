"""Tests for the Metadata container."""

import warnings
from datetime import datetime, timezone
from pathlib import Path

import sunstone
from sunstone.lineage import (
    DatasetMetadata,
    FieldDerivation,
    FieldSchema,
    LineageMetadata,
    Metadata,
)


class TestMetadataConstruction:
    """Tests for Metadata dataclass creation and field access."""

    def test_default_metadata(self):
        """Default Metadata has empty lineage and no other fields set."""
        m = Metadata()
        assert isinstance(m.lineage, LineageMetadata)
        assert m.description is None
        assert m.slug is None
        assert m.name is None
        assert m.rdf_prefixes is None
        assert m.custom_properties is None
        assert m.field_metadata == {}

    def test_metadata_with_all_fields(self):
        """Metadata accepts all fields at construction."""
        lineage = LineageMetadata()
        m = Metadata(
            lineage=lineage,
            description="Test dataset",
            slug="test-data",
            name="Test Data",
            rdf_prefixes={"schema": "https://schema.org/"},
            custom_properties={"schema:about": "Testing"},
            field_metadata={
                "col_a": FieldSchema(name="col_a", type="string", description="Column A"),
            },
        )
        assert m.description == "Test dataset"
        assert m.slug == "test-data"
        assert m.name == "Test Data"
        assert m.rdf_prefixes == {"schema": "https://schema.org/"}
        assert m.custom_properties == {"schema:about": "Testing"}
        assert "col_a" in m.field_metadata
        assert m.field_metadata["col_a"].description == "Column A"

    def test_metadata_field_metadata_independence(self):
        """Each Metadata instance has its own field_metadata dict."""
        m1 = Metadata()
        m2 = Metadata()
        m1.field_metadata["x"] = FieldSchema(name="x", type="string")
        assert "x" not in m2.field_metadata


class TestFieldSchemaOptionalType:
    """Tests for FieldSchema with optional type."""

    def test_field_schema_with_type(self):
        """FieldSchema works normally with an explicit type."""
        fs = FieldSchema(name="col", type="integer")
        assert fs.type == "integer"

    def test_field_schema_without_type(self):
        """FieldSchema accepts None type for deferred inference."""
        fs = FieldSchema(name="col", type=None, description="A column", unit="kg")
        assert fs.type is None
        assert fs.description == "A column"
        assert fs.unit == "kg"


class TestDataFrameMetadataIntegration:
    """Tests for DataFrame .metadata attribute and .lineage deprecation."""

    def test_default_metadata_on_new_dataframe(self):
        """New DataFrame gets an empty Metadata container."""
        df = sunstone.DataFrame({"a": [1, 2, 3]})
        assert isinstance(df.metadata, Metadata)
        assert isinstance(df.metadata.lineage, LineageMetadata)

    def test_metadata_parameter(self):
        """DataFrame accepts a metadata parameter."""
        meta = Metadata(description="test", slug="test-slug")
        df = sunstone.DataFrame({"a": [1]}, metadata=meta)
        assert df.metadata.description == "test"
        assert df.metadata.slug == "test-slug"

    def test_lineage_parameter_wraps_in_metadata(self):
        """Passing lineage= wraps it in a Metadata container (backwards compat)."""
        lineage = LineageMetadata()
        df = sunstone.DataFrame({"a": [1]}, lineage=lineage)
        assert isinstance(df.metadata, Metadata)
        assert df.metadata.lineage is lineage

    def test_lineage_property_deprecation_warning(self):
        """Accessing df.lineage emits DeprecationWarning."""
        df = sunstone.DataFrame({"a": [1]})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = df.lineage
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_lineage_setter_deprecation_warning(self):
        """Setting df.lineage emits DeprecationWarning."""
        df = sunstone.DataFrame({"a": [1]})
        new_lineage = LineageMetadata()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df.lineage = new_lineage
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
        assert df.metadata.lineage is new_lineage

    def test_lineage_property_delegates_to_metadata(self):
        """df.lineage returns the same object as df.metadata.lineage."""
        df = sunstone.DataFrame({"a": [1]})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert df.lineage is df.metadata.lineage


class TestConvenienceProperties:
    """Tests for df.description, df.rdf_prefixes, df.custom_properties."""

    def test_description_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.description is None
        df.description = "test description"
        assert df.description == "test description"
        assert df.metadata.description == "test description"

    def test_rdf_prefixes_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.rdf_prefixes is None
        df.rdf_prefixes = {"schema": "https://schema.org/"}
        assert df.rdf_prefixes == {"schema": "https://schema.org/"}
        assert df.metadata.rdf_prefixes == {"schema": "https://schema.org/"}

    def test_custom_properties_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.custom_properties is None
        df.custom_properties = {"schema:about": "Test"}
        assert df.custom_properties == {"schema:about": "Test"}
        assert df.metadata.custom_properties == {"schema:about": "Test"}


class TestSetFieldMetadata:
    """Tests for DataFrame.set_field_metadata()."""

    def test_set_field_metadata_creates_entry(self):
        """Setting metadata for a new column creates a FieldSchema."""
        df = sunstone.DataFrame({"enrollment": [100, 200]})
        df.set_field_metadata("enrollment", description="Total students", unit="count")
        fm = df.metadata.field_metadata["enrollment"]
        assert fm.name == "enrollment"
        assert fm.description == "Total students"
        assert fm.unit == "count"
        assert fm.type is None  # not set, will be inferred at write time

    def test_set_field_metadata_updates_existing(self):
        """Setting metadata again updates rather than replaces."""
        df = sunstone.DataFrame({"col": [1]})
        df.set_field_metadata("col", description="First")
        df.set_field_metadata("col", unit="kg")
        fm = df.metadata.field_metadata["col"]
        assert fm.description == "First"  # preserved
        assert fm.unit == "kg"  # added

    def test_set_field_metadata_chaining(self):
        """set_field_metadata returns self for chaining."""
        df = sunstone.DataFrame({"a": [1], "b": [2]})
        result = df.set_field_metadata("a", unit="m").set_field_metadata("b", unit="kg")
        assert result is df
        assert df.metadata.field_metadata["a"].unit == "m"
        assert df.metadata.field_metadata["b"].unit == "kg"

    def test_set_field_metadata_with_explicit_type(self):
        """Explicit type is stored and used instead of inference."""
        df = sunstone.DataFrame({"col": [1]})
        df.set_field_metadata("col", type="integer", description="Count")
        fm = df.metadata.field_metadata["col"]
        assert fm.type == "integer"

    def test_set_field_metadata_with_constraints(self):
        """Constraints can be set."""
        df = sunstone.DataFrame({"status": ["active"]})
        df.set_field_metadata("status", constraints={"enum": ["active", "inactive"]})
        fm = df.metadata.field_metadata["status"]
        assert fm.constraints == {"enum": ["active", "inactive"]}

    def test_set_field_metadata_with_source(self):
        """Source slug can be set."""
        df = sunstone.DataFrame({"val": [1]})
        df.set_field_metadata("val", source="input-data")
        assert df.metadata.field_metadata["val"].source == "input-data"


class TestMetadataPropagation:
    """Tests for metadata flowing through pandas operations."""

    def _make_df(self):
        """Create a DataFrame with metadata set."""
        df = sunstone.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        df.metadata.description = "test data"
        df.metadata.slug = "test-slug"
        df.metadata.name = "Test Data"
        df.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        df.metadata.custom_properties = {"schema:about": "Test"}
        df.set_field_metadata("a", description="Column A", unit="m")
        df.set_field_metadata("b", description="Column B", unit="kg")
        return df

    def test_filter_preserves_metadata(self):
        df = self._make_df()
        result = df[df["a"] > 1]
        assert result.metadata.description == "test data"
        assert result.metadata.slug == "test-slug"
        assert result.metadata.rdf_prefixes == {"schema": "https://schema.org/"}
        assert "a" in result.metadata.field_metadata
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_column_selection_drops_removed_field_metadata(self):
        df = self._make_df()
        result = df[["a"]]
        assert "a" in result.metadata.field_metadata
        assert "b" not in result.metadata.field_metadata
        assert result.metadata.description == "test data"

    def test_head_preserves_metadata(self):
        df = self._make_df()
        result = df.head(2)
        assert result.metadata.description == "test data"
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_merge_uses_left_metadata(self):
        left = sunstone.DataFrame({"key": [1], "val_l": [10]})
        left.metadata.description = "left data"
        left.set_field_metadata("val_l", unit="m")
        right = sunstone.DataFrame({"key": [1], "val_r": [20]})
        right.set_field_metadata("val_r", unit="kg")
        result = left.merge(right, on="key")
        assert result.metadata.description == "left data"
        assert result.metadata.field_metadata["val_l"].unit == "m"
        assert result.metadata.field_metadata["val_r"].unit == "kg"

    def test_concat_uses_first_metadata(self):
        df1 = sunstone.DataFrame({"a": [1]})
        df1.metadata.description = "first"
        df1.set_field_metadata("a", unit="m")
        df2 = sunstone.DataFrame({"a": [2]})
        df2.metadata.description = "second"
        result = df1.concat([df2])
        assert result.metadata.description == "first"
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_join_uses_left_metadata(self):
        left = sunstone.DataFrame({"val": [1]}, index=[0])
        left.metadata.description = "left"
        right = sunstone.DataFrame({"other": [2]}, index=[0])
        result = left.join(right)
        assert result.metadata.description == "left"

    def test_metadata_is_independent_after_operation(self):
        df = self._make_df()
        result = df.head(2)
        result.metadata.description = "modified"
        assert df.metadata.description == "test data"


class TestConflictingMetadata:
    """Tests for merge/join/concat when both DataFrames have conflicting metadata.

    The design rule: left/first DataFrame's metadata wins for all dataset-level
    fields (description, slug, name, rdf_prefixes, custom_properties, field_metadata).
    Lineage is merged from both sides.
    """

    def _make_left(self):
        left = sunstone.DataFrame({"key": [1, 2], "value": [10, 20]})
        left.metadata.slug = "left-dataset"
        left.metadata.name = "Left Dataset"
        left.metadata.description = "Left description"
        left.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        left.metadata.custom_properties = {"schema:about": "Left topic"}
        left.set_field_metadata("key", description="Join key", type="integer")
        left.set_field_metadata("value", description="Left value", unit="meters")
        left.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source A", slug="source-a", location="a.csv"))
        return left

    def _make_right(self):
        right = sunstone.DataFrame({"key": [1, 2], "score": [0.5, 0.9]})
        right.metadata.slug = "right-dataset"
        right.metadata.name = "Right Dataset"
        right.metadata.description = "Right description"
        right.metadata.rdf_prefixes = {"dc": "http://purl.org/dc/terms/"}
        right.metadata.custom_properties = {"dc:subject": "Right topic"}
        right.set_field_metadata("key", description="Right join key", type="string")
        right.set_field_metadata("score", description="Right score", unit="ratio")
        right.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source B", slug="source-b", location="b.csv"))
        return right

    def test_merge_conflicting_metadata(self):
        """Merge: left wins for dataset-level, lineage combined, right field_metadata lost."""
        left = self._make_left()
        right = self._make_right()
        result = left.merge(right, on="key")

        # Dataset-level: left wins
        assert result.metadata.slug == "left-dataset"
        assert result.metadata.name == "Left Dataset"
        assert result.metadata.description == "Left description"
        assert result.metadata.rdf_prefixes == {"schema": "https://schema.org/"}
        assert result.metadata.custom_properties == {"schema:about": "Left topic"}

        # Lineage: merged from both sides
        slugs = {s.slug for s in result.metadata.lineage.sources}
        assert slugs == {"source-a", "source-b"}

        # Field metadata: left's fields survive, right's brought in for new columns
        assert "key" in result.metadata.field_metadata
        assert result.metadata.field_metadata["key"].description == "Join key"
        assert result.metadata.field_metadata["key"].type == "integer"  # not "string" from right
        assert "value" in result.metadata.field_metadata
        assert result.metadata.field_metadata["value"].unit == "meters"
        assert result.metadata.field_metadata["score"].unit == "ratio"  # right's field metadata brought in

    def test_join_conflicting_metadata(self):
        """Join: left wins for dataset-level, lineage combined."""
        left = sunstone.DataFrame({"val_l": [10, 20]})
        left.metadata.description = "Left join"
        left.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        left.set_field_metadata("val_l", unit="kg")
        left.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source A", slug="source-a", location="a.csv"))

        right = sunstone.DataFrame({"val_r": [30, 40]})
        right.metadata.description = "Right join"
        right.metadata.rdf_prefixes = {"dc": "http://purl.org/dc/terms/"}
        right.set_field_metadata("val_r", unit="lbs")
        right.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source B", slug="source-b", location="b.csv"))

        result = left.join(right)

        # Dataset-level: left wins
        assert result.metadata.description == "Left join"
        assert result.metadata.rdf_prefixes == {"schema": "https://schema.org/"}

        # Lineage: combined
        slugs = {s.slug for s in result.metadata.lineage.sources}
        assert slugs == {"source-a", "source-b"}

        # Field metadata: left's survives, right's brought in
        assert result.metadata.field_metadata["val_l"].unit == "kg"
        assert result.metadata.field_metadata["val_r"].unit == "lbs"

    def test_concat_conflicting_metadata(self):
        """Concat: first DataFrame wins for dataset-level, lineage combined."""
        df1 = sunstone.DataFrame({"x": [1, 2]})
        df1.metadata.slug = "first-slug"
        df1.metadata.name = "First"
        df1.metadata.description = "First description"
        df1.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        df1.metadata.custom_properties = {"schema:about": "Topic A"}
        df1.set_field_metadata("x", description="First x", unit="m")
        df1.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source 1", slug="source-1", location="1.csv"))

        df2 = sunstone.DataFrame({"x": [3, 4]})
        df2.metadata.slug = "second-slug"
        df2.metadata.name = "Second"
        df2.metadata.description = "Second description"
        df2.metadata.rdf_prefixes = {"dc": "http://purl.org/dc/terms/"}
        df2.metadata.custom_properties = {"dc:subject": "Topic B"}
        df2.set_field_metadata("x", description="Second x", unit="ft")
        df2.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source 2", slug="source-2", location="2.csv"))

        df3 = sunstone.DataFrame({"x": [5]})
        df3.metadata.description = "Third description"
        df3.metadata.lineage.add_source(sunstone.DatasetMetadata(name="Source 3", slug="source-3", location="3.csv"))

        result = df1.concat([df2, df3], ignore_index=True)

        # Dataset-level: first wins
        assert result.metadata.slug == "first-slug"
        assert result.metadata.name == "First"
        assert result.metadata.description == "First description"
        assert result.metadata.rdf_prefixes == {"schema": "https://schema.org/"}
        assert result.metadata.custom_properties == {"schema:about": "Topic A"}

        # Field metadata: first wins
        assert result.metadata.field_metadata["x"].description == "First x"
        assert result.metadata.field_metadata["x"].unit == "m"  # not "ft" from df2

        # Lineage: merged from all three
        slugs = {s.slug for s in result.metadata.lineage.sources}
        assert slugs == {"source-1", "source-2", "source-3"}

        # Data: all rows present
        assert len(result) == 5


class TestFieldDerivationMergeConflicts:
    """Tests that field_derivations are properly combined during merge/join/concat."""

    def test_merge_combines_field_derivations(self):
        """Merge should union field_derivations from both sides."""
        left = sunstone.DataFrame({"key": [1], "val_l": [10]})
        left.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="val_l", source_entity="ds-left"),
        ]

        right = sunstone.DataFrame({"key": [1], "val_r": [20]})
        right.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="val_r", source_entity="ds-right"),
        ]

        result = left.merge(right, on="key")
        fds = result.metadata.lineage.field_derivations
        assert fds is not None
        assert len(fds) == 2
        assert {d.output_field for d in fds} == {"val_l", "val_r"}

    def test_join_combines_field_derivations(self):
        """Join should union field_derivations from both sides."""
        left = sunstone.DataFrame({"val_l": [10]})
        left.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="val_l", source_entity="ds-left"),
        ]

        right = sunstone.DataFrame({"val_r": [20]})
        right.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="val_r", source_entity="ds-right"),
        ]

        result = left.join(right)
        fds = result.metadata.lineage.field_derivations
        assert fds is not None
        assert len(fds) == 2

    def test_concat_combines_field_derivations(self):
        """Concat should union field_derivations from all DataFrames."""
        df1 = sunstone.DataFrame({"a": [1]})
        df1.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="a", source_entity="ds1"),
        ]

        df2 = sunstone.DataFrame({"a": [2]})
        df2.metadata.lineage.field_derivations = [
            FieldDerivation(output_field="a", source_entity="ds2"),
        ]

        result = df1.concat([df2])
        fds = result.metadata.lineage.field_derivations
        assert fds is not None
        # (a, ds1) and (a, ds2) are distinct derivations
        assert len(fds) == 2

    def test_merge_deduplicates_same_derivation(self):
        """If both sides have the same derivation, it should appear only once."""
        shared_fd = FieldDerivation(output_field="shared", source_entity="same-source")

        left = sunstone.DataFrame({"key": [1], "shared": [10]})
        left.metadata.lineage.field_derivations = [shared_fd]

        right = sunstone.DataFrame({"key": [1], "other": [20]})
        right.metadata.lineage.field_derivations = [shared_fd]

        result = left.merge(right, on="key")
        fds = result.metadata.lineage.field_derivations
        assert fds is not None
        shared_fds = [d for d in fds if d.output_field == "shared"]
        assert len(shared_fds) == 1


class TestBuildFieldSchema:
    """Tests for write-time field schema merge."""

    def test_inferred_only(self):
        """Without field metadata, all types are inferred from dtypes."""
        df = sunstone.DataFrame({"i": [1], "f": [1.5], "s": ["a"], "b": [True]})
        schema = df._build_field_schema()
        types = {f.name: f.type for f in schema}
        assert types["i"] == "integer"
        assert types["f"] == "number"
        assert types["s"] == "string"
        assert types["b"] == "boolean"

    def test_explicit_overrides_inferred(self):
        """Explicit field metadata takes precedence over inference."""
        df = sunstone.DataFrame({"val": [1]})
        df.set_field_metadata("val", type="number", description="A value", unit="kg")
        schema = df._build_field_schema()
        assert len(schema) == 1
        assert schema[0].type == "number"
        assert schema[0].description == "A value"
        assert schema[0].unit == "kg"

    def test_partial_annotation(self):
        """Annotated and unannotated columns both get schemas."""
        df = sunstone.DataFrame({"annotated": [1], "plain": ["x"]})
        df.set_field_metadata("annotated", description="Important", unit="m")
        schema = df._build_field_schema()
        by_name = {f.name: f for f in schema}
        assert by_name["annotated"].description == "Important"
        assert by_name["annotated"].type == "integer"
        assert by_name["plain"].type == "string"
        assert by_name["plain"].description is None

    def test_explicit_type_none_gets_inferred(self):
        """FieldSchema with type=None gets type inferred from dtype."""
        df = sunstone.DataFrame({"col": [42]})
        df.set_field_metadata("col", description="Count")
        assert df.metadata.field_metadata["col"].type is None
        schema = df._build_field_schema()
        assert schema[0].type == "integer"
        assert schema[0].description == "Count"


class TestMetadataIntegration:
    """End-to-end test: read -> annotate -> write -> verify datasets.yaml."""

    def test_full_metadata_flow(self, project_path: Path, tmp_path: Path):
        """Metadata set on DataFrame flows through to datasets.yaml on write."""
        import shutil

        from ruamel.yaml import YAML

        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )
        result = df[["Member State", "ISO Code"]].head(5)
        result.metadata.slug = "top-five-members"
        result.metadata.name = "Top Five Members"
        result.metadata.description = "First five UN member states"
        result.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        result.metadata.custom_properties = {"schema:about": "United Nations"}
        result.set_field_metadata("Member State", description="Country name")
        result.set_field_metadata("ISO Code", description="ISO 3166-1 alpha-3", source="official-un-member-states")
        output_path = test_project / "outputs" / "top_five.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), index=False)
        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)
        output = None
        for o in data["outputs"]:
            if o["slug"] == "top-five-members":
                output = o
                break
        assert output is not None, "Output dataset not found in datasets.yaml"
        assert output["name"] == "Top Five Members"
        assert output["description"] == "First five UN member states"
        assert output["rdfPrefixes"] == {"schema": "https://schema.org/"}
        assert output["schema:about"] == "United Nations"
        fields_by_name = {f["name"]: f for f in output["fields"]}
        assert fields_by_name["Member State"]["description"] == "Country name"
        assert fields_by_name["ISO Code"]["description"] == "ISO 3166-1 alpha-3"
        assert fields_by_name["ISO Code"]["source"] == "official-un-member-states"
        # Lineage is in the lock file, not in datasets.yaml
        with open(test_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)
        lock_output = next(o for o in lock_data["outputs"] if o["slug"] == "top-five-members")
        assert "sources" in lock_output

    def test_to_csv_slug_name_from_metadata(self, project_path: Path, tmp_path: Path):
        """to_csv uses metadata slug/name when not passed as parameters."""
        import shutil

        from ruamel.yaml import YAML

        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )
        result = df.head(3)
        result.metadata.slug = "meta-slug"
        result.metadata.name = "Meta Name"
        output_path = test_project / "outputs" / "meta_test.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), index=False)
        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)
        output = next(o for o in data["outputs"] if o["slug"] == "meta-slug")
        assert output["name"] == "Meta Name"

    def test_to_csv_params_override_metadata(self, project_path: Path, tmp_path: Path):
        """Explicit to_csv params override metadata values."""
        import shutil

        from ruamel.yaml import YAML

        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )
        result = df.head(3)
        result.metadata.slug = "meta-slug"
        result.metadata.name = "Meta Name"
        output_path = test_project / "outputs" / "override_test.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), slug="param-slug", name="Param Name", index=False)
        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)
        output = next(o for o in data["outputs"] if o["slug"] == "param-slug")
        assert output["name"] == "Param Name"


class TestMetadataJsonLd:
    """Tests for Metadata.to_jsonld() and Metadata.from_jsonld()."""

    def test_to_jsonld_minimal(self):
        """Metadata with just slug+name produces valid JSON-LD with @context, @type, identifiers."""
        m = Metadata(slug="test-slug", name="Test Dataset")
        doc = m.to_jsonld()
        assert "@context" in doc
        assert doc["@type"] == "dcat:Distribution"
        assert doc["si:version"] == "1.0"
        assert doc["dct:identifier"] == "test-slug"
        assert doc["dct:title"] == "Test Dataset"

    def test_to_jsonld_full(self):
        """Full metadata with sources, field metadata, field derivations, rdf_prefixes, custom_properties."""
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        lineage = LineageMetadata(
            created_at=ts,
            data_hash="abc123",
            project_path="/some/path",
            sources=[
                DatasetMetadata(name="Source A", slug="source-a", location="a.csv"),
            ],
            field_derivations=[
                FieldDerivation(output_field="col_a", source_entity="source-a", source_field="orig_a"),
            ],
        )
        m = Metadata(
            lineage=lineage,
            slug="full-dataset",
            name="Full Dataset",
            description="A full test dataset",
            rdf_prefixes={"ex": "http://example.org/"},
            custom_properties={"ex:category": "testing"},
            field_metadata={
                "col_a": FieldSchema(name="col_a", type="string", description="Column A", unit="kg"),
            },
        )
        doc = m.to_jsonld()

        # Context includes default + user prefixes
        assert doc["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
        assert doc["@context"]["ex"] == "http://example.org/"

        # Core fields
        assert doc["dct:identifier"] == "full-dataset"
        assert doc["dct:title"] == "Full Dataset"
        assert doc["dct:description"] == "A full test dataset"
        assert doc["dct:created"] == "2025-06-15T12:00:00+00:00"
        assert doc["si:dataHash"] == "abc123"

        # Sources
        sources = doc["prov:wasDerivedFrom"]
        assert len(sources) == 1
        assert sources[0]["dct:identifier"] == "source-a"
        assert sources[0]["dct:title"] == "Source A"
        assert sources[0]["dcat:downloadURL"] == "a.csv"

        # Field metadata
        fields = doc["si:fields"]
        assert "col_a" in fields
        assert fields["col_a"]["dct:description"] == "Column A"
        assert fields["col_a"]["si:unit"] == "kg"
        assert fields["col_a"]["si:type"] == "string"

        # Field derivations
        assert fields["col_a"]["prov:wasDerivedFrom"]["dct:identifier"] == "source-a"
        assert fields["col_a"]["prov:wasDerivedFrom"]["si:sourceField"] == "orig_a"

        # Custom properties
        assert doc["ex:category"] == "testing"

    def test_to_jsonld_excludes_project_path(self):
        """project_path never appears in serialized output."""
        m = Metadata(
            lineage=LineageMetadata(project_path="/secret/path"),
            slug="test",
            name="Test",
        )
        doc = m.to_jsonld()
        import json

        serialized = json.dumps(doc)
        assert "/secret/path" not in serialized
        assert "project_path" not in serialized

    def test_to_jsonld_with_data_hash(self):
        """data_hash serializes as si:dataHash."""
        m = Metadata(
            lineage=LineageMetadata(data_hash="sha256-deadbeef"),
            slug="hashed",
            name="Hashed",
        )
        doc = m.to_jsonld()
        assert doc["si:dataHash"] == "sha256-deadbeef"

    def test_to_jsonld_omits_none_fields(self):
        """None-valued fields are omitted from the output."""
        m = Metadata(slug="minimal", name="Minimal")
        doc = m.to_jsonld()
        assert "dct:description" not in doc
        assert "si:dataHash" not in doc
        assert "prov:wasDerivedFrom" not in doc
        assert "si:fields" not in doc
        assert "dct:created" not in doc

    def test_from_jsonld_minimal(self):
        """Reconstruct from minimal doc."""
        doc = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "prov": "http://www.w3.org/ns/prov#",
                "si": "https://sunstone.institute/ns/",
                "schema": "http://schema.org/",
            },
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:identifier": "my-slug",
            "dct:title": "My Title",
        }
        m = Metadata.from_jsonld(doc)
        assert m.slug == "my-slug"
        assert m.name == "My Title"
        assert m.description is None
        assert m.lineage.data_hash is None

    def test_from_jsonld_full_round_trip(self):
        """to_jsonld -> from_jsonld preserves all fields."""
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        lineage = LineageMetadata(
            created_at=ts,
            data_hash="abc123",
            sources=[
                DatasetMetadata(name="Source A", slug="source-a", location="a.csv"),
            ],
            field_derivations=[
                FieldDerivation(output_field="col_a", source_entity="source-a", source_field="orig_a"),
            ],
        )
        original = Metadata(
            lineage=lineage,
            slug="round-trip",
            name="Round Trip",
            description="A round trip test",
            rdf_prefixes={"ex": "http://example.org/"},
            custom_properties={"ex:category": "testing"},
            field_metadata={
                "col_a": FieldSchema(name="col_a", type="string", description="Column A", unit="kg"),
            },
        )
        doc = original.to_jsonld()
        restored = Metadata.from_jsonld(doc)

        assert restored.slug == "round-trip"
        assert restored.name == "Round Trip"
        assert restored.description == "A round trip test"
        assert restored.rdf_prefixes == {"ex": "http://example.org/"}
        assert restored.custom_properties == {"ex:category": "testing"}
        assert restored.lineage.data_hash == "abc123"
        assert restored.lineage.created_at == ts

        # Sources
        assert len(restored.lineage.sources) == 1
        assert restored.lineage.sources[0].slug == "source-a"
        assert restored.lineage.sources[0].name == "Source A"
        assert restored.lineage.sources[0].location == "a.csv"

        # Field metadata
        assert "col_a" in restored.field_metadata
        assert restored.field_metadata["col_a"].description == "Column A"
        assert restored.field_metadata["col_a"].unit == "kg"
        assert restored.field_metadata["col_a"].type == "string"

        # Field derivations
        assert restored.lineage.field_derivations is not None
        assert len(restored.lineage.field_derivations) == 1
        fd = restored.lineage.field_derivations[0]
        assert fd.output_field == "col_a"
        assert fd.source_entity == "source-a"
        assert fd.source_field == "orig_a"

    def test_from_jsonld_unknown_keys_preserved(self):
        """Unknown top-level keys go to custom_properties."""
        doc = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "prov": "http://www.w3.org/ns/prov#",
                "si": "https://sunstone.institute/ns/",
                "schema": "http://schema.org/",
                "ex": "http://example.org/",
            },
            "@type": "dcat:Distribution",
            "si:version": "1.0",
            "dct:identifier": "test",
            "dct:title": "Test",
            "ex:customField": "custom-value",
            "ex:anotherField": 42,
        }
        m = Metadata.from_jsonld(doc)
        assert m.custom_properties is not None
        assert m.custom_properties["ex:customField"] == "custom-value"
        assert m.custom_properties["ex:anotherField"] == 42
        # User prefix extracted
        assert m.rdf_prefixes is not None
        assert m.rdf_prefixes["ex"] == "http://example.org/"

    def test_from_jsonld_missing_optional_fields(self):
        """Missing optional fields produce None/empty, not errors."""
        doc = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "prov": "http://www.w3.org/ns/prov#",
                "si": "https://sunstone.institute/ns/",
                "schema": "http://schema.org/",
            },
            "@type": "dcat:Distribution",
            "si:version": "1.0",
        }
        m = Metadata.from_jsonld(doc)
        assert m.slug is None
        assert m.name is None
        assert m.description is None
        assert m.lineage.data_hash is None
        assert m.lineage.created_at is None
        assert m.lineage.sources == []
        assert m.field_metadata == {}
        assert m.custom_properties is None
        assert m.rdf_prefixes is None
