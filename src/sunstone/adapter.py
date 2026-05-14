"""Adapter that normalises DataFrame-returning `FormatHandler`s into the
`Asset`-returning shape used internally."""

from __future__ import annotations

from typing import Any, BinaryIO

from .asset import Asset, AssetKind
from .lineage import Metadata


class TabularDataFrameAdapter:
    """Wraps a legacy-style `FormatHandler` whose `read()` returns
    `pd.DataFrame` and whose `write()` takes one. Returns/accepts `Asset` at the
    outer boundary.

    This is the canonical path for plugins that don't want to migrate to the
    `Asset`-returning protocol; it is **not** deprecated. Plugins that want
    richer control (non-tabular kinds, kind-specific extras, multi-asset
    returns) set `__sunstone_handler_protocol__ = 2` and skip the adapter.
    """

    def __init__(self, handler: object) -> None:
        self._h = handler

    # --- Capability predicates ---

    def supports_native_metadata_extraction(self) -> bool:
        # Legacy tabular handlers don't enrich the Asset beyond what's in
        # df.attrs; treat native extraction as False.
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        # Map onto the legacy single-predicate `supports_metadata()`.
        return bool(getattr(self._h, "supports_metadata", lambda: False)())

    def supports_metadata(self) -> bool:
        # Preserved for callers still using the legacy name.
        return self.supports_sunstone_metadata_embedding()

    # --- Dispatch passthrough ---

    def can_read(self, path: str, format: str | None) -> bool:
        return bool(self._h.can_read(path, format))  # type: ignore[attr-defined]

    def can_write(self, path: str, format: str | None) -> bool:
        return bool(self._h.can_write(path, format))  # type: ignore[attr-defined]

    def supported_kinds(self) -> tuple[AssetKind, ...]:
        return (AssetKind.TABULAR,)

    # --- Read ---

    def read(self, stream: BinaryIO, **kw: Any) -> Asset:
        df = self._h.read(stream, **kw)  # type: ignore[attr-defined]
        embedded = None
        if hasattr(df, "attrs"):
            embedded = df.attrs.pop("sunstone_metadata", None)
        meta = embedded if isinstance(embedded, Metadata) else Metadata()
        return Asset(payload=df, kind=AssetKind.TABULAR, metadata=meta)
