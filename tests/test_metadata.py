"""Tests for the Metadata container."""

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
