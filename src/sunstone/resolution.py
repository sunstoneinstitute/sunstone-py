"""Shared resolution of a positional path-or-slug to a registered dataset.

This module is intentionally dependency-light: it imports only the standard
library and ``sunstone.exceptions``. It must NOT import a dataframe engine
(pandas/polars/geopandas), so importing ``sunstone`` never pulls one in. The
``DatasetsManager`` is always passed in by the caller (duck-typed) rather than
imported at module load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


def looks_like_slug(value: str) -> bool:
    """Return True if ``value`` should be treated as a dataset slug rather than
    a filesystem path. A slug has no path separators and no file extension."""
    return "/" not in value and "\\" not in value and not Path(value).suffix
