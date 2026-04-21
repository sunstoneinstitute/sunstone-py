# tests/test_lock_file.py
import warnings
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from sunstone.cli import app
from sunstone.datasets import DatasetsManager
from sunstone.lineage import DatasetMetadata, LineageMetadata

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)


def _write_yaml(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        _yaml.dump(data, f)


@pytest.fixture()
def lock_project(tmp_path: Path) -> Path:
    """Minimal project with datasets.yaml and datasets.lock.yaml."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "inputs").mkdir()
    (project / "outputs").mkdir()

    # Create a minimal CSV so location resolves
    (project / "inputs" / "data.csv").write_text("a,b\n1,2\n")

    _write_yaml(
        project / "datasets.yaml",
        {
            "inputs": [
                {
                    "name": "Input Data",
                    "slug": "input-data",
                    "location": "inputs/data.csv",
                    "fields": [
                        {"name": "a", "type": "integer"},
                        {"name": "b", "type": "integer"},
                    ],
                }
            ],
            "outputs": [
                {
                    "name": "Output Data",
                    "slug": "output-data",
                    "location": "outputs/output.csv",
                    "fields": [{"name": "a", "type": "integer"}],
                }
            ],
        },
    )

    _write_yaml(
        project / "datasets.lock.yaml",
        {
            "inputs": [
                {
                    "slug": "input-data",
                    "content_hash": "sha256:abc123",
                    "row_count": 1,
                }
            ],
            "outputs": [
                {
                    "slug": "output-data",
                    "content_hash": "sha256:def456",
                    "created_at": "2026-04-10T14:23:01.508497",
                    "sources": [{"slug": "input-data"}],
                }
            ],
        },
    )

    return project


class TestLockFileLoading:
    def test_load_lock_file(self, lock_project: Path) -> None:
        manager = DatasetsManager(lock_project)
        assert manager.lock_data is not None
        assert len(manager.lock_data.get("outputs", [])) == 1
        assert manager.lock_data["outputs"][0]["slug"] == "output-data"

    def test_load_without_lock_file(self, tmp_path: Path) -> None:
        """Lock file is optional — loading succeeds without it."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {"inputs": [], "outputs": []},
        )
        manager = DatasetsManager(project)
        assert manager.lock_data == {}

    def test_lock_file_path_property(self, lock_project: Path) -> None:
        manager = DatasetsManager(lock_project)
        expected = lock_project / "datasets.lock.yaml"
        assert manager.lock_file == expected


class TestLockFileMerge:
    def test_output_lineage_from_lock_file(self, lock_project: Path) -> None:
        """Output lineage should come from lock file, not inline."""
        manager = DatasetsManager(lock_project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "output-data")
        assert output.was_derived_from is not None
        assert len(output.was_derived_from) == 1
        assert output.was_derived_from[0].slug == "input-data"

    def test_inline_lineage_fallback(self, tmp_path: Path) -> None:
        """Without lock file, inline lineage still works."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [{"name": "In", "slug": "in", "location": "in.csv"}],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc",
                            "created_at": "2026-01-01T00:00:00",
                            "sources": [{"slug": "in"}],
                        },
                    }
                ],
            },
        )
        manager = DatasetsManager(project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "out")
        assert output.was_derived_from is not None
        assert output.was_derived_from[0].slug == "in"

    def test_lock_file_lineage_overrides_inline(self, tmp_path: Path) -> None:
        """Lock file lineage takes precedence over inline."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {"name": "Old", "slug": "old-source", "location": "old.csv"},
                    {"name": "New", "slug": "new-source", "location": "new.csv"},
                ],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:stale",
                            "sources": [{"slug": "old-source"}],
                        },
                    }
                ],
            },
        )
        _write_yaml(
            project / "datasets.lock.yaml",
            {
                "outputs": [
                    {
                        "slug": "out",
                        "content_hash": "sha256:fresh",
                        "sources": [{"slug": "new-source"}],
                    }
                ],
            },
        )
        manager = DatasetsManager(project)
        outputs = manager.get_all_outputs()
        output = next(o for o in outputs if o.slug == "out")
        assert output.was_derived_from is not None
        assert output.was_derived_from[0].slug == "new-source"


class TestLockFileWriting:
    def test_update_lineage_writes_to_lock_file(self, lock_project: Path) -> None:
        """Lineage updates should write to datasets.lock.yaml, not datasets.yaml."""
        manager = DatasetsManager(lock_project)
        source = DatasetMetadata(
            name="Input Data",
            slug="input-data",
            location="inputs/data.csv",
        )
        lineage = LineageMetadata(sources=[source])
        manager.update_output_lineage(
            slug="output-data",
            lineage=lineage,
            content_hash="sha256:newvalue",
        )

        # Lock file should have the lineage
        with open(lock_project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        lock_output = next(o for o in lock_data["outputs"] if o["slug"] == "output-data")
        assert lock_output["content_hash"] == "sha256:newvalue"

        # datasets.yaml should NOT have lineage
        with open(lock_project / "datasets.yaml") as f:
            yaml_data = _yaml.load(f)
        yaml_output = next(o for o in yaml_data["outputs"] if o["slug"] == "output-data")
        assert "lineage" not in yaml_output

    def test_update_lineage_creates_lock_file(self, tmp_path: Path) -> None:
        """If no lock file exists, one should be created."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "data.csv").write_text("a\n1\n")

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [{"name": "In", "slug": "in", "location": "inputs/data.csv"}],
                "outputs": [{"name": "Out", "slug": "out", "location": "outputs/out.csv"}],
            },
        )

        assert not (project / "datasets.lock.yaml").exists()

        manager = DatasetsManager(project)
        source = DatasetMetadata(name="In", slug="in", location="inputs/data.csv")
        lineage = LineageMetadata(sources=[source])
        manager.update_output_lineage(slug="out", lineage=lineage, content_hash="sha256:first")

        assert (project / "datasets.lock.yaml").exists()
        with open(project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        assert lock_data["outputs"][0]["content_hash"] == "sha256:first"

    def test_update_lineage_preserves_other_lock_entries(self, lock_project: Path) -> None:
        """Updating one output shouldn't clobber other lock entries."""
        # Add a second output to datasets.yaml
        with open(lock_project / "datasets.yaml") as f:
            data = _yaml.load(f)
        data["outputs"].append({"name": "Second", "slug": "second-output", "location": "outputs/second.csv"})
        _write_yaml(lock_project / "datasets.yaml", data)

        # Add second output to lock file
        with open(lock_project / "datasets.lock.yaml") as f:
            lock = _yaml.load(f)
        lock["outputs"].append({"slug": "second-output", "content_hash": "sha256:keep-this"})
        _write_yaml(lock_project / "datasets.lock.yaml", lock)

        manager = DatasetsManager(lock_project)
        source = DatasetMetadata(name="Input Data", slug="input-data", location="inputs/data.csv")
        lineage = LineageMetadata(sources=[source])
        manager.update_output_lineage(slug="output-data", lineage=lineage, content_hash="sha256:updated")

        with open(lock_project / "datasets.lock.yaml") as f:
            result = _yaml.load(f)
        second = next(o for o in result["outputs"] if o["slug"] == "second-output")
        assert second["content_hash"] == "sha256:keep-this"


class TestResolveCommand:
    def test_resolve_creates_lock_file(self, tmp_path: Path) -> None:
        """sunstone dataset resolve should create datasets.lock.yaml."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "inputs").mkdir()
        (project / "outputs").mkdir()
        (project / "inputs" / "data.csv").write_text("name,age\nalice,30\nbob,25\n")
        (project / "outputs" / "out.csv").write_text("name\nalice\n")

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [
                    {
                        "name": "People",
                        "slug": "people",
                        "location": "inputs/data.csv",
                        "fields": [
                            {"name": "name", "type": "string"},
                            {"name": "age", "type": "integer"},
                        ],
                    }
                ],
                "outputs": [
                    {
                        "name": "Names",
                        "slug": "names",
                        "location": "outputs/out.csv",
                        "fields": [{"name": "name", "type": "string"}],
                    }
                ],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "resolve", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0

        lock_path = project / "datasets.lock.yaml"
        assert lock_path.exists()

        with open(lock_path) as f:
            lock = _yaml.load(f)
        input_entry = next(i for i in lock["inputs"] if i["slug"] == "people")
        assert "content_hash" in input_entry

    def test_resolve_check_mode(self, lock_project: Path) -> None:
        """--check should exit 0 when lock file is up to date."""
        runner = CliRunner()
        # First resolve to create a fresh lock
        runner.invoke(
            app,
            ["dataset", "resolve", "-f", str(lock_project / "datasets.yaml")],
        )
        # Now check — should be up to date
        result = runner.invoke(
            app,
            ["dataset", "resolve", "--check", "-f", str(lock_project / "datasets.yaml")],
        )
        assert result.exit_code == 0

    def test_resolve_check_fails_when_stale(self, lock_project: Path) -> None:
        """--check should exit 1 when lock file is stale."""
        # First create a valid lock file
        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "resolve", "-f", str(lock_project / "datasets.yaml")],
        )
        # Modify the input file to make the lock stale
        (lock_project / "inputs" / "data.csv").write_text("a,b\n99,99\n")

        result = runner.invoke(
            app,
            ["dataset", "resolve", "--check", "-f", str(lock_project / "datasets.yaml")],
        )
        assert result.exit_code == 1


class TestMigrateCommand:
    def test_migrate_extracts_lineage(self, tmp_path: Path) -> None:
        """migrate should move inline lineage to lock file."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [{"name": "In", "slug": "in", "location": "in.csv"}],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc123",
                            "created_at": "2026-01-01T00:00:00",
                            "sources": [{"slug": "in", "name": "In", "location": "in.csv"}],
                        },
                    }
                ],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0

        # datasets.yaml should no longer have lineage
        with open(project / "datasets.yaml") as f:
            yaml_data = _yaml.load(f)
        yaml_output = next(o for o in yaml_data["outputs"] if o["slug"] == "out")
        assert "lineage" not in yaml_output

        # datasets.lock.yaml should have the lineage
        with open(project / "datasets.lock.yaml") as f:
            lock_data = _yaml.load(f)
        lock_output = next(o for o in lock_data["outputs"] if o["slug"] == "out")
        assert lock_output["content_hash"] == "sha256:abc123"
        assert lock_output["sources"][0]["slug"] == "in"

    def test_migrate_adds_gitattributes_in_git_repo(self, tmp_path: Path) -> None:
        """migrate should add .gitattributes only inside a git repo."""
        import subprocess

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True)

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {"content_hash": "sha256:abc"},
                    }
                ],
            },
        )

        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )

        gitattributes = project / ".gitattributes"
        assert gitattributes.exists()
        assert "datasets.lock.yaml" in gitattributes.read_text()
        assert "linguist-generated=true" in gitattributes.read_text()

    def test_migrate_skips_gitattributes_outside_git(self, tmp_path: Path) -> None:
        """migrate should not create .gitattributes outside a git repo."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {"content_hash": "sha256:abc"},
                    }
                ],
            },
        )

        runner = CliRunner()
        runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )

        assert not (project / ".gitattributes").exists()

    def test_migrate_noop_without_inline_lineage(self, tmp_path: Path) -> None:
        """migrate with no inline lineage should report nothing to migrate."""
        project = tmp_path / "project"
        project.mkdir()

        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [{"name": "Out", "slug": "out", "location": "out.csv"}],
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dataset", "migrate", "-f", str(project / "datasets.yaml")],
        )
        assert result.exit_code == 0
        assert "nothing to migrate" in result.output.lower() or "no inline" in result.output.lower()


class TestDeprecationWarning:
    def test_inline_lineage_emits_deprecation_warning(self, tmp_path: Path) -> None:
        """Loading inline lineage should emit a DeprecationWarning."""
        project = tmp_path / "project"
        project.mkdir()
        _write_yaml(
            project / "datasets.yaml",
            {
                "inputs": [],
                "outputs": [
                    {
                        "name": "Out",
                        "slug": "out",
                        "location": "out.csv",
                        "lineage": {
                            "content_hash": "sha256:abc",
                            "sources": [{"slug": "in"}],
                        },
                    }
                ],
            },
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DatasetsManager(project)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) >= 1
            assert "datasets.lock.yaml" in str(deprecations[0].message)

    def test_no_warning_when_lock_file_present(self, lock_project: Path) -> None:
        """No deprecation warning when lineage is in lock file."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DatasetsManager(lock_project)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) == 0
