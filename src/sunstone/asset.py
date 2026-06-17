"""Asset envelope: uniform container across tabular, raster, array, and tile kinds."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable, Sequence, cast

from .errors import IncompatibleAssetKindError
from .lineage import Metadata

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from .lineage import LineageMetadata


class AssetKind(Enum):
    """Closed enum of asset kinds supported by sunstone.

    New kinds (point clouds, meshes, audio) require adding a variant here.
    Plugin authors cannot extend this enum.
    """

    TABULAR = "tabular"
    RASTER = "raster"
    ARRAY = "array"
    TILES = "tiles"
    BLOB = "blob"
    GEOFEATURES = "geofeatures"


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

    def as_blob(self) -> bytes:
        if self.kind is not AssetKind.BLOB:
            raise IncompatibleAssetKindError(expected=AssetKind.BLOB, actual=self.kind)
        return cast(bytes, self.payload)

    def as_geofeatures(self) -> Any:
        """Return the geopandas GeoDataFrame payload (typed Any: core has no geopandas dep)."""
        if self.kind is not AssetKind.GEOFEATURES:
            raise IncompatibleAssetKindError(expected=AssetKind.GEOFEATURES, actual=self.kind)
        return self.payload

    def derive(
        self,
        payload: Any,
        *,
        slug: str | None = None,
        name: str | None = None,
        kind: "AssetKind | None" = None,
        derived_from: "Iterable[Asset] | None" = None,
        metadata_updates: dict[str, Any] | None = None,
        extras_updates: dict[str, Any] | None = None,
        inherit_custom_properties: bool = False,
    ) -> "Asset":
        """Return a new Asset derived from this one (and optionally additional
        parents via `derived_from`).

        Lineage records `prov:wasDerivedFrom` for each parent. See spec
        `docs/superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md`
        for full semantics.
        """
        import copy as _copy

        from .derive_policies import apply_kind_derive_policy
        from .lineage import Metadata as _Metadata

        # 1. Fork metadata (no inheritance by default; slug/name clear).
        child_meta = _Metadata(
            slug=slug,
            name=name,
            description=None,
            rdf_prefixes=(dict(self.metadata.rdf_prefixes) if self.metadata.rdf_prefixes else None),
        )
        if inherit_custom_properties and self.metadata.custom_properties:
            child_meta.custom_properties = dict(self.metadata.custom_properties)
        if metadata_updates:
            for k, v in metadata_updates.items():
                child_meta[k] = v

        # 2. Build child lineage. Parents default to [self].
        parents = list(derived_from) if derived_from is not None else [self]
        child_meta.lineage = _build_child_lineage(parents)

        # 3. Deep-copy extras then apply extras_updates.
        child_extras: dict[str, Any] = _copy.deepcopy(self.extras)
        if extras_updates:
            child_extras.update(extras_updates)

        child = Asset(
            payload=payload,
            kind=kind or self.kind,
            metadata=child_meta,
            extras=child_extras,
        )

        # 4. Apply per-kind derive policy (e.g., raster profile invalidation).
        return apply_kind_derive_policy(self, child)


def _build_child_lineage(parents: Sequence["Asset"]) -> "LineageMetadata":
    """Compose a child `LineageMetadata` from one or more parent assets.

    For each parent with a slug, record a `DatasetMetadata` snapshot in
    `lineage.sources`. For each parent without a slug, collapse: inherit
    the parent's `lineage.sources` so the upstream-slugged ancestor is the
    one recorded.

    Activity is carried forward from any parent that has one (most recent
    wins on a single-parent chain; multi-parent currently picks the first
    parent's activity — multi-parent activity composition is a follow-up).
    """
    from .lineage import DatasetMetadata, LineageMetadata

    sources: list[DatasetMetadata] = []
    carried_activity = None

    for parent in parents:
        if parent.metadata.slug:
            snapshot = DatasetMetadata(
                name=parent.metadata.name or "",
                slug=parent.metadata.slug,
                location="",
                description=parent.metadata.description,
                dataset_type="input",
                rdf_prefixes=(dict(parent.metadata.rdf_prefixes) if parent.metadata.rdf_prefixes else None),
                custom_properties=(
                    dict(parent.metadata.custom_properties) if parent.metadata.custom_properties else None
                ),
            )
            if snapshot not in sources:
                sources.append(snapshot)
        else:
            for upstream in parent.metadata.lineage.sources:
                if upstream not in sources:
                    sources.append(upstream)

        if carried_activity is None and parent.metadata.lineage.activity is not None:
            carried_activity = parent.metadata.lineage.activity

    return LineageMetadata(sources=sources, activity=carried_activity)
