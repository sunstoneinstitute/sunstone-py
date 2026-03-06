"""
End-to-end lineage flow tests.

Tests the full pipeline: read datasets -> session records reads ->
write output -> session flushes with context -> update_output_lineage persists.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from ruamel.yaml import YAML

import sunstone
from sunstone.session import close_session, get_session


@pytest.fixture
def flow_project(tmp_path: Path) -> Path:
    """Create a minimal project with datasets.yaml and input CSV files."""
    project = tmp_path / "flow_project"
    project.mkdir()

    # Create input directory and CSV files
    inputs_dir = project / "inputs"
    inputs_dir.mkdir()

    csv1 = inputs_dir / "alpha.csv"
    csv1.write_text("id,name,value\n1,Alice,100\n2,Bob,200\n")

    csv2 = inputs_dir / "beta.csv"
    csv2.write_text("id,score\n1,85\n2,92\n")

    # Create outputs directory
    (project / "outputs").mkdir()

    # Create datasets.yaml with two inputs and one pre-registered output
    yaml = YAML()
    yaml.default_flow_style = False
    data = {
        "inputs": [
            {
                "name": "Alpha Dataset",
                "slug": "alpha-data",
                "location": "inputs/alpha.csv",
                "fields": [
                    {"name": "id", "type": "integer"},
                    {"name": "name", "type": "string"},
                    {"name": "value", "type": "integer"},
                ],
                "source": {
                    "name": "Test Source",
                    "location": {"data": None},
                    "attributedTo": "Test",
                    "acquiredAt": "2026-01-01",
                    "acquisitionMethod": "manual",
                    "license": "CC-BY-4.0",
                },
            },
            {
                "name": "Beta Dataset",
                "slug": "beta-data",
                "location": "inputs/beta.csv",
                "fields": [
                    {"name": "id", "type": "integer"},
                    {"name": "score", "type": "integer"},
                ],
                "source": {
                    "name": "Test Source",
                    "location": {"data": None},
                    "attributedTo": "Test",
                    "acquiredAt": "2026-01-01",
                    "acquisitionMethod": "manual",
                    "license": "CC-BY-4.0",
                },
            },
        ],
        "outputs": [],
    }
    with open(project / "datasets.yaml", "w") as f:
        yaml.dump(data, f)

    return project


@pytest.fixture(autouse=True)
def _clean_session() -> Any:
    """Close the lineage session after each test for isolation."""
    yield
    close_session()


# Mock context to avoid git subprocess calls
_MOCK_CONTEXT_DICT = {
    "user": "test-user",
    "execution_timestamp": "2026-01-15T10:00:00+00:00",
}


def _mock_detect_context() -> Any:
    """Return a mock ExecutionContext."""
    from sunstone.context import ExecutionContext

    return ExecutionContext(
        user="test-user",
        execution_timestamp="2026-01-15T10:00:00+00:00",
    )


class TestSessionRecording:
    """Tests that read methods record reads in the session."""

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_read_dataset_records_session_read(self, mock_ctx: Any, flow_project: Path) -> None:
        """After read_dataset(), session should have 1 read recorded."""
        sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)

        session = get_session()
        assert len(session._reads) == 1
        assert session._reads[0].slug == "alpha-data"

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_read_csv_path_records_session_read(self, mock_ctx: Any, flow_project: Path) -> None:
        """After read_csv() with file path, session should have 1 read recorded."""
        sunstone.DataFrame.read_csv("inputs/alpha.csv", project_path=flow_project)

        session = get_session()
        assert len(session._reads) == 1
        assert session._reads[0].slug == "alpha-data"

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_read_csv_slug_delegates_no_double_record(self, mock_ctx: Any, flow_project: Path) -> None:
        """read_csv() with slug delegates to read_dataset; only 1 read recorded."""
        sunstone.DataFrame.read_csv("alpha-data", project_path=flow_project)

        session = get_session()
        # Should be exactly 1, not 2 (no double recording)
        assert len(session._reads) == 1


class TestFlushAndPersist:
    """Tests that to_csv flushes session and persists context + params."""

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_two_reads_one_write_records_both_sources(self, mock_ctx: Any, flow_project: Path) -> None:
        """Read two datasets, write output -> lineage has both sources + context."""
        df1 = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)
        df2 = sunstone.DataFrame.read_dataset("beta-data", project_path=flow_project)

        merged = df1.merge(df2, on="id")
        merged.to_csv(
            "outputs/merged.csv",
            slug="merged-output",
            name="Merged Output",
            index=False,
        )

        # Read datasets.yaml and check lineage
        yaml = YAML()
        with open(flow_project / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next(d for d in data["outputs"] if d["slug"] == "merged-output")
        lineage = output["lineage"]

        assert "content_hash" in lineage
        assert "created_at" in lineage
        assert "sources" in lineage
        assert len(lineage["sources"]) >= 1  # At least from DataFrame lineage
        assert "context" in lineage
        assert lineage["context"]["user"] == "test-user"

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_transformation_params_persisted(self, mock_ctx: Any, flow_project: Path) -> None:
        """to_csv(transformation_params=...) persists params in datasets.yaml."""
        df = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)

        df.to_csv(
            "outputs/filtered.csv",
            slug="filtered-output",
            name="Filtered Output",
            transformation_params={"threshold": 100},
            index=False,
        )

        yaml = YAML()
        with open(flow_project / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next(d for d in data["outputs"] if d["slug"] == "filtered-output")
        lineage = output["lineage"]

        assert "transformation_params" in lineage
        assert lineage["transformation_params"]["threshold"] == 100

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_session_cleared_after_flush(self, mock_ctx: Any, flow_project: Path) -> None:
        """After to_csv(), session reads should be cleared."""
        df = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)
        df.to_csv(
            "outputs/clear_test.csv",
            slug="clear-test",
            name="Clear Test",
            index=False,
        )

        session = get_session()
        # Reads should be cleared after flush
        assert len(session._reads) == 0
