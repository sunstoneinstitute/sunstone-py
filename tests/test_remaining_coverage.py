"""
Tests for remaining coverage gaps in lineage, pandas, and queries modules.
"""

from datetime import datetime
from pathlib import Path

import pytest
from ruamel.yaml import YAML

import sunstone
from sunstone import pandas as spd
from sunstone.lineage import LineageMetadata
from sunstone.queries import get_upstream


@pytest.fixture
def query_project(tmp_path: Path) -> Path:
    """Create a project with chained lineage for query tests."""
    project = tmp_path / "query_project"
    project.mkdir()
    (project / "inputs").mkdir()
    (project / "outputs").mkdir()

    (project / "inputs" / "raw.csv").write_text("id,val\n1,10\n")

    yaml = YAML()
    yaml.default_flow_style = False
    data = {
        "inputs": [
            {
                "name": "Raw Data",
                "slug": "raw-data",
                "location": "inputs/raw.csv",
                "fields": [{"name": "id", "type": "integer"}, {"name": "val", "type": "integer"}],
            },
        ],
        "outputs": [
            {
                "name": "Level 1",
                "slug": "level-1",
                "location": "outputs/level1.csv",
                "fields": [{"name": "id", "type": "integer"}],
                "lineage": {
                    "sources": [{"slug": "raw-data"}],
                },
            },
        ],
    }
    with open(project / "datasets.yaml", "w") as f:
        yaml.dump(data, f)

    return project


class TestLineageMetadataToDict:
    """Tests for LineageMetadata.to_dict() with created_at and data_hash."""

    def test_to_dict_with_created_at(self) -> None:
        """to_dict includes created_at when set."""
        lineage = LineageMetadata()
        lineage.created_at = datetime(2026, 1, 15, 10, 0, 0)
        result = lineage.to_dict()
        assert "created_at" in result
        assert result["created_at"] == "2026-01-15T10:00:00"

    def test_to_dict_with_data_hash(self) -> None:
        """to_dict includes data_hash when set."""
        lineage = LineageMetadata()
        lineage.data_hash = "abc123"
        result = lineage.to_dict()
        assert "data_hash" in result
        assert result["data_hash"] == "abc123"

    def test_to_dict_without_optional_fields(self) -> None:
        """to_dict omits created_at and data_hash when None."""
        lineage = LineageMetadata()
        result = lineage.to_dict()
        assert "created_at" not in result
        assert "data_hash" not in result

    def test_to_dict_with_both(self) -> None:
        """to_dict includes both when set."""
        lineage = LineageMetadata()
        lineage.created_at = datetime(2026, 3, 1, 12, 0, 0)
        lineage.data_hash = "deadbeef"
        result = lineage.to_dict()
        assert result["created_at"] == "2026-03-01T12:00:00"
        assert result["data_hash"] == "deadbeef"


class TestPandasReadCsvPassthrough:
    """Tests that sunstone.pandas.read_csv delegates to DataFrame.read_csv."""

    def test_read_csv_via_pandas_module(self, project_path: Path) -> None:
        """read_csv from sunstone.pandas returns a tracked DataFrame."""
        df = spd.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=project_path,
            strict=False,
        )
        assert isinstance(df, sunstone.DataFrame)
        assert len(df.data) > 0
        assert len(df.metadata.lineage.sources) > 0


class TestPandasConcatEmpty:
    """Tests for sunstone.pandas.concat with empty input."""

    def test_concat_empty_list_raises(self) -> None:
        """concat with empty list raises ValueError."""
        with pytest.raises(ValueError, match="No objects to concatenate"):
            spd.concat([])


@pytest.mark.filterwarnings("ignore:Inline lineage:DeprecationWarning")
class TestQueryLineageDefaultProjectPath:
    """Tests for queries.get_upstream with default project_path."""

    def test_get_upstream_with_explicit_project_path(self, query_project: Path) -> None:
        """get_upstream builds lineage tree with explicit project_path."""
        node = get_upstream("level-1", project_path=query_project)
        assert node.slug == "level-1"
        assert len(node.sources) == 1
        assert node.sources[0].slug == "raw-data"


@pytest.mark.filterwarnings("ignore:Inline lineage:DeprecationWarning")
class TestQueryLineageDepthLimit:
    """Tests for _build_node depth limit."""

    def test_depth_limit_stops_recursion(self, tmp_path: Path) -> None:
        """Recursion stops at max_depth, returning a leaf node."""
        project = tmp_path / "deep_project"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "seed.csv").write_text("x\n1\n")

        yaml = YAML()
        yaml.default_flow_style = False

        # Create a chain of outputs: L4 -> L3 -> L2 -> L1 -> seed
        # All intermediate nodes are outputs so they have lineage to resolve
        data = {
            "inputs": [
                {
                    "name": "Seed",
                    "slug": "seed",
                    "location": "inputs/seed.csv",
                    "fields": [{"name": "x", "type": "integer"}],
                },
            ],
            "outputs": [
                {
                    "name": "Level 1",
                    "slug": "l1",
                    "location": "outputs/l1.csv",
                    "fields": [{"name": "x", "type": "integer"}],
                    "lineage": {"sources": [{"slug": "seed"}]},
                },
                {
                    "name": "Level 2",
                    "slug": "l2",
                    "location": "outputs/l2.csv",
                    "fields": [{"name": "x", "type": "integer"}],
                    "lineage": {"sources": [{"slug": "l1"}]},
                },
                {
                    "name": "Level 3",
                    "slug": "l3",
                    "location": "outputs/l3.csv",
                    "fields": [{"name": "x", "type": "integer"}],
                    "lineage": {"sources": [{"slug": "l2"}]},
                },
                {
                    "name": "Level 4",
                    "slug": "l4",
                    "location": "outputs/l4.csv",
                    "fields": [{"name": "x", "type": "integer"}],
                    "lineage": {"sources": [{"slug": "l3"}]},
                },
            ],
        }
        with open(project / "datasets.yaml", "w") as f:
            yaml.dump(data, f)

        # max_depth=2: depth 0 (l4) -> depth 1 (l3) -> depth 2 (l2)
        # At depth 3, l2's source l1 hits depth > max_depth and is returned as leaf
        node = get_upstream("l4", project_path=project, max_depth=2)
        assert node.slug == "l4"
        # l4 -> l3
        assert len(node.sources) == 1
        l3 = node.sources[0]
        assert l3.slug == "l3"
        # l3 -> l2
        assert len(l3.sources) == 1
        l2 = l3.sources[0]
        assert l2.slug == "l2"
        # l2 has source l1, but l1 would be at depth 3 > max_depth=2
        # so l1 is returned as a leaf with no sources resolved
        assert len(l2.sources) == 1
        l1 = l2.sources[0]
        assert l1.slug == "l1"
        assert len(l1.sources) == 0  # truncated by depth limit
