"""
Tests for uncovered lines in sunstone.datasets module.

Covers error paths, edge cases in find_dataset_by_location,
add/update operations, lineage strict mode, and fetch_from_url.
"""

import socket
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from ruamel.yaml import YAML

from sunstone.datasets import DatasetsManager
from sunstone.handlers import _is_public_url
from sunstone.exceptions import DatasetNotFoundError, DatasetValidationError
from sunstone.lineage import (
    DatasetMetadata,
    FieldSchema,
    LineageMetadata,
    Source,
    SourceLocation,
)

_yaml = YAML()


def _write_datasets_yaml(project_path: Path, data: dict) -> None:
    """Helper to write a datasets.yaml file."""
    with open(project_path / "datasets.yaml", "w") as f:
        _yaml.dump(data, f)


def _minimal_project(tmp_path: Path, data: dict | None = None) -> Path:
    """Create a minimal project directory with a datasets.yaml."""
    project = tmp_path / "project"
    project.mkdir()
    if data is None:
        data = {"inputs": [], "outputs": []}
    _write_datasets_yaml(project, data)
    return project


class TestIsPublicUrlErrorPaths:
    """Tests for _is_public_url error handling (lines 102-110)."""

    def test_gaierror_returns_false(self) -> None:
        with patch("sunstone.handlers.socket.getaddrinfo", side_effect=socket.gaierror("DNS failure")):
            assert _is_public_url("https://nonexistent.invalid/data.csv") is False

    def test_value_error_returns_false(self) -> None:
        # Trigger ValueError by making ip_address raise on a bad address
        with patch(
            "sunstone.handlers.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("not-an-ip",))],
        ):
            with patch("sunstone.handlers.ipaddress.ip_address", side_effect=ValueError("bad IP")):
                assert _is_public_url("https://example.com/data.csv") is False

    def test_unexpected_exception_is_reraised(self) -> None:
        with patch(
            "sunstone.handlers.socket.getaddrinfo",
            side_effect=RuntimeError("unexpected"),
        ):
            with pytest.raises(RuntimeError, match="unexpected"):
                _is_public_url("https://example.com/data.csv")


class TestDatasetsManagerInit:
    """Tests for DatasetsManager.__init__ and _load edge cases (lines 135, 149)."""

    def test_missing_datasets_yaml_raises_file_not_found(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="datasets.yaml not found"):
            DatasetsManager(empty_dir)

    def test_outputs_key_auto_created_when_missing(self, tmp_path: Path) -> None:
        project = _minimal_project(tmp_path, {"inputs": []})
        mgr = DatasetsManager(project)
        assert mgr._data["outputs"] == []

    def test_inputs_key_auto_created_when_missing(self, tmp_path: Path) -> None:
        project = _minimal_project(tmp_path, {"outputs": []})
        mgr = DatasetsManager(project)
        assert mgr._data["inputs"] == []


class TestParsePublishEdgeCase:
    """Test _parse_publish returns None for non-bool/non-dict values (line 217)."""

    def test_parse_publish_with_unexpected_type_returns_none(self, tmp_path: Path) -> None:
        project = _minimal_project(tmp_path)
        mgr = DatasetsManager(project)
        assert mgr._parse_publish("some string") is None
        assert mgr._parse_publish(42) is None


class TestFindDatasetByLocation:
    """Tests for find_dataset_by_location complex matching (lines 388-414)."""

    def _make_project(self, tmp_path: Path) -> Path:
        """Create a project with an output dataset at outputs/data.csv."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "outputs").mkdir()
        (project / "outputs" / "data.csv").write_text("a,b\n1,2\n")
        data = {
            "inputs": [],
            "outputs": [
                {
                    "name": "Test Output",
                    "slug": "test-output",
                    "location": "outputs/data.csv",
                    "fields": [{"name": "a", "type": "string"}],
                }
            ],
        }
        _write_datasets_yaml(project, data)
        return project

    def test_absolute_path_resolution(self, tmp_path: Path) -> None:
        """Line 388: dataset location is absolute, resolves and matches."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "outputs").mkdir()
        (project / "outputs" / "data.csv").write_text("a,b\n1,2\n")
        abs_location = str(project / "outputs" / "data.csv")
        data = {
            "inputs": [],
            "outputs": [
                {
                    "name": "Abs Output",
                    "slug": "abs-output",
                    "location": abs_location,
                    "fields": [{"name": "a", "type": "string"}],
                }
            ],
        }
        _write_datasets_yaml(project, data)
        mgr = DatasetsManager(project)
        result = mgr.find_dataset_by_location(abs_location)
        assert result is not None
        assert result.slug == "abs-output"

    def test_resolved_paths_match(self, tmp_path: Path) -> None:
        """Line 391: resolved paths match even with different relative forms."""
        project = self._make_project(tmp_path)
        mgr = DatasetsManager(project)
        # Use a different relative path that resolves to the same file
        result = mgr.find_dataset_by_location("./outputs/../outputs/data.csv")
        assert result is not None
        assert result.slug == "test-output"

    def test_samefile_check(self, tmp_path: Path) -> None:
        """Line 397: samefile check when both exist."""
        project = self._make_project(tmp_path)
        mgr = DatasetsManager(project)
        # Create a symlink to the same file
        symlink = project / "link_data.csv"
        symlink.symlink_to(project / "outputs" / "data.csv")
        result = mgr.find_dataset_by_location(str(symlink))
        assert result is not None
        assert result.slug == "test-output"

    def test_fallback_matching_dataset_location_missing(self, tmp_path: Path) -> None:
        """Lines 402-414: fallback when dataset location doesn't exist but requested does."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "inputs").mkdir()
        # The dataset yaml points to a non-existent path
        actual_file = project / "inputs" / "data.csv"
        actual_file.write_text("a,b\n1,2\n")
        data = {
            "inputs": [
                {
                    "name": "Missing Input",
                    "slug": "missing-input",
                    "location": "old_dir/data.csv",
                    "fields": [{"name": "a", "type": "string"}],
                }
            ],
            "outputs": [],
        }
        _write_datasets_yaml(project, data)
        mgr = DatasetsManager(project)
        # The file exists at inputs/data.csv, dataset points to old_dir/data.csv
        # Same filename but dataset_loc doesn't exist - triggers fallback at lines 402+
        result = mgr.find_dataset_by_location("inputs/data.csv")
        assert result is not None
        assert result.slug == "missing-input"

    def test_find_by_absolute_requested_path(self, tmp_path: Path) -> None:
        """Line 388: requested location is absolute, converted to relative."""
        project = self._make_project(tmp_path)
        mgr = DatasetsManager(project)
        abs_path = str(project / "outputs" / "data.csv")
        result = mgr.find_dataset_by_location(abs_path)
        assert result is not None
        assert result.slug == "test-output"


class TestAddOutputDataset:
    """Tests for add_output_dataset duplicate slug check (line 517)."""

    def test_duplicate_slug_raises_validation_error(self, project_copy: Path) -> None:
        mgr = DatasetsManager(project_copy)
        with pytest.raises(DatasetValidationError, match="already exists"):
            mgr.add_output_dataset(
                name="Duplicate",
                slug="current-un-member-states",
                location="outputs/dup.csv",
                fields=[FieldSchema(name="x", type="string")],
            )


class TestUpdateOutputDataset:
    """Tests for update_output_dataset (lines 552-562)."""

    def test_update_fields_and_location(self, project_copy: Path) -> None:
        """Lines 554-557: updating fields and location."""
        mgr = DatasetsManager(project_copy)
        new_fields = [FieldSchema(name="new_col", type="integer")]
        result = mgr.update_output_dataset(
            slug="current-un-member-states",
            fields=new_fields,
            location="outputs/updated.csv",
        )
        assert result.location == "outputs/updated.csv"
        assert result.fields is not None
        assert len(result.fields) == 1
        assert result.fields[0].name == "new_col"

    def test_update_fields_only(self, project_copy: Path) -> None:
        mgr = DatasetsManager(project_copy)
        new_fields = [FieldSchema(name="col_a", type="string")]
        result = mgr.update_output_dataset(
            slug="current-un-member-states",
            fields=new_fields,
        )
        assert result.fields is not None
        assert len(result.fields) == 1
        # Location should remain unchanged
        assert result.location == "outputs/current_un_member_states.csv"

    def test_update_nonexistent_slug_raises_not_found(self, project_copy: Path) -> None:
        """Line 562: DatasetNotFoundError when slug not found."""
        mgr = DatasetsManager(project_copy)
        with pytest.raises(DatasetNotFoundError, match="not found"):
            mgr.update_output_dataset(
                slug="nonexistent-slug",
                fields=[FieldSchema(name="x", type="string")],
            )


class TestUpdateOutputLineage:
    """Tests for update_output_lineage (lines 629, 676-698)."""

    def test_nonexistent_slug_raises_not_found(self, project_copy: Path) -> None:
        """Line 629: DatasetNotFoundError."""
        mgr = DatasetsManager(project_copy)
        lineage = LineageMetadata(sources=[])
        with pytest.raises(DatasetNotFoundError, match="not found"):
            mgr.update_output_lineage(
                slug="nonexistent",
                lineage=lineage,
                content_hash="abc123",
            )

    def test_strict_mode_raises_when_lineage_differs(self, project_copy: Path) -> None:
        """Lines 676-684: strict mode raises when files differ."""
        mgr = DatasetsManager(project_copy)
        lineage = LineageMetadata(sources=[])
        # Use a different hash to force a change
        with pytest.raises(DatasetValidationError, match="strict mode"):
            mgr.update_output_lineage(
                slug="current-un-member-states",
                lineage=lineage,
                content_hash="different_hash_value",
                strict=True,
            )

    def test_strict_mode_passes_when_lineage_matches(self, project_copy: Path) -> None:
        """Lines 686-687: strict mode passes and cleans up temp file."""
        mgr = DatasetsManager(project_copy)
        # First write lineage in relaxed mode
        source_ds = mgr.find_dataset_by_slug("official-un-member-states", "input")
        assert source_ds is not None
        lineage = LineageMetadata(sources=[source_ds])
        mgr.update_output_lineage(
            slug="current-un-member-states",
            lineage=lineage,
            content_hash="test_hash_123",
        )
        # Now run in strict mode with the same hash - should pass without error
        mgr.update_output_lineage(
            slug="current-un-member-states",
            lineage=lineage,
            content_hash="test_hash_123",
            strict=True,
        )

    def test_exception_cleans_up_temp_file(self, project_copy: Path) -> None:
        """Lines 694-698: cleanup temp file on exception."""
        mgr = DatasetsManager(project_copy)
        lineage = LineageMetadata(sources=[])
        # Patch _yaml.dump to raise after temp file is created
        with patch("sunstone.datasets._yaml.dump", side_effect=RuntimeError("dump failed")):
            with pytest.raises(RuntimeError, match="dump failed"):
                mgr.update_output_lineage(
                    slug="current-un-member-states",
                    lineage=lineage,
                    content_hash="abc",
                )
        # Verify no temp files were left behind
        temp_files = list(project_copy.glob("datasets_*.yaml"))
        assert len(temp_files) == 0


class TestGetAbsolutePath:
    """Test get_absolute_path (line 712)."""

    def test_relative_path_resolution(self, project_copy: Path) -> None:
        mgr = DatasetsManager(project_copy)
        result = mgr.get_absolute_path("outputs/data.csv")
        assert result == (project_copy / "outputs" / "data.csv").resolve()

    def test_absolute_path_passthrough(self, project_copy: Path, tmp_path: Path) -> None:
        mgr = DatasetsManager(project_copy)
        abs_file = tmp_path / "some" / "file.csv"
        result = mgr.get_absolute_path(str(abs_file))
        assert result == abs_file


class TestFetchFromUrl:
    """Tests for fetch_from_url edge cases (lines 739, 745-746, 801-805)."""

    def _make_dataset_with_source(self, url: str | None = None) -> DatasetMetadata:
        """Create a DatasetMetadata with optional source URL."""
        source = None
        if url is not None:
            source = Source(
                name="Test Source",
                location=SourceLocation(data=url),
                attributed_to="Test",
                acquired_at="2025-01-01",
                acquisition_method="manual-download",
                license="CC-BY-4.0",
            )
        return DatasetMetadata(
            name="Test Dataset",
            slug="test-dataset",
            location="inputs/test.csv",
            source=source,
        )

    def test_no_source_url_raises_value_error(self, project_copy: Path) -> None:
        """Line 739: ValueError when no source URL."""
        mgr = DatasetsManager(project_copy)
        dataset = self._make_dataset_with_source(url=None)
        with pytest.raises(ValueError, match="has no source URL"):
            mgr.fetch_from_url(dataset)

    def test_no_source_at_all_raises_value_error(self, project_copy: Path) -> None:
        """Line 739: ValueError when source is None."""
        mgr = DatasetsManager(project_copy)
        dataset = DatasetMetadata(
            name="No Source",
            slug="no-source",
            location="inputs/test.csv",
        )
        with pytest.raises(ValueError, match="has no source URL"):
            mgr.fetch_from_url(dataset)

    def test_existing_file_skips_fetch(self, project_copy: Path) -> None:
        """Lines 745-746: skip fetch when file already exists."""
        mgr = DatasetsManager(project_copy)
        # Create the file so it already exists
        target = project_copy / "inputs" / "test.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("existing data")
        dataset = self._make_dataset_with_source(url="https://example.com/data.csv")
        result = mgr.fetch_from_url(dataset)
        assert result == target.resolve()
        # Verify file content unchanged (no fetch happened)
        assert target.read_text() == "existing data"

    def test_timeout_exception_propagates(self, project_copy: Path) -> None:
        """Timeout handling."""
        mgr = DatasetsManager(project_copy)
        dataset = self._make_dataset_with_source(url="https://example.com/data.csv")
        with patch("sunstone.handlers._is_public_url", return_value=True):
            with patch("sunstone.handlers.requests.get", side_effect=requests.Timeout("timed out")):
                with pytest.raises(requests.Timeout):
                    mgr.fetch_from_url(dataset, force=True)

    def test_request_exception_propagates(self, project_copy: Path) -> None:
        """RequestException handling."""
        mgr = DatasetsManager(project_copy)
        dataset = self._make_dataset_with_source(url="https://example.com/data.csv")
        with patch("sunstone.handlers._is_public_url", return_value=True):
            with patch(
                "sunstone.handlers.requests.get",
                side_effect=requests.ConnectionError("connection failed"),
            ):
                with pytest.raises(requests.ConnectionError):
                    mgr.fetch_from_url(dataset, force=True)
