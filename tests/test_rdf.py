"""
Tests for RDF triple support in datasets.yaml.
"""

import tempfile
from pathlib import Path

from sunstone.cli import collect_methodology_files, expand_custom_properties, expand_rdf_prefixes
from sunstone.datasets import DatasetsManager


class TestRDFPrefixExpansion:
    """Tests for RDF prefix expansion."""

    def test_expand_simple_prefix(self) -> None:
        """Test expanding a simple prefixed name."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        result = expand_rdf_prefixes("si:monitorsThreat", prefixes)
        assert result == "https://sunstone.institute/rdf/vocab#monitorsThreat"

    def test_expand_value_with_prefix(self) -> None:
        """Test expanding a value that uses a prefix."""
        prefixes = {"si30": "https://sunstone.institute/rdf/threat/"}
        result = expand_rdf_prefixes("si30:27", prefixes)
        assert result == "https://sunstone.institute/rdf/threat/27"

    def test_already_expanded_uri(self) -> None:
        """Test that already expanded URIs are not modified."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        uri = "https://sunstone.institute/rdf/vocab#monitorsThreat"
        result = expand_rdf_prefixes(uri, prefixes)
        assert result == uri

    def test_unknown_prefix(self) -> None:
        """Test that unknown prefixes are left as-is."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        result = expand_rdf_prefixes("unknown:value", prefixes)
        assert result == "unknown:value"

    def test_no_colon(self) -> None:
        """Test that values without colons are left as-is."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        result = expand_rdf_prefixes("plainvalue", prefixes)
        assert result == "plainvalue"


class TestCustomPropertiesExpansion:
    """Tests for custom properties expansion."""

    def test_expand_property_key(self) -> None:
        """Test expanding RDF property keys."""
        prefixes = {
            "si": "https://sunstone.institute/rdf/vocab#",
            "si30": "https://sunstone.institute/rdf/threat/",
        }
        custom_props = {"si:monitorsThreat": "si30:27"}
        result = expand_custom_properties(custom_props, prefixes)
        assert result == {
            "https://sunstone.institute/rdf/vocab#monitorsThreat": "https://sunstone.institute/rdf/threat/27"
        }

    def test_expand_multiple_properties(self) -> None:
        """Test expanding multiple RDF properties."""
        prefixes = {
            "si": "https://sunstone.institute/rdf/vocab#",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        custom_props = {
            "si:category": "environmental",
            "dc:creator": "Sunstone Institute",
        }
        result = expand_custom_properties(custom_props, prefixes)
        assert result == {
            "https://sunstone.institute/rdf/vocab#category": "environmental",
            "http://purl.org/dc/elements/1.1/creator": "Sunstone Institute",
        }

    def test_preserve_non_string_values(self) -> None:
        """Test that non-string values are preserved."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        custom_props = {
            "si:count": 42,
            "si:enabled": True,
            "si:tags": ["climate", "environment"],
        }
        result = expand_custom_properties(custom_props, prefixes)
        assert result["https://sunstone.institute/rdf/vocab#count"] == 42
        assert result["https://sunstone.institute/rdf/vocab#enabled"] is True
        assert result["https://sunstone.institute/rdf/vocab#tags"] == ["climate", "environment"]

    def test_methodology_path_without_base_url(self) -> None:
        """Test that methodology paths are kept as relative paths when no base_url is provided."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        custom_props = {
            "si:methodology": "docs/methodology.md",
        }
        # Without base_url, path is kept as-is (for local package_build)
        result = expand_custom_properties(custom_props, prefixes, "outputs/data.csv")
        # Key should be expanded
        assert "https://sunstone.institute/rdf/vocab#methodology" in result
        # Value should be kept as a relative path
        assert result["https://sunstone.institute/rdf/vocab#methodology"] == "docs/methodology.md"

    def test_methodology_path_with_base_url(self) -> None:
        """Test that methodology paths are resolved as relative URIs against base_url."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        custom_props = {
            "si:methodology": "docs/methodology.md",
        }
        result = expand_custom_properties(
            custom_props, prefixes, "outputs/data.csv", base_url="https://example.com/datasets/project"
        )
        assert "https://sunstone.institute/rdf/vocab#methodology" in result
        assert (
            result["https://sunstone.institute/rdf/vocab#methodology"]
            == "https://example.com/datasets/project/docs/methodology.md"
        )

    def test_methodology_nested_path_with_base_url(self) -> None:
        """Test that nested methodology paths are resolved correctly against base_url."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        custom_props = {
            "si:methodology": "docs/project/methodology.md",
        }
        result = expand_custom_properties(
            custom_props, prefixes, "outputs/data.csv", base_url="https://example.com/datasets/"
        )
        assert "https://sunstone.institute/rdf/vocab#methodology" in result
        assert (
            result["https://sunstone.institute/rdf/vocab#methodology"]
            == "https://example.com/datasets/docs/project/methodology.md"
        )

    def test_methodology_uri_preserved(self) -> None:
        """Test that methodology URIs are preserved as-is."""
        prefixes = {"si": "https://sunstone.institute/rdf/vocab#"}
        custom_props = {
            "si:methodology": "https://example.org/methodology/v1",
        }
        # URIs should be preserved regardless of base_url settings
        result = expand_custom_properties(
            custom_props, prefixes, "outputs/data.csv", base_url="https://other.com/datasets/"
        )
        assert "https://sunstone.institute/rdf/vocab#methodology" in result
        assert result["https://sunstone.institute/rdf/vocab#methodology"] == "https://example.org/methodology/v1"


class TestRDFInDatasets:
    """Tests for RDF support in datasets.yaml."""

    def test_parse_rdf_prefixes(self) -> None:
        """Test parsing RDF prefixes from datasets.yaml."""
        # Create a temporary datasets.yaml with RDF properties
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    rdfPrefixes:
      si: "https://sunstone.institute/rdf/vocab#"
      si30: "https://sunstone.institute/rdf/threat/"
    si:monitorsThreat: si30:27
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")

            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"
            assert dataset.rdf_prefixes["si30"] == "https://sunstone.institute/rdf/threat/"
            assert dataset.custom_properties is not None
            assert dataset.custom_properties["si:monitorsThreat"] == "si30:27"

    def test_defaults_rdf_prefixes(self) -> None:
        """Test that default RDF prefixes are applied to datasets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
    si30: "https://sunstone.institute/rdf/threat/"
  si:category: environmental

outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    si:monitorsThreat: si30:27
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")

            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"
            assert dataset.custom_properties is not None
            assert dataset.custom_properties["si:monitorsThreat"] == "si30:27"
            # Default property should be included
            assert dataset.custom_properties["si:category"] == "environmental"

    def test_top_level_rdf_prefixes(self) -> None:
        """Test that top-level rdfPrefixes are applied to datasets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
rdfPrefixes:
  si: "https://sunstone.institute/rdf/vocab#"
  si30: "https://sunstone.institute/rdf/threat/"

outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    si:monitorsThreat: si30:27
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")

            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"
            assert dataset.rdf_prefixes["si30"] == "https://sunstone.institute/rdf/threat/"
            assert dataset.custom_properties is not None
            assert dataset.custom_properties["si:monitorsThreat"] == "si30:27"

    def test_top_level_rdf_prefixes_via_get_default(self) -> None:
        """Test that get_default_rdf_prefixes returns top-level prefixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
rdfPrefixes:
  si: "https://sunstone.institute/rdf/vocab#"

outputs: []
"""
            )

            manager = DatasetsManager(tmpdir)
            prefixes = manager.get_default_rdf_prefixes()
            assert prefixes["si"] == "https://sunstone.institute/rdf/vocab#"

    def test_top_level_overrides_defaults_section(self) -> None:
        """Test that top-level rdfPrefixes takes precedence over defaults section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
rdfPrefixes:
  si: "https://sunstone.institute/rdf/vocab#"

defaults:
  rdfPrefixes:
    si: "https://old.example.com/vocab#"

outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")
            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"

            prefixes = manager.get_default_rdf_prefixes()
            assert prefixes["si"] == "https://sunstone.institute/rdf/vocab#"

    def test_dataset_level_overrides_top_level(self) -> None:
        """Test that dataset-level rdfPrefixes overrides top-level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
rdfPrefixes:
  si: "https://old.example.com/vocab#"

outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    rdfPrefixes:
      si: "https://sunstone.institute/rdf/vocab#"
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")
            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"

    def test_override_default_prefixes(self) -> None:
        """Test that dataset-level prefixes override defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://old.example.com/vocab#"

outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    rdfPrefixes:
      si: "https://sunstone.institute/rdf/vocab#"
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")

            assert dataset is not None
            assert dataset.rdf_prefixes is not None
            assert dataset.rdf_prefixes["si"] == "https://sunstone.institute/rdf/vocab#"

    def test_full_uri_properties(self) -> None:
        """Test using full URIs as property names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            datasets_file.write_text(
                """
outputs:
  - name: Test Dataset
    slug: test-dataset
    location: outputs/test.csv
    https://sunstone.institute/rdf/vocab#monitorsThreat: https://sunstone.institute/rdf/threat/27
    fields:
      - name: id
        type: integer
"""
            )

            manager = DatasetsManager(tmpdir)
            dataset = manager.find_dataset_by_slug("test-dataset")

            assert dataset is not None
            assert dataset.custom_properties is not None
            assert (
                dataset.custom_properties["https://sunstone.institute/rdf/vocab#monitorsThreat"]
                == "https://sunstone.institute/rdf/threat/27"
            )


class TestRDFInDatapackage:
    """Tests for RDF in datapackage.json generation."""

    def test_datapackage_with_rdf(self) -> None:
        """Test that datapackage.json includes expanded RDF properties."""
        # This would require creating actual CSV files and running the CLI
        # For now, we test the expansion logic directly
        prefixes = {
            "si": "https://sunstone.institute/rdf/vocab#",
            "si30": "https://sunstone.institute/rdf/threat/",
        }
        custom_props = {
            "si:monitorsThreat": "si30:27",
            "si:category": "environmental",
        }

        expanded = expand_custom_properties(custom_props, prefixes)

        # Verify full URIs in result
        assert "https://sunstone.institute/rdf/vocab#monitorsThreat" in expanded
        assert (
            expanded["https://sunstone.institute/rdf/vocab#monitorsThreat"]
            == "https://sunstone.institute/rdf/threat/27"
        )
        assert "https://sunstone.institute/rdf/vocab#category" in expanded
        assert expanded["https://sunstone.institute/rdf/vocab#category"] == "environmental"

        # Original prefixed names should not be in result
        assert "si:monitorsThreat" not in expanded
        assert "si:category" not in expanded

    def test_automatic_rdf_types(self) -> None:
        """Test that automatic RDF types are added to datapackage."""
        from sunstone.cli import STANDARD_RDF_PREFIXES

        # Verify standard prefixes are defined
        assert "rdf" in STANDARD_RDF_PREFIXES
        assert "dcat" in STANDARD_RDF_PREFIXES
        assert STANDARD_RDF_PREFIXES["rdf"] == "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        assert STANDARD_RDF_PREFIXES["dcat"] == "http://www.w3.org/ns/dcat#"

        # Verify the expected type URIs
        rdf_type_uri = f"{STANDARD_RDF_PREFIXES['rdf']}type"
        dcat_dataset_uri = f"{STANDARD_RDF_PREFIXES['dcat']}Dataset"
        dcat_distribution_uri = f"{STANDARD_RDF_PREFIXES['dcat']}Distribution"

        assert rdf_type_uri == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        assert dcat_dataset_uri == "http://www.w3.org/ns/dcat#Dataset"
        assert dcat_distribution_uri == "http://www.w3.org/ns/dcat#Distribution"


class TestCollectMethodologyFiles:
    """Tests for collecting methodology files across datasets and top-level properties."""

    def test_collects_top_level_methodology(self) -> None:
        """Test that top-level methodology files are collected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = str(Path(tmpdir).resolve())
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "docs").mkdir()
            (Path(tmpdir) / "docs" / "methodology.md").write_text("# Method")
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "data.csv").write_text("a,b\n1,2\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
  si:methodology: docs/methodology.md

outputs:
  - name: Data
    slug: data
    location: outputs/data.csv
    fields:
      - name: a
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()

            results = collect_methodology_files(datasets, top_props, prefixes, manager)
            assert len(results) == 1
            assert results[0][0] == Path(tmpdir) / "docs" / "methodology.md"
            assert results[0][1] == "docs/methodology.md"

    def test_collects_per_dataset_methodology(self) -> None:
        """Test that per-dataset methodology files are collected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "docs").mkdir()
            (Path(tmpdir) / "docs" / "method_a.md").write_text("# A")
            (Path(tmpdir) / "docs" / "method_b.md").write_text("# B")
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "a.csv").write_text("x\n1\n")
            (Path(tmpdir) / "outputs" / "b.csv").write_text("x\n2\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"

outputs:
  - name: Dataset A
    slug: dataset-a
    location: outputs/a.csv
    si:methodology: docs/method_a.md
    fields:
      - name: x
        type: integer
  - name: Dataset B
    slug: dataset-b
    location: outputs/b.csv
    si:methodology: docs/method_b.md
    fields:
      - name: x
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()

            results = collect_methodology_files(datasets, top_props, prefixes, manager)
            paths = {r[0].name for r in results}
            assert paths == {"method_a.md", "method_b.md"}

    def test_deduplicates_same_file(self) -> None:
        """Test that the same file referenced by multiple datasets is only collected once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "docs").mkdir()
            (Path(tmpdir) / "docs" / "methodology.md").write_text("# Method")
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "a.csv").write_text("x\n1\n")
            (Path(tmpdir) / "outputs" / "b.csv").write_text("x\n2\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"
  si:methodology: docs/methodology.md

outputs:
  - name: Dataset A
    slug: dataset-a
    location: outputs/a.csv
    fields:
      - name: x
        type: integer
  - name: Dataset B
    slug: dataset-b
    location: outputs/b.csv
    fields:
      - name: x
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()

            results = collect_methodology_files(datasets, top_props, prefixes, manager)
            assert len(results) == 1

    def test_skips_external_uris(self) -> None:
        """Test that external methodology URIs are not collected for upload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "data.csv").write_text("x\n1\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"

outputs:
  - name: Data
    slug: data
    location: outputs/data.csv
    si:methodology: https://external.example.com/method
    fields:
      - name: x
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()

            results = collect_methodology_files(datasets, top_props, prefixes, manager)
            assert len(results) == 0

    def test_collects_uri_matching_base_url(self) -> None:
        """Test that methodology URIs matching base_url are collected as local files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = str(Path(tmpdir).resolve())
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "docs").mkdir()
            (Path(tmpdir) / "docs" / "methodology.md").write_text("# Method")
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "data.csv").write_text("x\n1\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"

outputs:
  - name: Data
    slug: data
    location: outputs/data.csv
    si:methodology: https://cdn.example.com/datasets/project/docs/methodology.md
    fields:
      - name: x
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()
            base_url = "https://cdn.example.com/datasets/project/"

            results = collect_methodology_files(datasets, top_props, prefixes, manager, base_url)
            assert len(results) == 1
            assert results[0][0] == Path(tmpdir) / "docs" / "methodology.md"
            # The URI is kept as-is since it's already fully resolved
            assert results[0][1] == "https://cdn.example.com/datasets/project/docs/methodology.md"

    def test_resolves_relative_paths_with_base_url(self) -> None:
        """Test that relative methodology paths are resolved against base_url."""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasets_file = Path(tmpdir) / "datasets.yaml"
            (Path(tmpdir) / "docs").mkdir()
            (Path(tmpdir) / "docs" / "methodology.md").write_text("# Method")
            (Path(tmpdir) / "outputs").mkdir()
            (Path(tmpdir) / "outputs" / "data.csv").write_text("x\n1\n")
            datasets_file.write_text(
                """
defaults:
  rdfPrefixes:
    si: "https://sunstone.institute/rdf/vocab#"

outputs:
  - name: Data
    slug: data
    location: outputs/data.csv
    si:methodology: docs/methodology.md
    fields:
      - name: x
        type: integer
"""
            )
            manager = DatasetsManager(tmpdir)
            datasets = manager.get_all_outputs()
            top_props = manager.get_top_level_custom_properties()
            prefixes = manager.get_default_rdf_prefixes()
            base_url = "https://cdn.example.com/datasets/project/"

            results = collect_methodology_files(datasets, top_props, prefixes, manager, base_url)
            assert len(results) == 1
            assert results[0][1] == "https://cdn.example.com/datasets/project/docs/methodology.md"
