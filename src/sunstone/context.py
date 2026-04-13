"""
Execution context detection for lineage tracking.

Captures information about the execution environment (git state, user,
notebook/script path, timestamp) for inclusion in lineage metadata.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .lineage import Agent


@dataclass(frozen=True)
class ExecutionContext:
    """
    Frozen dataclass capturing the execution environment.

    All fields are optional to support various execution contexts
    (notebooks, scripts, CI/CD, etc.).
    """

    notebook_path: Optional[str] = None
    """Path to the Jupyter notebook, if running in one."""

    script_path: Optional[str] = None
    """Path to the Python script, if running as a script."""

    git_commit: Optional[str] = None
    """Git commit hash (HEAD) at time of execution."""

    git_dirty: Optional[bool] = None
    """Whether the git working tree has uncommitted changes."""

    user: Optional[str] = None
    """User who executed the code."""

    execution_timestamp: Optional[str] = None
    """ISO 8601 timestamp of when the context was captured."""

    def to_dict(self) -> dict:
        """
        Convert to dictionary, omitting fields with None values.

        Returns:
            Dictionary with only non-None field values.
        """
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None}

    def to_agents(self) -> list[Agent]:
        """Return PROV-O Agent objects for this execution context.

        Produces a Person agent for the user (if known) and a SoftwareAgent
        for the sunstone-py library.
        """
        from .lineage import Agent, AgentType

        agents: list[Agent] = []
        if self.user:
            agents.append(Agent(id=self.user, type=AgentType.PERSON))

        # Import version at call time to avoid circular imports
        try:
            from importlib.metadata import version as pkg_version

            sunstone_version = pkg_version("sunstone-py")
        except Exception:
            sunstone_version = None

        agents.append(
            Agent(
                id="sunstone-py",
                type=AgentType.SOFTWARE,
                label="Sunstone Projects Library",
                version=sunstone_version,
            )
        )
        return agents


def _detect_notebook_path() -> Optional[str]:
    """
    Detect if running inside a Jupyter notebook and return its path.

    Uses the optional ipynb-path package. Returns None if not in a notebook
    or if the package is not installed.
    """
    try:
        import ipynb_path  # type: ignore[import-not-found]

        path = ipynb_path.get()
        return str(path) if path else None
    except ImportError:
        return None
    except Exception:
        return None


def _detect_script_path() -> Optional[str]:
    """
    Detect the script path from sys.argv[0].

    Returns None if argv[0] is empty or not a meaningful path
    (e.g., interactive interpreter).
    """
    if sys.argv and sys.argv[0] and sys.argv[0] not in ("", "-", "-c"):
        return sys.argv[0]
    return None


def _detect_git_state() -> tuple[Optional[str], Optional[bool]]:
    """
    Detect git commit hash and dirty state using subprocess.

    Returns:
        Tuple of (commit_hash, is_dirty). Both None if git is unavailable
        or the directory is not a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, None
        commit = result.stdout.strip()

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = bool(status_result.stdout.strip()) if status_result.returncode == 0 else None

        return commit, dirty

    except FileNotFoundError:
        return None, None
    except subprocess.TimeoutExpired:
        return None, None


def _detect_user() -> Optional[str]:
    """
    Detect the current user.

    Tries multiple methods in order: os.getlogin(), getpass.getuser(),
    USER environment variable.
    """
    try:
        return os.getlogin()
    except OSError:
        pass
    try:
        return getpass.getuser()
    except Exception:
        pass
    return os.environ.get("USER")


def detect_execution_context() -> ExecutionContext:
    """
    Detect and capture the current execution context.

    Gathers information about the execution environment including
    git state, user identity, notebook/script path, and timestamp.

    Returns:
        ExecutionContext with all detectable fields populated.
    """
    notebook_path = _detect_notebook_path()
    script_path = _detect_script_path() if notebook_path is None else None
    git_commit, git_dirty = _detect_git_state()
    user = _detect_user()
    timestamp = datetime.now(timezone.utc).isoformat()

    return ExecutionContext(
        notebook_path=notebook_path,
        script_path=script_path,
        git_commit=git_commit,
        git_dirty=git_dirty,
        user=user,
        execution_timestamp=timestamp,
    )
