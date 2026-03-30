"""
Plugin system for extending sunstone with custom auth, URL handlers, and format handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from .lineage import DatasetMetadata


@runtime_checkable
class AuthProvider(Protocol):
    """Provides authentication for HTTP requests."""

    def authenticate(self, url: str, headers: dict[str, str], dataset: DatasetMetadata) -> dict[str, str]:
        """Return modified headers dict. Called before every HTTP fetch."""
        ...


@runtime_checkable
class URLHandler(Protocol):
    """Resolves custom URL schemes to local file paths."""

    def can_handle(self, url: str) -> bool:
        """Return True if this handler can resolve the given URL."""
        ...

    def fetch(self, url: str, dest: Path) -> Path:
        """Download/resolve URL to a local file. Return path to the file."""
        ...


@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats not built into sunstone."""

    def can_read(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can read the given file/format."""
        ...

    def read(self, path: Path, **kwargs: object) -> pd.DataFrame:
        """Read file into a pandas DataFrame."""
        ...

    def can_write(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can write the given file/format."""
        ...

    def write(self, df: pd.DataFrame, path: Path, **kwargs: object) -> None:
        """Write DataFrame to file."""
        ...
