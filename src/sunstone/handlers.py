"""
Internal plugin implementations for built-in formats and HTTP fetching.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


# Extension -> format string mapping
_EXTENSION_MAP: dict[str, str] = {
    ".csv": "csv",
    ".json": "json",
    ".xlsx": "excel",
    ".xls": "excel",
    ".parquet": "parquet",
    ".tsv": "tsv",
    ".txt": "tsv",
}

# Format string -> pandas reader function
_READER_MAP: dict[str, Callable[..., pd.DataFrame]] = {
    "csv": pd.read_csv,
    "json": pd.read_json,
    "excel": pd.read_excel,
    "parquet": pd.read_parquet,
    "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
}

# Format string -> pandas writer method name on DataFrame
_WRITER_MAP: dict[str, str] = {
    "csv": "to_csv",
}


class BuiltinFormatHandler:
    """Handles CSV, JSON, Excel, Parquet, and TSV formats using pandas."""

    def _resolve_format(self, path: Path, format: str | None) -> str | None:
        """Resolve a format string from explicit format or file extension."""
        if format is not None:
            return format if format in _READER_MAP or format in _WRITER_MAP else None
        return _EXTENSION_MAP.get(path.suffix.lower())

    def can_read(self, path: Path, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _READER_MAP

    def read(self, path: Path, **kwargs: object) -> pd.DataFrame:
        fmt = self._resolve_format(path, None)
        reader = _READER_MAP[fmt]  # type: ignore[index]
        return reader(path, **kwargs)

    def can_write(self, path: Path, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _WRITER_MAP

    def write(self, df: pd.DataFrame, path: Path, **kwargs: object) -> None:
        fmt = self._resolve_format(path, None)
        writer = getattr(df, _WRITER_MAP[fmt])  # type: ignore[index]
        writer(path, **kwargs)
