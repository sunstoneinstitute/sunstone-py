# Generic Format Handler and Asset Envelope Design

**Date:** 2026-05-12
**Status:** Approved (all decisions resolved 2026-05-13)
**Supersedes:** Portions of `2026-04-03-stream-based-plugin-io-design.md` (the `FormatHandler` protocol section).
**Related:** `2026-04-07-dataframe-metadata-design.md` (metadata model that the `Asset` envelope generalises). See `2026-05-12-asset-envelope-open-decisions.md` for the design-decision audit trail.

## Problem

The current `FormatHandler` protocol is rigidly tabular:

```python
def read(self, stream: BinaryIO, **kwargs) -> pd.DataFrame: ...
def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs) -> None: ...
```

This forecloses on three classes of data that data scientists want sunstone to help them
manage with the same lineage and RDF-metadata story that DataFrames enjoy today:

1. **Rasters** — GeoTIFF, Cloud-Optimized GeoTIFF, NetCDF, HDF5. Native shape is an
   `ndarray` with georeferencing metadata (CRS, transform, nodata).
2. **Dense array bundles** — NumPy `.npz`, Zarr stores, embeddings on disk. Native shape
   is a dict-of-arrays or a chunked array.
3. **Tile pyramids** — XYZ tile directories, MBTiles, vector tiles. Native shape is a
   pyramid descriptor plus the underlying chunked store.

None of these are pandas DataFrames. Forcing them through the current protocol would
either coerce them into something tabular (lossy and silly) or require a parallel,
duplicated plugin system per kind.

The library also has a longer-term ambition — discovering datasets by language ("Sentinel-2
NDVI rasters over East Africa, 2024") — that depends on **every kind of dataset carrying
the same RDF-capable metadata bag**. Today, only DataFrames do.

## Goals

- One plugin protocol that supports tabular, raster, array, tile, and future kinds of
  data without per-kind sharding of the entry-point API.
- Uniform metadata: every readable artefact carries the same `Metadata` container
  (the unified container in `sunstone.lineage` — lineage, slug/name, description,
  `rdf_prefixes`, `custom_properties`/RDF triples, `field_metadata`,
  `component_metadata`, `identity`) regardless of payload type. `DatasetMetadata`
  remains the YAML-row class; it is *not* what `Asset.metadata` holds.
- Explicit, lightweight provenance: deriving a new asset from an existing one is a single
  method call that records `prov:wasDerivedFrom` automatically and supports
  multi-parent derivation.
- **Zero backwards-compatibility break for plugin authors.** Plugins returning
  `pd.DataFrame` (with optional `df.attrs["sunstone_metadata"]`) keep working
  unchanged via a normalising adapter; plugins returning `Asset` get richer control.
  Both paths are first-class and supported indefinitely.
- The existing DataFrame ergonomics (`sunstone.DataFrame` wrapper with `.metadata`,
  pandas-compatible operations) remain unchanged for tabular data.

## Non-Goals

- Implementing GeoTIFF, NPZ, or tile handlers. Each is a separate plan that builds on
  this protocol.
- Building the natural-language discovery layer. Downstream work; this design provides
  the metadata substrate.
- Designing the per-kind required RDF shape (DCAT/PROV/GeoSPARQL/SOSA mappings,
  unit/QUDT bridging). Tracked as a **gating dependency** for non-tabular handlers in
  a follow-up spec — it must land before the first GeoTIFF handler.
- Forcing every kind through a single concrete container class. Plugin authors choose
  their native payload type; the envelope is what's uniform, not the payload.
- Replacing the `sunstone.DataFrame` wrapper. It stays as the user-facing facade for
  tabular work; internally it becomes a thin facade over an `Asset`.

## Design Decisions

### D1. Single generic protocol; payload type is `Any`

`FormatHandler.read()` returns a sunstone-owned envelope (`Asset`) with an `Any`-typed
`payload` field. Plugins decide the concrete payload type (DataFrame, `numpy.ndarray`,
`dict[str, np.ndarray]`, a tile-pyramid descriptor object, ...).

For formats whose I/O is not a single byte-stream (XYZ tile directories, MBTiles,
Zarr stores, partitioned Parquet, object-store prefixes), a parallel
`StoreFormatHandler` protocol takes a `ResourceLocation` instead of a `BinaryIO`. See
the Protocol Definitions section.

### D2. Asset envelope is the uniform container

```python
class AssetKind(Enum):
    TABULAR = "tabular"
    RASTER  = "raster"
    ARRAY   = "array"
    TILES   = "tiles"

@dataclass
class Asset:
    payload: Any
    kind: AssetKind
    metadata: Metadata              # the unified container from sunstone.lineage
    extras: dict[str, Any]          # kind-specific accessories (profile, CRS, chunks, ...)
```

`kind` is a **closed enum**. Adding a new kind requires extending `AssetKind` upstream
rather than letting third-party plugins invent strings. This makes dispatch,
validation, and the typed accessors below (`as_table()`, `as_raster()`, ...) total over
the kind space.

Kind-specific detail (rasterio profile, Zarr chunk spec, tile zoom range) lives in
`extras` to keep the envelope shape stable. **Payload is the data, for every kind.**
`extras` carry metadata *about* the data, never copies of it.

**Metadata sourcing convention.** The `metadata` field is always populated, but
*who* populates it is layered:

- Handlers extract whatever embedded metadata the file format carries and return it on
  the `Asset` (subject to their `supports_native_metadata_extraction()` /
  `supports_sunstone_metadata_embedding()` answers — see D6). If the format has no
  embedded metadata, handlers return an `Asset` with a minimal `Metadata` (slug/name
  both `None`; lineage default-initialised; rdf_prefixes/custom_properties left
  empty). Asset kind is carried on `Asset.kind`, not on the metadata.
- The calling layer (`ss.read`, `read_csv`, etc.) merges this with metadata resolved
  from `datasets.yaml`, with `datasets.yaml` taking precedence on conflicts. Merge
  order: defaults → `datasets.yaml` row → embedded file metadata → user mutations
  after read.
- After merge, the calling layer reassigns `asset.metadata` to the merged instance.

Plugin authors don't need to know about `datasets.yaml`. They populate what the file
itself tells them.

**Tabular ownership.** `sunstone.DataFrame` becomes a thin facade over an `Asset`:
`df.data` returns `asset.as_table()`; `df.metadata` returns `asset.metadata` (same
instance, not a copy). User mutations to `df.metadata.description` flow into
`datasets.yaml` on write as before.

### D3. Convenience accessors over `extras`

Common kind-specific fields surface as read-only properties on `Asset` that delegate to
`extras`. They exist because users computing on assets shouldn't have to remember the
`extras` key naming for each kind, and writers need a uniform way to validate before
serialising.

- **`asset.profile` → `extras.get("profile")` (raster).** A rasterio-style profile dict
  (`dtype`, `count`, `transform`, `crs`, `nodata`, `compression`, ...) — everything a
  GeoTIFF writer needs to round-trip a raster. Users computing band math read it to
  preserve geo-referencing; writers inspect it to validate that the payload's shape
  and dtype agree with what they're about to serialise.
- **`asset.crs` → `extras.get("crs")` (raster, tiles).** Coordinate reference system,
  exposed uniformly across kinds so cross-kind code (reprojection helpers, discovery
  queries like "what's in EPSG:4326?", footprint computation) doesn't branch on `kind`.

These are read-only sugar over `extras`. Plugin authors populate `extras["profile"]`,
`extras["crs"]` as appropriate. Note: there is no `asset.arrays` accessor — for
`AssetKind.ARRAY`, the payload *is* the `dict[str, ndarray]`, accessed via
`asset.as_array()`. Duplicating it in `extras` would invite unnecessary copies.

### D3b. Typed kind accessors

Asset payloads are statically `Any`, but most downstream code knows what kind it's
operating on. To avoid `cast(...)` litter and to fail loudly on kind mismatch, `Asset`
exposes typed accessors:

```python
asset.as_table()   -> pd.DataFrame                # raises IncompatibleAssetKindError if kind != TABULAR
asset.as_raster()  -> np.ndarray                  # raises if kind != RASTER
asset.as_array()   -> dict[str, np.ndarray]       # raises if kind != ARRAY
asset.as_tiles()   -> TilePyramid                 # raises if kind != TILES
```

Each accessor checks `self.kind` and either returns `self.payload` typed appropriately
or raises `IncompatibleAssetKindError`. Pure runtime checks plus type-checker hints —
no payload transformation.

### D4. `Asset.derive()` is the canonical provenance event

```python
def derive(
    self,
    payload: Any,
    *,
    slug: str | None = None,
    name: str | None = None,
    kind: AssetKind | None = None,
    derived_from: Iterable["Asset"] | None = None,
    metadata_updates: dict[str, Any] | None = None,
    extras_updates: dict[str, Any] | None = None,
    inherit_custom_properties: bool = False,
) -> "Asset":
    ...
```

Calling `.derive()` returns a new `Asset` that:

- Carries the new `payload`.
- Inherits `kind` and **deep-copies** `extras` (no shared mutable state with the
  parent), then applies `extras_updates`. The relevant `KindDerivePolicy` then runs
  to invalidate stale kind-specific fields — e.g., the `RASTER` policy drops
  `profile["count"]`, `profile["dtype"]`, `profile["nodata"]` when the new payload's
  shape or dtype differs from the parent's. Default policy is a no-op.
- Forks `metadata`:
  - **`slug` clears to `None`** unless explicitly provided. Writers must then require
    a non-None slug — matching today's `df.to_csv(slug=...)` contract.
  - **`name` clears to `None`** unless explicitly provided. (A derived NDVI asset
    shouldn't silently carry the parent's "Sentinel-2 SR" name.)
  - **`custom_properties` do NOT inherit by default.** Semantic claims about data
    (`sosa:observedProperty = "surface-reflectance"`) are not provenance; inheriting
    them onto a derivative would make false RDF statements. Opt in with
    `inherit_custom_properties=True` for cases where the claims genuinely carry
    forward (e.g., a re-projection that preserves the observed property).
    `metadata_updates` is the explicit per-key override channel.
  - `description`, `rdf_prefixes`, `identity`, and `field_metadata` /
    `component_metadata` follow the same rule: not inherited by default; specify in
    `metadata_updates`.
- **Records `prov:wasDerivedFrom` for each parent.** `derived_from` defaults to
  `[self]` (single-parent derive); pass an iterable to record multi-parent lineage for
  mosaics, joins, stacks, etc.

**Unsaved parents (transient intermediates).** When a parent in `derived_from` has no
slug (it was a transient intermediate, e.g., `B` in a chain `A → B → C`), `derive()`
collapses past it:

- `child.lineage.sources` inherits `parent.lineage.sources` (i.e., the slugged
  upstream `A`, not the slugless `B`). This keeps `sources` clean and identifiable —
  no blank-node noise.
- `child.lineage.activity` chains: the new activity record is appended to the parent's
  activity chain rather than replacing it. The full op chain `A → B → C` is preserved
  in `lineage.activity`, just not in `lineage.sources`.

This gives discoverable identity (`sources` are real, slugged datasets) and complete
operation history (`activity` captures every transform) without forcing transients to
materialise to disk.

### D5. Dispatch entry points stay flat

Top-level reader/writer functions in `sunstone` autodispatch:

```python
asset = sunstone.read("inputs/sentinel2_2024_07.tif")    # returns Asset
sunstone.write(asset, "outputs/ndvi_202407.tif")
```

**Dispatch order:**

1. **`datasets.yaml` `format` field** is the primary signal when the path resolves to
   a registered dataset entry. This handles ambiguous cases that file extensions
   can't disambiguate (Zarr stores, partitioned Parquet directories, XYZ tile
   pyramids, cloud prefixes without extensions).
2. **Store-vs-stream classification** by the resolved `ResourceLocation` —
   directory/prefix → `StoreFormatHandler`; single file → `FormatHandler`.
3. **Extension-based fallback** for ad-hoc reads outside of `datasets.yaml`.
4. **Explicit `kind=` / `format=` parameter** on `ss.read` as a final override.

The kind-specific sugar (`sunstone.pandas.read_csv`, the DataFrame wrapper) remains
in place for tabular work and internally produces an `Asset` of
`kind=AssetKind.TABULAR`. Users who never touch non-tabular data never see the
envelope.

### D6. Backwards compatibility: adapter-as-default, no breaking change

The `Asset` wrapper is essentially free at runtime — a dataclass holding four
references, constructed once per read. There is no performance reason to break the
existing plugin contract.

**Both plugin styles are first-class and supported indefinitely:**

1. **DataFrame-returning plugins** (today's CSV, JSON, Excel, TSV, Parquet, plus all
   external plugins on `sunstone.plugins`). Implement
   `read(stream) -> pd.DataFrame`; optionally embed sunstone metadata via
   `df.attrs["sunstone_metadata"]` (the existing Parquet pattern). The registry
   normalises into an `Asset` via `LegacyFormatHandlerAdapter` (renamed to
   `TabularDataFrameAdapter` to drop the "legacy" framing). No deprecation timeline.
2. **Asset-returning plugins** (new). Implement `read(stream) -> Asset`. Required for
   non-tabular kinds; optional for tabular plugins that want richer control over
   embedded metadata, kind-specific extras, or multi-asset returns.

**Capability split for embedded metadata.** The old `supports_metadata()` predicate
conflates two distinct capabilities. New protocol:

- `supports_native_metadata_extraction()` — handler can extract format-native
  metadata (CRS/transform/band tags from GeoTIFF, CF dimensions from NetCDF, schema
  from Parquet, EXIF from PNG). Most read handlers say `True`; the question is what
  they choose to populate on the `Asset`.
- `supports_sunstone_metadata_embedding()` — handler can round-trip a full Sunstone
  `Metadata` blob (slug, RDF triples, lineage) into and out of the file format.
  Parquet says `True`; PNG says `False` (no clean embedding target). Read paths
  consult the first; write paths consult the second.

Detection between styles uses an explicit capability marker (a class-level
attribute, e.g., `__sunstone_handler_protocol__ = 2`), not return-annotation
inspection. Plugins set the attribute when they migrate; absence = DataFrame-style.

## Protocol Definitions

### FormatHandler (stream-based)

```python
from typing import Any, BinaryIO, Protocol, runtime_checkable

@runtime_checkable
class FormatHandler(Protocol):
    """Handler for formats whose I/O is a single byte stream."""

    __sunstone_handler_protocol__: int = 2  # capability marker

    def supports_native_metadata_extraction(self) -> bool: ...
    def supports_sunstone_metadata_embedding(self) -> bool: ...

    def can_read(self, path: str, format: str | None) -> bool: ...

    def read(self, stream: BinaryIO, **kwargs: Any) -> "Asset":
        """Read stream into an Asset. The Asset's `kind` is set by the handler."""
        ...

    def can_write(self, path: str, format: str | None) -> bool: ...

    def write(self, asset: "Asset", stream: BinaryIO, **kwargs: Any) -> None: ...

    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
```

### StoreFormatHandler (location-based)

```python
@dataclass
class ResourceLocation:
    """A path, directory, or URL prefix understood by URLHandler.

    Single-file: backed by `open_byte_stream()`.
    Directory/prefix: backed by `list()`, `subpath()`, `as_path()` for handlers
    that need random access (SQLite/MBTiles), partition enumeration (Hive/Parquet),
    or chunked reads (Zarr).
    """
    path: str
    def as_path(self) -> pathlib.Path: ...
    def is_dir(self) -> bool: ...
    def list(self, glob: str = "*") -> Iterator["ResourceLocation"]: ...
    def subpath(self, rel: str) -> "ResourceLocation": ...
    def open_byte_stream(self, mode: str = "rb") -> BinaryIO: ...


@runtime_checkable
class StoreFormatHandler(Protocol):
    """Handler for formats whose I/O needs store/location access, not a byte stream.

    Examples: MBTiles (single file but random SQL access), XYZ tile directories,
    Zarr stores, partitioned Parquet, object-store prefixes.
    """

    __sunstone_handler_protocol__: int = 2

    def supports_native_metadata_extraction(self) -> bool: ...
    def supports_sunstone_metadata_embedding(self) -> bool: ...

    def can_read_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def read(self, location: ResourceLocation, **kwargs: Any) -> "Asset": ...

    def can_write_store(self, location: ResourceLocation, format: str | None) -> bool: ...

    def write(self, asset: "Asset", location: ResourceLocation, **kwargs: Any) -> None: ...

    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
```

### Asset

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, TYPE_CHECKING

from sunstone.lineage import Metadata

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


class AssetKind(Enum):
    TABULAR = "tabular"
    RASTER  = "raster"
    ARRAY   = "array"
    TILES   = "tiles"


@dataclass
class Asset:
    payload: Any
    kind: AssetKind
    metadata: Metadata
    extras: dict[str, Any] = field(default_factory=dict)

    # Convenience accessors over extras
    @property
    def profile(self) -> Any: return self.extras.get("profile")
    @property
    def crs(self) -> Any: return self.extras.get("crs")

    # Typed kind accessors — raise IncompatibleAssetKindError on mismatch
    def as_table(self) -> "pd.DataFrame":
        if self.kind is not AssetKind.TABULAR:
            raise IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=self.kind)
        return self.payload
    def as_raster(self) -> "np.ndarray":
        if self.kind is not AssetKind.RASTER:
            raise IncompatibleAssetKindError(expected=AssetKind.RASTER, actual=self.kind)
        return self.payload
    def as_array(self) -> dict[str, "np.ndarray"]:
        if self.kind is not AssetKind.ARRAY:
            raise IncompatibleAssetKindError(expected=AssetKind.ARRAY, actual=self.kind)
        return self.payload
    def as_tiles(self) -> Any:
        if self.kind is not AssetKind.TILES:
            raise IncompatibleAssetKindError(expected=AssetKind.TILES, actual=self.kind)
        return self.payload

    def derive(
        self,
        payload: Any,
        *,
        slug: str | None = None,
        name: str | None = None,
        kind: AssetKind | None = None,
        derived_from: Iterable["Asset"] | None = None,
        metadata_updates: dict[str, Any] | None = None,
        extras_updates: dict[str, Any] | None = None,
        inherit_custom_properties: bool = False,
    ) -> "Asset": ...
```

### KindDerivePolicy

```python
class KindDerivePolicy(Protocol):
    """Hook called from Asset.derive() to invalidate stale kind-specific extras
    when the payload changes shape, dtype, or other kind-relevant invariants."""

    def __call__(
        self,
        parent: Asset,
        child: Asset,  # already-constructed, extras inherited+updated, before return
    ) -> Asset: ...


# Registry mapping kind → policy. Plugins may register policies for new kinds.
KIND_DERIVE_POLICIES: dict[AssetKind, KindDerivePolicy] = {
    AssetKind.RASTER: _raster_invalidate_stale_profile,
    # AssetKind.ARRAY: default no-op
    # AssetKind.TILES: default no-op
}
```

The `RASTER` policy drops `profile["count"]`, `profile["dtype"]`, `profile["nodata"]`
when the child's payload `ndim`/`shape`/`dtype` differ from the parent's. Geographic
fields (`transform`, `crs`) are preserved by default since most derivations preserve
spatial reference.

### RDF Value Types

User-facing RDF values stay simple. `custom_properties` accept ordinary Python
literals; three thin wrapper types cover the cases where the type system needs help.

```python
class IRI(str):
    """An IRI reference. Subclasses str so it's still string-comparable and
    JSON-serialisable, but distinguishable from a string literal.
    Prefix resolution happens at serialise time using metadata.rdf_prefixes."""

@dataclass(frozen=True)
class LangString:
    value: str
    lang: str            # BCP 47 tag, e.g., "en", "fr-CA"

@dataclass(frozen=True)
class TypedLiteral:
    value: Any           # Python literal that doesn't infer to the right xsd type
    datatype: str        # e.g., "xsd:double"
```

**Default serialisation rules** at write time:

- `str` literal → `xsd:string`
- `int` → `xsd:integer`; `float`/`Decimal` → `xsd:double`/`xsd:decimal`
- `bool` → `xsd:boolean`
- `datetime` → `xsd:dateTime`; `date` → `xsd:date`
- `IRI(...)` → JSON-LD `{"@id": "..."}` (or expanded URI)
- `LangString(...)` → `{"@value": "...", "@language": "..."}`
- `TypedLiteral(...)` → `{"@value": "...", "@type": "..."}`

JSON-LD is the internal storage format. Users never see it — they write
`asset.metadata["sosa:observedProperty"] = IRI("sosa:NDVI")` or
`asset.metadata["dcterms:created"] = datetime(2024, 7, 1)`.

### Metadata mapping sugar

`Metadata` grows mapping-style access proxying to `custom_properties`:

```python
asset.metadata["sosa:observedProperty"] = IRI("sosa:NDVI")
"dcat:theme" in asset.metadata
del asset.metadata["dct:spatial"]
```

`__setitem__` lazy-initialises `custom_properties = {}` on first set. Colon-bearing
keys are treated as RDF prefixed names; bare keys raise `ValueError` (use
`metadata.field_to_set = value` for non-RDF attributes).

## Kind Taxonomy

| `kind`              | Typical payload                            | Typical `extras` keys              | Handler protocol               | First handler target    |
|---------------------|--------------------------------------------|------------------------------------|--------------------------------|-------------------------|
| `AssetKind.TABULAR` | `pd.DataFrame` (facade: `sunstone.DataFrame`) | —                              | `FormatHandler` (single file) or `StoreFormatHandler` (partitioned Parquet) | existing handlers       |
| `AssetKind.RASTER`  | `numpy.ndarray` (bands, H, W)              | `profile`, `crs`, `transform`      | `FormatHandler` or `StoreFormatHandler` (Zarr) | GeoTIFF                 |
| `AssetKind.ARRAY`   | `dict[str, numpy.ndarray]`                 | dimension labels, chunking         | `FormatHandler` (.npz) or `StoreFormatHandler` (Zarr) | NumPy `.npz`            |
| `AssetKind.TILES`   | tile-pyramid descriptor object             | `zoom_min`, `zoom_max`, `crs`      | `StoreFormatHandler`           | MBTiles / XYZ           |

`AssetKind` is closed. Same payload kind can be served by either handler protocol
depending on whether the file is single-file or store-backed. Partitioned Parquet
is `TABULAR` but uses `StoreFormatHandler` because the dataset is a directory of
files, not a single byte stream.

## Metadata Model

`Metadata` (in `sunstone.lineage`) is the asset-level container, used uniformly across
all kinds. Fields:

- `slug: str | None`, `name: str | None` — project-local identity.
- `identity: str | None` — globally stable URI template (see Identity section).
- `description: str | None`.
- `lineage: LineageMetadata` — PROV-O sources, activity chain, derivations.
- `rdf_prefixes: dict[str, str] | None` — namespace map.
- `custom_properties: dict[str, Any] | None` — keyed by `prefix:term`; values are
  Python literals or `IRI`/`LangString`/`TypedLiteral` wrappers.
- `field_metadata: dict[str, FieldSchema]` — per-column metadata for tabular kinds
  (existing).
- `component_metadata: dict[str, ComponentSchema]` — per-component metadata for any
  kind (raster bands, array variables, tile layers; tabular `field_metadata` becomes
  a typed view onto this for backwards compatibility).

`ComponentSchema` is a neutral structure:

```python
@dataclass
class ComponentSchema:
    name: str
    component_kind: str   # "column" | "band" | "variable" | "layer"
    dtype: str | None = None
    units: str | None = None       # Pint-parsable; emitted as qudt:unit IRI
    description: str | None = None
    custom_properties: dict[str, Any] | None = None   # per-component RDF triples
    derived_from: list[FieldDerivation] | None = None
```

The same shape covers `current_un_member_states.Country` (a column), `sentinel2.B04`
(a band), `era5.temperature` (a variable in a NetCDF), `osm_basemap.water` (a tile
layer). Discovery code reads via `ComponentSchema` uniformly.

`LineageMetadata.field_derivations` remains tabular-specific in interpretation. The
new generalisation flows through `ComponentSchema.derived_from`.

The `DatasetMetadata` class (also in `sunstone.lineage`) is the *YAML-row* class — it
represents a `datasets.yaml` entry, with `location`, `dataset_type`, `source`, etc.
The two classes overlap on RDF/identity fields but are not interchangeable.
`Asset.metadata` holds `Metadata`; `DatasetMetadata` is only used internally for
`datasets.yaml` round-tripping.

## Identity & Content Hashing

Two-axis identity for cross-project / cross-environment discovery:

**1. `Metadata.identity: str | None`** — URI template, supports the existing
sunstone-py env-var interpolation syntax:

- `sunstone://namespace/path/asset@1.0.0` (sunstone-native URI)
- `https://${DATASET_BASE_URL}/table@1.0.0` (env-interpolated for dev/staging/prod)

At write time the template is materialised into a concrete `@id` using the resolved
env vars; `dct:identifier` continues to carry the project-local `slug`.

**Default identity** when `identity is None` on write:
`sunstone://${PACKAGE_NAME}/${SLUG}@${PACKAGE_VERSION}` derived from the package's
declared name and version. Users who don't care get a sensible default; users who
do override the template once.

**2. `LineageMetadata.data_hash`** (existing `si:dataHash`) — content-hash identity,
machine-stable across environments. Cross-project "is this the same bytes?" matching.

Discovery queries can join on either axis: namespaced URIs for human lookup, content
hashes for byte-identical detection.

## Units (gating dependency for non-tabular handlers)

Non-tabular components (raster bands, array variables) frequently carry units
("kelvin", "m/s"). The unit story is reserved for the RDF-shape follow-up spec, but
the decisions are locked here:

- **Pint** is the canonical declaration and internal representation everywhere —
  tabular fields, raster bands, array variables. Units are Pint-parsable strings in
  `ComponentSchema.units`.
- **For numpy-array consumers** wanting unit-aware compute: `band.as_quantity()` /
  `variable.as_quantity()` returns `unyt.unyt_array.from_pint(pint_quantity)`. `unyt`
  has the stronger numpy-subclass integration; Pint is the declaration system.
- **For RDF emission**, units map to `qudt:unit` IRIs via a small Pint→QUDT mapping
  table (one-shot).
- **Escape hatch**: `as_quantity(backend="pint")` for callers who prefer
  `pint.Quantity` over `unyt.unyt_array`.

The follow-up spec must land before the first GeoTIFF handler ships.

## Client Code Walkthrough

```python
import sunstone as ss
from sunstone.rdf import IRI

asset = ss.read("inputs/sentinel2_2024_07.tif")
asset.metadata.description = "Sentinel-2 surface reflectance, July 2024"
asset.metadata["sosa:observedProperty"] = IRI("sosa:surfaceReflectance")
asset.metadata["dcat:theme"] = "earth-observation"

red, nir = asset.as_raster()[2], asset.as_raster()[3]
ndvi = (nir - red) / (nir + red)

out = asset.derive(
    payload=ndvi,
    slug="sentinel2-ndvi-202407",
    name="Sentinel-2 NDVI, July 2024",
    metadata_updates={"sosa:observedProperty": IRI("sosa:NDVI")},
)
ss.write(out, "outputs/ndvi_202407.tif")
```

What happens under the hood:

1. `ss.read` resolves the path via `datasets.yaml` → picks the GeoTIFF handler →
   handler returns an `Asset(kind=AssetKind.RASTER, payload=ndarray, extras={"profile": ...})`.
2. `asset.metadata["..."] = ...` writes via `__setitem__` lazy-init
   `custom_properties`. IRI values are tagged for JSON-LD `{"@id": ...}` serialisation.
3. `asset.derive(payload=ndvi, ...)` constructs the child `Asset`: extras
   deep-copied, `RASTER` derive policy drops stale `profile["count"]`/`["dtype"]`
   because shape changed from `(N_bands, H, W)` to `(H, W)`. Child metadata gets new
   slug/name; `custom_properties` are reset (not inherited) and `metadata_updates`
   replaces with NDVI's claim. Lineage records `prov:wasDerivedFrom = parent`; the
   parent has a slug (`sentinel2-2024-07`), so it shows up in `child.lineage.sources`.
4. `ss.write` picks the writer for `.tif`, hands it the `Asset`. If the asset has no
   `identity`, sunstone applies the default
   `sunstone://${PACKAGE_NAME}/sentinel2-ndvi-202407@${PACKAGE_VERSION}` template.
   `datasets.yaml` updates with the asset's metadata (slug/name/location/identity/
   custom_properties).

### Multi-parent example

```python
tiles = [ss.read(f"inputs/tile_{i}.tif") for i in range(4)]
mosaic_array = stitch(*(t.as_raster() for t in tiles))

mosaic = tiles[0].derive(
    payload=mosaic_array,
    slug="ne-africa-mosaic-2024",
    name="Northeast Africa Mosaic, 2024",
    derived_from=tiles,    # all four sources recorded in lineage
)
```

## Backwards Compatibility

**Zero break for plugin authors and end users.**

### DataFrame-returning plugins (existing pattern, still first-class)

```python
class CSVHandler:
    # No __sunstone_handler_protocol__ attribute → registry uses adapter
    def supports_metadata(self) -> bool: return False
    def can_read(self, path, format): return path.endswith(".csv")
    def read(self, stream, **kw) -> pd.DataFrame:
        return pd.read_csv(stream)
    def can_write(self, path, format): return path.endswith(".csv")
    def write(self, df, stream, **kw):
        df.to_csv(stream, index=False)
```

The registry wraps this in `TabularDataFrameAdapter` (the renamed, no-longer-"legacy"
adapter) that normalises to `Asset(kind=AssetKind.TABULAR, payload=df, metadata=...)`
and unwraps on write. Plugins that embed metadata via `df.attrs["sunstone_metadata"]`
(e.g., Parquet) keep working — the adapter preserves the round-trip.

```python
class TabularDataFrameAdapter:
    """Standard normaliser for DataFrame-returning handlers.
    Not deprecated; this is the canonical path for plugins that don't want
    the richer Asset return type."""

    def __init__(self, handler: object): self._h = handler
    def supports_native_metadata_extraction(self) -> bool: return False
    def supports_sunstone_metadata_embedding(self) -> bool:
        return getattr(self._h, "supports_metadata", lambda: False)()
    def can_read(self, path, format): return self._h.can_read(path, format)
    def read(self, stream, **kw) -> Asset:
        df = self._h.read(stream, **kw)
        embedded = df.attrs.pop("sunstone_metadata", None) if hasattr(df, "attrs") else None
        meta = embedded if isinstance(embedded, Metadata) else Metadata()
        return Asset(payload=df, kind=AssetKind.TABULAR, metadata=meta)
    def can_write(self, path, format): return self._h.can_write(path, format)
    def write(self, asset, stream, **kw):
        df = asset.as_table()
        if self.supports_sunstone_metadata_embedding():
            df.attrs["sunstone_metadata"] = asset.metadata
            try: self._h.write(df, stream, **kw)
            finally: df.attrs.pop("sunstone_metadata", None)
        else:
            self._h.write(df, stream, **kw)
    def supported_kinds(self): return (AssetKind.TABULAR,)
```

### Asset-returning plugins (new pattern, opt-in)

Plugins that want richer control declare the protocol marker and return `Asset`
directly. Required for any non-tabular kind. Concrete sketches:

```python
# CSV — stream-based, no metadata (same as above but Asset-native)
class CSVAssetHandler:
    __sunstone_handler_protocol__ = 2
    def supports_native_metadata_extraction(self): return False
    def supports_sunstone_metadata_embedding(self): return False
    def can_read(self, path, format): return path.endswith(".csv")
    def read(self, stream, **kw) -> Asset:
        return Asset(payload=pd.read_csv(stream), kind=AssetKind.TABULAR, metadata=Metadata())
    def can_write(self, path, format): return path.endswith(".csv")
    def write(self, asset, stream, **kw):
        asset.as_table().to_csv(stream, index=False)
    def supported_kinds(self): return (AssetKind.TABULAR,)


# Partitioned Parquet — store-based, native + sunstone metadata
class PartitionedParquetHandler:
    __sunstone_handler_protocol__ = 2
    def supports_native_metadata_extraction(self): return True
    def supports_sunstone_metadata_embedding(self): return True
    def can_read_store(self, location, format):
        return format == "parquet-partitioned" or (
            location.is_dir() and any(location.list("*.parquet"))
        )
    def read(self, location, **kw) -> Asset:
        ds = pyarrow.parquet.ParquetDataset(location.as_path())
        blob = ds.schema.metadata.get(b"sunstone_metadata")
        meta = Metadata.from_jsonld(json.loads(blob)) if blob else Metadata()
        meta.field_metadata = _schema_to_field_metadata(ds.schema)
        return Asset(payload=ds.read().to_pandas(), kind=AssetKind.TABULAR,
                     metadata=meta, extras={"partition_keys": ds.partitioning})
    def write(self, asset, location, **kw): ...
    def supported_kinds(self): return (AssetKind.TABULAR,)


# MBTiles — store-based (single file, random SQL access, not byte-stream)
class MBTilesHandler:
    __sunstone_handler_protocol__ = 2
    def supports_native_metadata_extraction(self): return True
    def supports_sunstone_metadata_embedding(self): return True
    def can_read_store(self, location, format):
        return location.as_path().suffix == ".mbtiles" or format == "mbtiles"
    def read(self, location, **kw) -> Asset:
        db = sqlite3.connect(location.as_path())
        native = dict(db.execute("SELECT name, value FROM metadata").fetchall())
        zoom_min, zoom_max = _query_zoom_range(db)
        if "sunstone_metadata" in native:
            meta = Metadata.from_jsonld(json.loads(native["sunstone_metadata"]))
        else:
            meta = Metadata(description=native.get("description"))
        return Asset(
            payload=TilePyramid(db=db, zoom_min=zoom_min, zoom_max=zoom_max),
            kind=AssetKind.TILES, metadata=meta,
            extras={"zoom_min": zoom_min, "zoom_max": zoom_max,
                    "crs": native.get("crs", "EPSG:3857")})
    def write(self, asset, location, **kw): ...
    def supported_kinds(self): return (AssetKind.TILES,)
```

### Existing user code

`sunstone.pandas.read_csv()`, `df.to_csv()`, `df.metadata.*`, `df.lineage` — all keep
working unchanged. `sunstone.DataFrame` is now a thin facade over an `Asset` of
`kind=AssetKind.TABULAR`, but users who don't touch non-tabular data never see the
envelope.

### Plugin Registry compatibility

`PluginRegistry.get_format_handlers()` continues to return registered handlers
without modification. A new accessor `get_asset_format_handlers()` returns the same
handlers normalised via adapters (i.e., every returned handler conforms to the new
`Asset`-returning protocol shape regardless of plugin style). Code that wants
uniformity uses the new accessor; code that wants raw access keeps the old one.

## Error Handling

- `ss.read(path)` with no handler match → `UnknownFormatError`, unchanged.
- `ss.write(asset, path)` where the writer's `supported_kinds()` doesn't include
  `asset.kind` → `IncompatibleAssetKindError` with the asset's kind and the
  handler's supported kinds in the message.
- `asset.as_table()` / `as_raster()` / etc. on the wrong kind →
  `IncompatibleAssetKindError`.
- `asset.derive(payload=...)` with `payload` shape incompatible with `kind` is **not**
  validated by `derive()` itself; sunstone treats `kind` as descriptive. The
  `KindDerivePolicy` may invalidate stale extras based on the change; validation
  proper is the writer's job.
- `asset.metadata["bare-key"] = ...` (no colon) → `ValueError`. Mapping sugar
  enforces prefixed RDF names.

## Deprecation Warnings

The `LegacyFormatHandlerAdapter` framing is gone — there is no deprecated path. The
only deprecation in this design is the legacy `supports_metadata()` predicate, which
is being split into `supports_native_metadata_extraction()` /
`supports_sunstone_metadata_embedding()`. Warning policy:

- Emit on **first actual use**, not at handler-registration time, to avoid breaking
  `warnings-as-errors` users at import time.
- One warning per handler class, not per call.
- Honour `SUNSTONE_SUPPRESS_LEGACY_WARNINGS=1` env var as an escape hatch for
  CI pipelines.

## Testing Strategy

- Unit tests for `Asset` construction, `derive()` lineage recording (single + multi
  parent), `extras` deep-copy isolation, slug/name clearing, custom_properties opt-in
  inheritance.
- Tests for the `RASTER` `KindDerivePolicy`: profile invalidation when shape/dtype
  change; preservation when they don't.
- Round-trip tests for `TabularDataFrameAdapter`: an existing Parquet handler keeps
  producing identical results when invoked through `ss.read`/`ss.write`, including
  `df.attrs["sunstone_metadata"]` round-trip.
- A `DummyRasterHandler` returning `Asset(kind=AssetKind.RASTER, payload=np.zeros(...))`
  exercises the non-tabular path without pulling in rasterio (kept optional).
- IRI / LangString / TypedLiteral serialisation round-trip into JSON-LD.
- Metadata mapping sugar: `__setitem__`, `__getitem__`, `__delitem__`, `__contains__`,
  bare-key rejection.
- Multi-parent `derive()`: `child.lineage.sources` contains snapshots of all slugged
  parents; unsaved-parent collapse preserves grandparent identity.
- Identity template materialisation: env-var interpolation, default derivation when
  `identity is None`.
- `StoreFormatHandler` with a `DummyZarrHandler` returning an `Asset` from a
  `ResourceLocation`-backed directory.
- Integration test in the `UNMembersProject` fixture: tabular workflows are
  byte-identical pre- and post-refactor.

## Migration Path

No breaking changes. Phased rollout:

1. **Substrate.** Introduce `Asset`, `AssetKind`, `IRI`/`LangString`/`TypedLiteral`,
   `Metadata` mapping sugar, `ComponentSchema`, `Metadata.identity`, `Metadata.component_metadata`,
   the `KindDerivePolicy` registry, `IncompatibleAssetKindError`. No behaviour change
   yet — adding types only.
2. **Adapter as default.** Introduce `TabularDataFrameAdapter`, normalise all
   DataFrame-returning handler results into `Asset` at the registry boundary.
   Existing `DataFrame.read_dataset`/`read_csv`/`read_excel` paths get a
   `_read_tabular_asset()` helper that unwraps an `Asset` payload back to a DataFrame
   and merges metadata consistently. All existing tests pass unchanged.
3. **Asset-returning entry points.** Add `ss.read` / `ss.write` autodispatch
   returning/accepting `Asset`, plus `Asset.derive()` with provenance recording
   (single + multi-parent, unsaved-parent activity chaining). Tabular sugar
   (`sunstone.pandas.*`, `DataFrame.to_csv`) unchanged.
4. **`StoreFormatHandler` protocol + dispatch.** Add `ResourceLocation`,
   `StoreFormatHandler`, `datasets.yaml`-format-first dispatch order in
   `PluginRegistry`, `get_asset_format_handlers()` accessor.
5. **Migrate built-ins.** Move `BuiltinFormatHandler` and `ParquetFormatHandler` to
   the new `Asset`-returning protocol natively. (These are currently appended
   directly inside `PluginRegistry._discover()` — adapter-wrapping doesn't apply.)
6. **First non-tabular handler.** GeoTIFF, in its own design, gated on the RDF-shape
   follow-up spec landing first.

External plugins migrate at their own pace by setting
`__sunstone_handler_protocol__ = 2` and switching their return type to `Asset`. No
deprecation timeline; both paths supported.

## Follow-up Specs

- **Per-kind RDF profiles** — required triples per `AssetKind` (CRS, bbox, temporal
  coverage, bands, units, license, content hash). DCAT/PROV/GeoSPARQL/SOSA mappings.
  QUDT unit IRIs. JSON-LD context. **Gating dependency for the first non-tabular
  handler.**
- **Units in non-tabular metadata** — folded into the RDF profile spec above. Pint
  declarations, unyt bridging, QUDT IRI mapping table.
- **`Resource` abstraction** — convergence target for `FormatHandler` and
  `StoreFormatHandler` if/when stream-based handlers also benefit from the
  store-aware interface. Plugin-author migration only; user-facing API unchanged.

## Resolved Decisions

Captured here for the record; full discussion in
`2026-05-12-asset-envelope-open-decisions.md`.

| # | Decision | Resolution |
|---|----------|------------|
| 1 | DataFrame wrapper vs Asset ownership | `sunstone.DataFrame` becomes a facade over `Asset`; `df.metadata is asset.metadata`. |
| 2 | `Metadata` mapping sugar | Add `__getitem__`/`__setitem__`/`__delitem__`/`__contains__` proxying to `custom_properties` with lazy init; bare keys reject. |
| 3 | `derive()` multi-parent | Add `derived_from: Iterable[Asset] \| None = None` kwarg, default `[self]`. |
| 4 | `derive()` name inheritance | Both `slug` and `name` clear to `None` unless explicitly provided. |
| 5 | `derive()` custom_properties propagation | Do NOT inherit by default; opt in via `inherit_custom_properties=True`. |
| 6 | Extras mutability on derive | Deep-copy. |
| 7 | Per-kind derive policies | `KindDerivePolicy` registry keyed on `AssetKind`. `RASTER` policy invalidates stale profile fields on shape/dtype change. |
| 8 | Unsaved parents in `derived_from` | Collapse: child inherits parent's `sources`; child's `activity` chains parent's activity + new derive op. |
| 9 | Array payload vs `extras["arrays"]` overlap | Drop `asset.arrays`. Payload IS the data for every kind. |
| 10 | Tile / store-based protocol | Parallel `StoreFormatHandler` taking `ResourceLocation` instead of `BinaryIO`. |
| 11 | Autodispatch | `datasets.yaml` `format` field is primary signal; store-vs-stream classification by `ResourceLocation`; extension as fallback. |
| 12 | Legacy vs new handler distinction | Zero BC break. Capability marker `__sunstone_handler_protocol__ = 2`. Adapter is the default normaliser, not "legacy". |
| 13 | `supports_metadata()` split | `supports_native_metadata_extraction()` + `supports_sunstone_metadata_embedding()`. |
| 14 | `PluginRegistry.get_format_handlers()` migration | Add `get_asset_format_handlers()` returning adapter-normalised handlers; keep `get_format_handlers()` for raw access. |
| 15 | RDF discovery shape | Separate gating-dependency follow-up spec. Pint canonical + `unyt.from_pint` for numpy + QUDT IRI mapping. |
| 16 | RDF value typing | Three small wrappers `IRI`, `LangString`, `TypedLiteral`. Python literals default. JSON-LD is internal only. |
| 17 | Stable `@id` | `Metadata.identity: str \| None` URI template with env-var interpolation. Default `sunstone://${PACKAGE_NAME}/${SLUG}@${PACKAGE_VERSION}`. |
| 18 | Component metadata | Neutral `ComponentSchema` in `Metadata.component_metadata`. `field_metadata` becomes a typed view over column components. |
| 19 | Deprecation warning timing | First-use, once per handler class. `SUNSTONE_SUPPRESS_LEGACY_WARNINGS=1` env-var escape hatch. |
| — | `AssetKind` open vs closed | Closed enum (resolved in spec round 1 per crit). |
| — | `derive()` always records `wasDerivedFrom` | Yes; transients should be raw payloads, not `Asset`. |
| — | `Asset.payload` laziness | Out of scope; lazy payload types (e.g., `RasterRef`) implementable without envelope changes. |
