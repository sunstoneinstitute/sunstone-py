"""Backward-compatible re-export. Prefer `from sunstone.pandas import DataFrame`."""

from .lineage import compute_dataframe_hash  # noqa: F401  (monkeypatch target)
from .pandas.core import DataFrame, _read_tabular_asset  # noqa: F401
