"""Polars-compatible API for Sunstone DataFrames (eager mode, Spec 1).

Mirrors `sunstone.pandas`. A `DataFrame` here is a thin facade over an
`AssetKind.TABULAR` Asset whose payload is a `polars.DataFrame`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    import polars as _pl  # noqa: F401
except ImportError as e:  # pragma: no cover - exercised via subprocess in tests
    raise ImportError(
        "Polars support requires the [polars] extra. Install with: pip install 'sunstone-py[polars]'"
    ) from e

# Pass-through polars symbols (re-export with the explicit `X as X` form).
from polars import (
    Int64 as Int64,
    Series as Series,
    col as col,
    lit as lit,
    when as when,
)

if TYPE_CHECKING:
    from .core import DataFrame

__all__ = [
    "read_csv",
    "read_parquet",
    "read_json",
    "read_dataset",
    "DataFrame",
    "Series",
    "col",
    "lit",
    "when",
    "Int64",
]


def __getattr__(name: str) -> Any:
    """Lazy-load facade symbols (keeps the import light)."""
    if name == "DataFrame":
        from .core import DataFrame as _DataFrame

        return _DataFrame
    if name in ("read_csv", "read_parquet", "read_json", "read_dataset"):
        from . import io as _io

        return getattr(_io, name)
    raise AttributeError(f"module 'sunstone.polars' has no attribute {name!r}")
