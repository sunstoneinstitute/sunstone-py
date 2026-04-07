"""Tests for the Metadata container."""

import warnings

import sunstone
from sunstone.lineage import FieldSchema, LineageMetadata, Metadata


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
