"""Asset envelope: uniform container across tabular, raster, array, and tile kinds."""

from __future__ import annotations

from enum import Enum


class AssetKind(Enum):
    """Closed enum of asset kinds supported by sunstone.

    New kinds (point clouds, meshes, audio) require adding a variant here.
    Plugin authors cannot extend this enum.
    """

    TABULAR = "tabular"
    RASTER = "raster"
    ARRAY = "array"
    TILES = "tiles"
