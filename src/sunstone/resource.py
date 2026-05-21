"""Location abstraction for store-based format handlers.

`ResourceLocation` wraps a path/URL that may refer to a single file or a
directory/prefix. It is the input type of `StoreFormatHandler.read()`/`write()`.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterator, Protocol, runtime_checkable

from .asset import Asset, AssetKind


@dataclass
class ResourceLocation:
    """A path or URL understood by sunstone's URL/store handlers.

    Single-file usage: `open_byte_stream()` for read/write.
    Directory/prefix usage: `is_dir()`, `list()`, `subpath()`, `as_path()` for
    handlers that need random access (SQLite/MBTiles), partition enumeration
    (Hive/Parquet), or chunked reads (Zarr).
    """

    path: str

    def as_path(self) -> pathlib.Path:
        """Return the path as a `pathlib.Path`. For non-local URLs this is the
        URL string parsed as a path; handlers that need URL-aware logic should
        consult `self.path` directly."""
        return pathlib.Path(self.path)

    def is_dir(self) -> bool:
        return self.as_path().is_dir()

    def list(self, glob: str = "*") -> Iterator["ResourceLocation"]:
        base = self.as_path()
        for child in sorted(base.glob(glob)):
            yield ResourceLocation(path=str(child))

    def subpath(self, rel: str) -> "ResourceLocation":
        return ResourceLocation(path=str(self.as_path() / rel))

    def open_byte_stream(self, mode: str = "rb") -> BinaryIO:
        """Open the underlying single-file location as a binary stream.

        For URL-backed locations this should delegate to the registered
        `URLHandler`; the local-path default opens with `builtins.open`."""
        # NB: real implementation will route through the URLHandler registry.
        # For now (local-only), use builtins.open. URL routing lands later.
        return open(self.path, mode)  # type: ignore[return-value]


@runtime_checkable
class StoreFormatHandler(Protocol):
    """Reads/writes formats whose I/O needs location/store access rather than a
    single byte stream (XYZ tiles, MBTiles, Zarr, partitioned Parquet, ...).

    Handlers MUST declare `__sunstone_handler_protocol__ = 2`.
    """

    __sunstone_handler_protocol__: int

    def supports_native_metadata_extraction(self) -> bool: ...
    def supports_sunstone_metadata_embedding(self) -> bool: ...

    def can_read_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def read(self, location: ResourceLocation, **kwargs: Any) -> Asset: ...

    def can_write_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def write(self, asset: Asset, location: ResourceLocation, **kwargs: Any) -> None: ...

    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
