"""Tests for `sunstone package changed` and `package push --namespaces-only`."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sunstone.changed import affected_projects, discover_datasets_files, git_changed_paths
from sunstone.cli import app

OUTPUT = (
    "outputs:\n  - name: out\n    title: Out\n    path: out.csv\n    fields:\n      - name: a\n        type: string\n"
)


def _project(root: Path, name: str, to: str | None = "sunstone:projects/demo", include: str = "") -> Path:
    project = root / name
    project.mkdir(parents=True)
    publish = f"publish:\n  enabled: true\n  to: {to}\n" if to else ""
    (project / "datasets.yaml").write_text(f"{include}{publish}inputs: []\n{OUTPUT}")
    (project / "out.csv").write_text("a\nx\n")
    return project / "datasets.yaml"


def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _project(tmp_path, "A")
    _project(tmp_path, "B", include="include:\n  - extra/more.yaml\n")
    (tmp_path / "B" / "extra").mkdir()
    (tmp_path / "B" / "extra" / "more.yaml").write_text("inputs: []\n")
    _project(tmp_path, "C", to="gs://bucket/c/")
    _project(tmp_path, "D", to=None)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _changed(*args: str) -> list[str]:
    result = CliRunner().invoke(app, ["package", "changed", *args])
    assert result.exit_code == 0, result.output
    return [line for line in result.stdout.splitlines() if line]


def test_datasets_yaml_change(repo: Path) -> None:
    assert _changed("A/datasets.yaml") == ["A/datasets.yaml"]


def test_lock_file_change(repo: Path) -> None:
    assert _changed("A/datasets.lock.yaml") == ["A/datasets.yaml"]


def test_include_file_change_selects_the_parent(repo: Path) -> None:
    assert _changed("B/extra/more.yaml") == ["B/datasets.yaml"]


def test_unrelated_change_selects_nothing(repo: Path) -> None:
    assert _changed("A/out.csv", "README.md") == []


def test_project_without_publish_is_left_out(repo: Path) -> None:
    assert _changed("D/datasets.yaml") == []


def test_namespaces_only_leaves_out_blob_store_projects(repo: Path) -> None:
    assert _changed("C/datasets.yaml") == ["C/datasets.yaml"]
    assert _changed("--namespaces-only", "C/datasets.yaml", "A/datasets.yaml") == ["A/datasets.yaml"]


def test_file_option_limits_the_candidates(repo: Path) -> None:
    assert _changed("-f", "B/datasets.yaml", "A/datasets.yaml", "B/datasets.lock.yaml") == ["B/datasets.yaml"]


def test_since_uses_the_merge_base(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "B" / "extra" / "more.yaml").write_text("inputs: []\n# edit\n")
    _git(repo, "commit", "-q", "-am", "edit include")
    # A change on main after the branch point is not the feature branch's change.
    _git(repo, "checkout", "-q", "main")
    (repo / "A" / "datasets.yaml").write_text((repo / "A" / "datasets.yaml").read_text() + "# edit\n")
    _git(repo, "commit", "-q", "-am", "edit A on main")
    _git(repo, "checkout", "-q", "feature")

    assert _changed("--since", "main") == ["B/datasets.yaml"]
    assert _changed("--since", base) == ["B/datasets.yaml"]


def test_since_reports_a_deleted_include(repo: Path) -> None:
    _git(repo, "rm", "-q", "B/extra/more.yaml")
    _git(repo, "commit", "-q", "-m", "drop include")
    assert (repo / "B" / "extra" / "more.yaml").resolve() in git_changed_paths(repo, "HEAD~1")
    assert _changed("--since", "HEAD~1") == ["B/datasets.yaml"]


def test_since_unknown_ref_fails(repo: Path) -> None:
    result = CliRunner().invoke(app, ["package", "changed", "--since", "no-such-ref"])
    assert result.exit_code == 2


def test_needs_since_or_paths(repo: Path) -> None:
    assert CliRunner().invoke(app, ["package", "changed"]).exit_code == 2


def test_json_output(repo: Path) -> None:
    result = CliRunner().invoke(app, ["package", "changed", "--json", "B/extra/more.yaml"])
    assert json.loads(result.stdout) == [
        {"file": "B/datasets.yaml", "triggers": ["B/extra/more.yaml"], "destinations": ["sunstone:projects/demo"]}
    ]


def test_unloadable_project_is_kept(repo: Path) -> None:
    (repo / "A" / "datasets.yaml").write_text("include:\n  - missing.yaml\ninputs: []\noutputs: []\n")
    assert _changed("A/datasets.yaml") == ["A/datasets.yaml"]


def test_included_datasets_yaml_is_not_a_project(tmp_path: Path) -> None:
    parent = _project(tmp_path, "P", include="include:\n  - sub/datasets.yaml\n")
    (tmp_path / "P" / "sub").mkdir()
    child = tmp_path / "P" / "sub" / "datasets.yaml"
    child.write_text("inputs: []\n")
    found = affected_projects([parent, child], [child])
    assert [(p.datasets_file, p.triggers) for p in found] == [(parent.resolve(), (child.resolve(),))]


def test_discover_without_git_skips_venv(tmp_path: Path) -> None:
    a = _project(tmp_path, "A")
    _project(tmp_path, ".venv/lib/pkg")
    assert discover_datasets_files(tmp_path) == [a.resolve()]


def test_push_namespaces_only_skips_blob_store(repo: Path) -> None:
    result = CliRunner().invoke(app, ["package", "push", "--namespaces-only", "-f", "C/datasets.yaml"])
    assert result.exit_code == 1
    assert "Skipping gs://bucket/c/" in result.output
    assert "No sunstone: namespace destinations" in result.output
