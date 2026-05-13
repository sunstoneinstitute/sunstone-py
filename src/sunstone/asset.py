"""Asset envelope: uniform container across tabular, raster, array, and tile kinds."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from .errors import IncompatibleAssetKindError
from .lineage import Metadata

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


class AssetKind(Enum):
    """Closed enum of asset kinds supported by sunstone.

    New kinds (point clouds, meshes, audio) require adding a variant here.
    Plugin authors cannot extend this enum.
    """

    TABULAR = "tabular"
    RASTER = "raster"
    ARRAY = "array"
    TILES = "tiles"


@dataclass
class Asset:
    """Uniform envelope across tabular, raster, array, and tile data.

    `payload` is the kind-native data (DataFrame, ndarray, dict-of-arrays, tile
    pyramid descriptor). `metadata` is the unified `Metadata` container.
    `extras` carry kind-specific accessory info (rasterio profile, CRS, chunk
    spec) — never copies of the payload.
    """

    payload: Any
    kind: AssetKind
    metadata: Metadata
    extras: dict[str, Any] = field(default_factory=dict)

    # --- Convenience accessors over extras (read-only sugar) ---

    @property
    def profile(self) -> Any:
        return self.extras.get("profile")

    @property
    def crs(self) -> Any:
        return self.extras.get("crs")

    # --- Typed kind accessors ---

    def as_table(self) -> "pd.DataFrame":
        if self.kind is not AssetKind.TABULAR:
            raise IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=self.kind)
        return cast("pd.DataFrame", self.payload)

    def as_raster(self) -> "np.ndarray":
        if self.kind is not AssetKind.RASTER:
            raise IncompatibleAssetKindError(expected=AssetKind.RASTER, actual=self.kind)
        return cast("np.ndarray", self.payload)

    def as_array(self) -> dict[str, "np.ndarray"]:
        if self.kind is not AssetKind.ARRAY:
            raise IncompatibleAssetKindError(expected=AssetKind.ARRAY, actual=self.kind)
        return cast(dict[str, "np.ndarray"], self.payload)

    def as_tiles(self) -> Any:
        if self.kind is not AssetKind.TILES:
            raise IncompatibleAssetKindError(expected=AssetKind.TILES, actual=self.kind)
        return self.payload
