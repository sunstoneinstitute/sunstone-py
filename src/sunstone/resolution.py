"""Shared resolution of a positional path-or-slug to a registered dataset.

This module is intentionally dependency-light: it imports only the standard
library and ``sunstone.exceptions``. It must NOT import a dataframe engine
(pandas/polars/geopandas), so importing ``sunstone`` never pulls one in. The
``DatasetsManager`` is always passed in by the caller (duck-typed) rather than
imported at module load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .exceptions import SlugConflictError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .datasets import DatasetMetadata, DatasetsManager


def looks_like_slug(value: str) -> bool:
    """Return True if ``value`` should be treated as a dataset slug rather than
    a filesystem path. A slug has no path separators and no file extension."""
    return "/" not in value and "\\" not in value and not Path(value).suffix


def resolve_to_dataset(
    value: str,
    manager: "DatasetsManager",
    dataset_type: Optional[str] = None,
) -> Optional["DatasetMetadata"]:
    """Resolve a positional path-or-slug to a registered dataset, or ``None``.

    If ``value`` looks like a slug it is looked up by slug; otherwise it is
    treated as a filesystem path and matched (cwd-relative, symlink-safe) by
    :meth:`DatasetsManager.find_dataset_by_location`.
    """
    value = str(value)
    if looks_like_slug(value):
        return manager.find_dataset_by_slug(value, dataset_type)
    return manager.find_dataset_by_location(value, dataset_type)


def check_slug_conflict(
    path_dataset: Optional["DatasetMetadata"],
    explicit_slug: Optional[str],
) -> None:
    """Raise :class:`SlugConflictError` if an explicit ``slug=`` disagrees with
    the dataset the positional path already resolves to. No-op when either is
    absent or they agree."""
    if path_dataset is not None and explicit_slug is not None and path_dataset.slug != explicit_slug:
        raise SlugConflictError(
            f"slug={explicit_slug!r} conflicts with the dataset already "
            f"registered at this path (slug={path_dataset.slug!r}). "
            f"Remove the slug= argument or write to a different path."
        )


def portable_location(location: str, project_path: Path) -> str:
    """Return a portable, project-relative POSIX location for storage in
    datasets.yaml. URLs are returned unchanged. Paths inside ``project_path``
    become forward-slash relative paths (Windows-safe); paths outside become
    absolute POSIX paths."""
    if "://" in location:
        return location
    abs_path = Path(location).expanduser().resolve()
    try:
        return abs_path.relative_to(project_path).as_posix()
    except ValueError:
        return abs_path.as_posix()
