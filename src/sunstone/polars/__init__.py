"""Polars-compatible API for Sunstone DataFrames (eager mode, Spec 1).

Mirrors `sunstone.pandas`. A `DataFrame` here is a thin facade over an
`AssetKind.TABULAR` Asset whose payload is a `polars.DataFrame`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    import polars as _pl
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
        # Import the submodule directly (not via ``from . import io``) so we don't
        # consult this package's ``__getattr__`` for the name ``io`` — the fallback
        # below would otherwise shadow our submodule with the real ``polars.io``.
        import importlib

        _io = importlib.import_module(f"{__name__}.io")
        return getattr(_io, name)
    # Skip dunders so we don't forward attribute probes (``__all__``, ``__path__``,
    # etc.) to polars.
    if not name.startswith("_"):
        import importlib
        import importlib.util

        # One of our own submodules (e.g. ``io``): import and return it so polars'
        # same-named module can never shadow it — the hazard the reader branch guards.
        if importlib.util.find_spec(f"{__name__}.{name}") is not None:
            return importlib.import_module(f"{__name__}.{name}")
        # Otherwise fall back to the real polars library for any symbol we don't own.
        try:
            return getattr(_pl, name)
        except AttributeError:
            pass
    raise AttributeError(f"module 'sunstone.polars' has no attribute {name!r}")
