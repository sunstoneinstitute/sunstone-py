"""Decide whether a project's outputs are stale and re-run its ``project`` script to rebuild them.

Outputs are stale when any local output file is missing, or when an input file, a ``*.py``
file under the project, ``pyproject.toml`` or ``uv.lock`` is newer than the oldest output.
Remote locations (URLs) are ignored. The script is the ``project`` entry in pyproject.toml's
``[project.scripts]``, called with the current interpreter, so the project's dependencies must be
installed in the environment sunstone runs in.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Iterable, Optional

from .changed import _SKIP_DIRS
from .datasets import DatasetsManager

_PROJECT_FILES = ("pyproject.toml", "uv.lock")


class RerunError(Exception):
    """The ``project`` script is not defined, could not be started, or exited non-zero."""


def _local_paths(locations: Iterable[str], project_path: Path) -> list[Path]:
    paths = []
    for loc in locations:
        if "://" in loc or loc.startswith("sunstone:"):
            continue
        p = Path(loc)
        paths.append(p if p.is_absolute() else project_path / p)
    return paths


def _python_files(project_path: Path) -> list[Path]:
    return [
        p
        for p in project_path.rglob("*.py")
        if not any(part in _SKIP_DIRS or part.startswith(".") for part in p.relative_to(project_path).parts[:-1])
    ]


def stale_reason(manager: DatasetsManager, project_path: Path) -> Optional[str]:
    """Why the project's outputs need rebuilding, or None when they are up to date or there are none."""
    outputs = _local_paths((ds.location for ds in manager.get_all_outputs()), project_path)
    if not outputs:
        return None
    missing = [p for p in outputs if not p.exists()]
    if missing:
        return f"missing output {missing[0].relative_to(project_path).as_posix()}"
    oldest = min(p.stat().st_mtime for p in outputs)

    sources = _local_paths((ds.location for ds in manager.get_all_inputs()), project_path)
    sources += _python_files(project_path)
    sources += [project_path / name for name in _PROJECT_FILES]
    for src in sources:
        if src.exists() and src.stat().st_mtime > oldest:
            try:
                shown = src.relative_to(project_path).as_posix()
            except ValueError:
                shown = src.as_posix()
            return f"{shown} is newer than the outputs"
    return None


# Loads the entry point named in argv[1] and exits with its return value, as a console script would.
_RUNNER = (
    "import sys; from importlib.metadata import EntryPoint; "
    "sys.exit(EntryPoint('project', sys.argv[1], 'console_scripts').load()())"
)


def project_script(project_path: Path) -> str:
    """The ``module:function`` value of ``[project.scripts].project`` in the project's pyproject.toml."""
    pyproject = project_path / "pyproject.toml"
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise RerunError(f"cannot read {pyproject}: {e}") from e
    script = data.get("project", {}).get("scripts", {}).get("project")
    if not isinstance(script, str):
        raise RerunError(f"{pyproject} has no [project.scripts] entry named 'project'")
    return script


def run_project(project_path: Path) -> None:
    """Run the project's ``project`` script in ``project_path``, streaming its output."""
    script = project_script(project_path)
    try:
        result = subprocess.run([sys.executable, "-c", _RUNNER, script], cwd=project_path)
    except OSError as e:
        raise RerunError(f"could not run {script}: {e}") from e
    if result.returncode != 0:
        raise RerunError(f"project script {script} exited with status {result.returncode}")
