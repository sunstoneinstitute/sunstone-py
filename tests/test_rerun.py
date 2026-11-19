"""Tests for sunstone.rerun and `sunstone package build --rerun`."""

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sunstone.rerun as rerun_mod
from sunstone.cli import app
from sunstone.datasets import DatasetsManager

OUTPUT = "outputs/current_un_member_states.csv"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    src = Path(__file__).parent / "testdata" / "UNMembersProject"
    dst = tmp_path / "project"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    # Make every file old, then the output newest: up to date.
    for p in dst.rglob("*"):
        if p.is_file():
            os.utime(p, (1_000_000, 1_000_000))
    out = dst / OUTPUT
    out.parent.mkdir(exist_ok=True)
    out.write_text("Country,Code\nTest,TST\n")
    os.utime(out, (2_000_000, 2_000_000))
    return dst


def _reason(project: Path):
    return rerun_mod.stale_reason(DatasetsManager(project), project)


def test_up_to_date(project: Path) -> None:
    assert _reason(project) is None


def test_missing_output(project: Path) -> None:
    (project / OUTPUT).unlink()
    assert "missing output" in _reason(project)


@pytest.mark.parametrize(
    "name", ["create_un_members_dataset.py", "pyproject.toml", "uv.lock", "inputs/official_un_member_states_raw.csv"]
)
def test_newer_source(project: Path, name: str) -> None:
    os.utime(project / name, (3_000_000, 3_000_000))
    assert _reason(project) == f"{name} is newer than the outputs"


def test_venv_python_ignored(project: Path) -> None:
    venv = project / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "x.py").write_text("")
    os.utime(venv / "x.py", (3_000_000, 3_000_000))
    assert _reason(project) is None


def _build(project: Path, *flags: str):
    return CliRunner().invoke(
        app, ["package", "build", "-f", str(project / "datasets.yaml"), "-o", str(project / "dp.json"), *flags]
    )


def test_build_reruns_when_stale(project: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(rerun_mod, "run_project", lambda p: calls.append(p))
    os.utime(project / "uv.lock", (3_000_000, 3_000_000))
    result = _build(project, "--rerun")
    assert result.exit_code == 0, result.output
    assert calls == [project.resolve()]
    assert "uv.lock is newer than the outputs" in result.output


def test_build_skips_when_up_to_date(project: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(rerun_mod, "run_project", lambda p: calls.append(p))
    assert _build(project, "--rerun").exit_code == 0
    assert calls == []


def test_build_defaults_to_no_rerun(project: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(rerun_mod, "run_project", lambda p: calls.append(p))
    os.utime(project / "uv.lock", (3_000_000, 3_000_000))
    assert _build(project).exit_code == 0
    assert calls == []


def test_build_fails_when_project_fails(project: Path, monkeypatch) -> None:
    def fail(p):
        raise rerun_mod.RerunError("project script x:main exited with status 1")

    monkeypatch.setattr(rerun_mod, "run_project", fail)
    (project / OUTPUT).unlink()
    result = _build(project, "--rerun")
    assert result.exit_code == 1
    assert "exited with status 1" in result.output


def _script_project(tmp_path: Path, body: str, scripts: str = '[project.scripts]\nproject = "build:main"\n') -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "p"\n' + scripts)
    (tmp_path / "build.py").write_text(body)
    return tmp_path


def test_run_project_calls_script_in_project_dir(tmp_path: Path) -> None:
    proj = _script_project(tmp_path, "from pathlib import Path\ndef main():\n    Path('ran').write_text('ok')\n")
    rerun_mod.run_project(proj)
    assert (proj / "ran").read_text() == "ok"


def test_run_project_nonzero_exit(tmp_path: Path) -> None:
    proj = _script_project(tmp_path, "def main():\n    return 3\n")
    with pytest.raises(rerun_mod.RerunError, match="exited with status 3"):
        rerun_mod.run_project(proj)


def test_run_project_without_script(tmp_path: Path) -> None:
    proj = _script_project(tmp_path, "", scripts="")
    with pytest.raises(rerun_mod.RerunError, match="no \\[project.scripts\\] entry named 'project'"):
        rerun_mod.run_project(proj)
