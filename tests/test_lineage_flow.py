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

    @pytest.fixture(autouse=True)
    def _fresh_session(self) -> None:
        """Ensure a fresh session for each test."""
        close_session()

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

        # Lineage should be in datasets.lock.yaml, not datasets.yaml
        yaml = YAML()
        with open(flow_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "merged-output")

        assert "content_hash" in lock_output
        assert "created_at" in lock_output
        assert "sources" in lock_output
        assert len(lock_output["sources"]) >= 1  # At least from DataFrame lineage
        assert "context" in lock_output
        assert lock_output["context"]["user"] == "test-user"

        # PROV-O: activity section should also be present
        assert "activity" in lock_output
        activity = lock_output["activity"]
        assert activity["id"].startswith("exec-")
        assert any(a["id"] == "test-user" for a in activity["agents"])
        assert any(a["type"] == "prov:SoftwareAgent" for a in activity["agents"])
        # Activity should record usage of both input datasets
        used_slugs = {u["entity"] for u in activity["used"]}
        assert "alpha-data" in used_slugs
        assert "beta-data" in used_slugs

        # datasets.yaml should NOT have lineage
        with open(flow_project / "datasets.yaml") as f:
            yaml_data = yaml.load(f)
        yaml_output = next(d for d in yaml_data["outputs"] if d["slug"] == "merged-output")
        assert "lineage" not in yaml_output

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
        with open(flow_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "filtered-output")

        assert "transformation_params" in lock_output
        assert lock_output["transformation_params"]["threshold"] == 100

        # PROV-O: activity should also carry transformation_params
        assert "activity" in lock_output
        assert lock_output["activity"]["transformation_params"]["threshold"] == 100

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

    def test_script_path_relative_when_inside_project(self, flow_project: Path) -> None:
        """script_path in context should be relative when inside the project."""
        abs_script = str(flow_project / "scripts" / "process.py")

        def _mock_ctx_with_script() -> Any:
            from sunstone.context import ExecutionContext

            return ExecutionContext(
                script_path=abs_script,
                user="test-user",
                execution_timestamp="2026-01-15T10:00:00+00:00",
            )

        with patch(
            "sunstone.context.detect_execution_context",
            side_effect=_mock_ctx_with_script,
        ):
            df = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)
            df.to_csv(
                "outputs/relative_test.csv",
                slug="relative-test",
                name="Relative Test",
                index=False,
            )

        yaml = YAML()
        with open(flow_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "relative-test")
        context = lock_output["context"]
        assert context["script_path"] == "scripts/process.py"

        # PROV-O: activity script_path should also be relativized
        activity = lock_output["activity"]
        assert activity["script_path"] == "scripts/process.py"

    def test_script_path_kept_absolute_when_outside_project(self, flow_project: Path) -> None:
        """script_path should stay absolute when outside the project."""
        abs_script = "/some/other/place/process.py"

        def _mock_ctx_outside() -> Any:
            from sunstone.context import ExecutionContext

            return ExecutionContext(
                script_path=abs_script,
                user="test-user",
                execution_timestamp="2026-01-15T10:00:00+00:00",
            )

        with patch(
            "sunstone.context.detect_execution_context",
            side_effect=_mock_ctx_outside,
        ):
            df = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)
            df.to_csv(
                "outputs/absolute_test.csv",
                slug="absolute-test",
                name="Absolute Test",
                index=False,
            )

        yaml = YAML()
        with open(flow_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "absolute-test")
        context = lock_output["context"]
        assert context["script_path"] == "/some/other/place/process.py"

    @patch("sunstone.context.detect_execution_context", side_effect=_mock_detect_context)
    def test_field_derivations_auto_populated_and_persisted(self, mock_ctx: Any, flow_project: Path) -> None:
        """Read two datasets, merge, write -> field_derivations appear in datasets.yaml."""
        df1 = sunstone.DataFrame.read_dataset("alpha-data", project_path=flow_project)
        df2 = sunstone.DataFrame.read_dataset("beta-data", project_path=flow_project)

        merged = df1.merge(df2, on="id")
        merged.to_csv(
            "outputs/merged.csv",
            slug="merged-output",
            name="Merged Output",
            index=False,
        )

        yaml = YAML()
        with open(flow_project / "datasets.lock.yaml") as f:
            lock_data = yaml.load(f)

        lock_output = next(d for d in lock_data["outputs"] if d["slug"] == "merged-output")

        assert "field_derivations" in lock_output
        fd = lock_output["field_derivations"]
        fd_by_field = {d["output_field"]: d for d in fd}

        # Columns from alpha-data
        assert fd_by_field["name"]["source_entity"] == "alpha-data"
        assert fd_by_field["name"]["source_field"] == "name"
        assert fd_by_field["value"]["source_entity"] == "alpha-data"
        assert fd_by_field["value"]["source_field"] == "value"

        # Column from beta-data
        assert fd_by_field["score"]["source_entity"] == "beta-data"
        assert fd_by_field["score"]["source_field"] == "score"

        # 'id' exists in both — should have derivation from at least one source
        assert "id" in fd_by_field
