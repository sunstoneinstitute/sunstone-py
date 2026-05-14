"""Location abstraction for store-based format handlers.

`ResourceLocation` wraps a path/URL that may refer to a single file or a
directory/prefix. It is the input type of `StoreFormatHandler.read()`/`write()`.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import BinaryIO, Iterator


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
