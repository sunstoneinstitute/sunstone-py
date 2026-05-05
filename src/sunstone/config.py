"""Process-wide configuration for sunstone.

Provides a default project path that ``read_csv``/``read_excel``/``read_dataset``
and the ``DataFrame`` constructor fall back to when no explicit ``project_path``
is provided. Backed by ``contextvars.ContextVar`` so it is safe across threads
and async tasks.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_project_path: contextvars.ContextVar[Path | None] = contextvars.ContextVar("sunstone_project_path", default=None)


def set_project_path(path: str | Path) -> Path:
    """Set the default project path used by ``read_*`` functions and ``DataFrame``.

    Subsequent calls without an explicit ``project_path`` argument will resolve
    locations against this path. Returns the resolved path.
    """
    resolved = Path(path).resolve()
    _project_path.set(resolved)
    return resolved


def clear_project_path() -> None:
    """Clear any previously configured default project path."""
    _project_path.set(None)


def get_project_path() -> Path:
    """Return the configured default project path, or the current working directory.

    Functions that accept an optional ``project_path`` argument should call this
    when the caller did not pass one.
    """
    configured = _project_path.get()
    return configured if configured is not None else Path.cwd()


@contextmanager
def use_project_path(path: str | Path) -> Iterator[Path]:
    """Temporarily set the default project path within a ``with`` block."""
    resolved = Path(path).resolve()
    token = _project_path.set(resolved)
    try:
        yield resolved
    finally:
        _project_path.reset(token)
