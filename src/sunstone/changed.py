"""``sunstone package changed``: which datasets.yaml files a set of changed paths affects.

A project is affected when its ``datasets.yaml``, the ``datasets.lock.yaml`` beside it, or a
file it names under ``include:`` changed. An include file does not name its parent, so the
parents are found by reading every candidate ``datasets.yaml``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ruamel.yaml import YAML

from .config import DATASETS_FILE, LOCK_FILE

_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__"})


class ChangedError(Exception):
    """The changed paths or the candidate projects could not be determined."""


@dataclass(frozen=True)
class AffectedProject:
    """A datasets.yaml that must be rebuilt and pushed, and the changed files that say so."""

    datasets_file: Path
    triggers: tuple[Path, ...]


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout
    except OSError as e:
        raise ChangedError(f"git is not available: {e}") from e
    except subprocess.CalledProcessError as e:
        raise ChangedError(f"git {' '.join(args)} failed: {e.stderr.strip()}") from e


def git_changed_paths(root: Path, since: str) -> list[Path]:
    """Absolute paths changed between ``since`` and HEAD, deleted and renamed-from paths included.

    The comparison starts at the merge base of ``since`` and HEAD, so commits that landed on
    ``since`` after the branch point do not count. Without a merge base (a shallow clone, or a
    force push that dropped ``since`` from history) the two trees are compared directly.
    """
    top = Path(_git(root, "rev-parse", "--show-toplevel").strip())
    _git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    try:
        base = _git(root, "merge-base", since, "HEAD").strip()
    except ChangedError:
        base = since
    out = _git(root, "diff", "--name-only", "--no-renames", "-z", base, "HEAD")
    return [(top / p).resolve() for p in out.split("\0") if p]


def discover_datasets_files(root: Path) -> list[Path]:
    """Every ``datasets.yaml`` under ``root``: the tracked ones in a git checkout, else a directory walk."""
    root = root.resolve()
    try:
        out = _git(root, "ls-files", "-z", "--", DATASETS_FILE, f"**/{DATASETS_FILE}")
        found = [root / p for p in out.split("\0") if p]
    except ChangedError:
        found = [p for p in root.rglob(DATASETS_FILE) if not _SKIP_DIRS.intersection(p.relative_to(root).parts[:-1])]
    return sorted(p.resolve() for p in found if p.is_file())


def include_files(datasets_file: Path) -> list[Path]:
    """Resolved ``include:`` targets of a datasets.yaml. Empty when the file cannot be read."""
    try:
        with open(datasets_file, "r") as f:
            data = YAML(typ="safe").load(f)
    except Exception:
        return []
    includes = data.get("include") if isinstance(data, dict) else None
    if not isinstance(includes, list):
        return []
    return [(datasets_file.parent / str(rel)).resolve() for rel in includes if isinstance(rel, str)]


def affected_projects(candidates: Sequence[Path], changed: Iterable[Path]) -> list[AffectedProject]:
    """The candidates that ``changed`` affects, in candidate order.

    A candidate that another candidate includes is part of that project, not a project of its own.
    """
    changed_set = {Path(p).resolve() for p in changed}
    files = [Path(c).resolve() for c in candidates]
    includes = {f: include_files(f) for f in files}
    included = {inc for incs in includes.values() for inc in incs}

    result: list[AffectedProject] = []
    for datasets_file in files:
        if datasets_file in included:
            continue
        watched = [datasets_file, datasets_file.parent / LOCK_FILE, *includes[datasets_file]]
        triggers = tuple(p for p in watched if p in changed_set)
        if triggers:
            result.append(AffectedProject(datasets_file, triggers))
    return result
