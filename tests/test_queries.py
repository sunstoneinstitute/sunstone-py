"""
Unit tests for lineage query API (queries.py).
"""

import textwrap
from pathlib import Path

import pytest

from sunstone.queries import LineageNode, display_lineage, get_upstream, lineage_to_dict

# These tests use the legacy inline-lineage format in datasets.yaml fixtures
# because the queries API supports both formats; the lock-file format is
# exercised in test_lock_file.py.
pytestmark = pytest.mark.filterwarnings("ignore:Inline lineage:DeprecationWarning")


def _write_datasets_yaml(tmp_path: Path, content: str) -> Path:
    """Helper to write a datasets.yaml file in a temp directory."""
    yaml_path = tmp_path / "datasets.yaml"
    yaml_path.write_text(textwrap.dedent(content))
    return tmp_path


class TestGetUpstreamSimple:
    """Tests for get_upstream with simple lineage."""

    def test_output_with_one_input_source(self, tmp_path):
        """Output with one input source should produce a two-node tree."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs:
              - name: Raw Data
                slug: raw-data
                location: inputs/raw.csv
            outputs:
              - name: Processed Data
                slug: processed-data
                location: outputs/processed.csv
                lineage:
                  sources:
                    - slug: raw-data
            """,
        )
        node = get_upstream("processed-data", project_path=tmp_path)
        assert node.slug == "processed-data"
        assert len(node.sources) == 1
        assert node.sources[0].slug == "raw-data"
        assert node.sources[0].sources == []  # input is a leaf

    def test_output_with_no_lineage(self, tmp_path):
        """Output with no lineage should be a leaf node."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs: []
            outputs:
              - name: Standalone
                slug: standalone
                location: outputs/standalone.csv
            """,
        )
        node = get_upstream("standalone", project_path=tmp_path)
        assert node.slug == "standalone"
        assert node.sources == []


class TestGetUpstreamMultiLevel:
    """Tests for multi-level lineage traversal."""

    def test_output_to_intermediate_to_input(self, tmp_path):
        """Should traverse: final -> intermediate -> raw."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs:
              - name: Raw
                slug: raw
                location: inputs/raw.csv
            outputs:
              - name: Intermediate
                slug: intermediate
                location: outputs/intermediate.csv
                lineage:
                  sources:
                    - slug: raw
              - name: Final
                slug: final
                location: outputs/final.csv
                lineage:
                  sources:
                    - slug: intermediate
            """,
        )
        node = get_upstream("final", project_path=tmp_path)
        assert node.slug == "final"
        assert len(node.sources) == 1
        assert node.sources[0].slug == "intermediate"
        assert len(node.sources[0].sources) == 1
        assert node.sources[0].sources[0].slug == "raw"


class TestGetUpstreamCircular:
    """Tests for circular reference detection."""

    def test_circular_reference_detected(self, tmp_path):
        """Circular reference should set circular=True and stop traversal."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs: []
            outputs:
              - name: Output A
                slug: output-a
                location: outputs/a.csv
                lineage:
                  sources:
                    - slug: output-b
              - name: Output B
                slug: output-b
                location: outputs/b.csv
                lineage:
                  sources:
                    - slug: output-a
            """,
        )
        node = get_upstream("output-a", project_path=tmp_path)
        assert node.slug == "output-a"
        assert len(node.sources) == 1
        b_node = node.sources[0]
        assert b_node.slug == "output-b"
        assert len(b_node.sources) == 1
        circular_node = b_node.sources[0]
        assert circular_node.slug == "output-a"
        assert circular_node.circular is True
        assert circular_node.sources == []  # stopped traversal


class TestGetUpstreamMissing:
    """Tests for graceful handling of missing sources."""

    def test_missing_source_creates_leaf(self, tmp_path):
        """Reference to non-existent slug should create leaf node."""
        _write_datasets_yaml(
            tmp_path,
            """\
            inputs: []
            outputs:
              - name: Output
                slug: my-output
                location: outputs/out.csv
                lineage:
                  sources:
                    - slug: nonexistent
            """,
        )
        node = get_upstream("my-output", project_path=tmp_path)
        assert len(node.sources) == 1
        assert node.sources[0].slug == "nonexistent"
        assert node.sources[0].sources == []  # graceful leaf


class TestDisplayLineage:
    """Tests for display_lineage ASCII tree rendering."""

    def test_simple_tree(self):
        """Should produce readable ASCII tree."""
        root = LineageNode(
            slug="output",
            sources=[
                LineageNode(slug="input-a"),
                LineageNode(slug="input-b"),
            ],
        )
        result = display_lineage(root)
        assert "output" in result
        assert "input-a" in result
        assert "input-b" in result

    def test_circular_marker(self):
        """Circular nodes should be marked with (circular)."""
        root = LineageNode(
            slug="output",
            sources=[
                LineageNode(slug="self-ref", circular=True),
            ],
        )
        result = display_lineage(root)
        assert "(circular)" in result

    def test_nested_tree_indentation(self):
        """Multi-level tree should have proper indentation."""
        root = LineageNode(
            slug="final",
            sources=[
                LineageNode(
                    slug="intermediate",
                    sources=[LineageNode(slug="raw")],
                ),
            ],
        )
        result = display_lineage(root)
        lines = result.strip().split("\n")
        # Root at top, then nested children
        assert len(lines) == 3


class TestLineageToDict:
    """Tests for lineage_to_dict JSON conversion."""

    def test_simple_conversion(self):
        """Should convert to nested dict structure."""
        root = LineageNode(
            slug="output",
            version="v1",
            sources=[LineageNode(slug="input")],
        )
        d = lineage_to_dict(root)
        assert d["slug"] == "output"
        assert d["version"] == "v1"
        assert d["circular"] is False
        assert len(d["sources"]) == 1
        assert d["sources"][0]["slug"] == "input"

    def test_circular_in_dict(self):
        """Circular flag should appear in dict."""
        node = LineageNode(slug="loop", circular=True)
        d = lineage_to_dict(node)
        assert d["circular"] is True
        assert d["sources"] == []

    def test_context_included(self):
        """Context dict should be included when present."""
        node = LineageNode(slug="output", context={"user": "test"})
        d = lineage_to_dict(node)
        assert d["context"] == {"user": "test"}
