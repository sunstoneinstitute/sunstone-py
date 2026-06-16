# GeoJSON/TopoJSON Vector Support + Plugin-Extensible Kinds

**Date:** 2026-06-16
**Status:** Proposed
**Related:** `2026-05-12-generic-format-handler-asset-envelope-design.md` (Asset envelope, closed-enum decision this spec revises), `2026-05-27-asset-kind-blob-and-content-type-discovery-design.md` (adding a kind, optional-dep handler pattern, content-type discovery), `2026-04-07-dataframe-metadata-design.md` (Metadata model), `2026-04-23-parquet-metadata-design.md` (embedded-metadata precedent).

## Problem

sunstone-py has no geospatial vector support. The `.json` extension maps to pandas `read_json` in `BuiltinFormatHandler`, so a GeoJSON file — which *is* `.json` — gets silently slurped and mangled into a nonsense tabular frame. There is no `geopandas`/`shapely` anywhere, no kind for vector geometry, and no user-facing API for geometry data.

Three deeper issues surfaced while scoping this:

1. **No way to pin a dataset's shape or format.** `read_dataset` resolves a handler purely as explicit `format=` argument → else file-extension detection (`dataframe.py:426`). `datasets.yaml` has a `type` field (`DatasetMetadata.resource_type`), but it is only a CLI validation hint (`type: table` ⇒ fields required) and is **never consulted for handler resolution**. So a registered `.geojson` with the `[geo]` extra absent silently falls back to `BlobFormatHandler`. That silent wrong-shape handling is the bug to kill.

2. **Shape and serialization are independent axes, and neither determines the other.** Many formats share one shape (CSV/JSON/Excel/TSV/Parquet all → tabular; GeoJSON/TopoJSON/Geobuf all → vector). And one format spans many shapes (JSON is table *or* tree *or* GeoJSON). This is exactly the Frictionless model the repo already follows — `type` (resource kind), `format` (serialization), `mediatype` (IANA MIME) as separate fields. We should mirror it.

3. **Kinds are a closed enum, requiring core changes to extend.** `AssetKind` is a closed `Enum` whose docstring says new kinds "require extending upstream." But an audit shows **nothing relies on enum exhaustiveness**: there is no `match`/`case` on `AssetKind` anywhere. Every consumer is an identity check (`if kind is not X: raise`), a dict-dispatch-with-default (`KIND_DERIVE_POLICIES.get(kind, no_op_policy)` — already a registry), or a per-handler `supported_kinds()` tuple. The only things forcing a core edit are the closed `Enum` itself and the typed accessors. Opening this up is therefore cheap, and lets an optional extra like `[geo]` contribute *both* a kind and its handlers without touching core.

## Goals

- **Plugin-extensible kinds.** A `KindRegistry` lets internal optional modules (and future external plugins) register a new kind (shape) — name, payload contract, derive policy — without modifying core. Built-in kinds are pre-registered; behavior is unchanged for existing kinds.
- **Geo as a self-contained plugin.** The `[geo]` extra contributes the `vector` kind, GeoJSON/TopoJSON handlers (full round-trip both ways, incl. topology computation on TopoJSON write), and a lineage-tracking `GeoDataFrame` wrapper + `sunstone.geopandas` facade — all gated by the extra. No core file references geopandas, even under `TYPE_CHECKING`.
- **Pinnable, load-bearing `type` + `format` in `datasets.yaml`**, Frictionless-aligned, so handler resolution can refuse a wrong-shape handler instead of silently falling back to blob.
- **Embedded lineage** via a top-level `"sunstone"` foreign member, giving GeoJSON/TopoJSON metadata round-trip parity with Parquet.

## Non-Goals

- Raster/coverage formats (GeoTIFF, COG) — `AssetKind.RASTER`, separate.
- Vector formats beyond GeoJSON/TopoJSON (Shapefile, GeoPackage, FlatGeobuf, Geobuf, KML). The plugin is structured so adding them later is incremental — they register against the same `vector` kind.
- Reprojection/CRS transformation helpers. We preserve the file's CRS (default WGS84 per RFC 7946) and expose it; transformation is the user's call via geopandas.
- A general-purpose external-plugin *packaging* guide. We expose the registration mechanism and use it internally for geo; documenting third-party plugin distribution is a follow-up.
- Content-sniffing. Detection stays extension + explicit `format=` + pinned `datasets.yaml`, as everywhere else.

## Design Decisions

### Phase 1 — Open the kind system (core, behavior-preserving)

#### D1. `AssetKind` becomes a `StrEnum`; `Asset.kind` becomes `str`

`AssetKind` is changed from `Enum` to `StrEnum`, so members are named string constants (`AssetKind.VECTOR == "vector"`) and arbitrary registered kind names are representable as plain strings. `Asset.kind` is typed `str`.

The ~10 identity checks (`if self.kind is not AssetKind.TABULAR`) migrate from `is`/`is not` to `==`/`!=` (StrEnum members are not identical objects to bare string literals). This is mechanical and fully covered by existing tests. Built-in kind names are unchanged on the wire: `tabular`, `raster`, `array`, `tiles`, `blob`.

#### D2. `KindRegistry` and `KindDescriptor`

A registry parallel to the format-handler registry. A `KindDescriptor` carries:

```python
@dataclass(frozen=True)
class KindDescriptor:
    name: str                                   # e.g. "vector"
    payload_contract: Callable[[Any], bool] | None = None   # validate payload (duck-typed; no hard dep)
    derive_policy: KindDerivePolicy | None = None
    description: str | None = None
```

- Built-in kinds (`tabular`, `raster`, `array`, `tiles`, `blob`) are pre-registered in core with their existing semantics.
- The registry is **plugin-facing**: a registered plugin MAY expose `kind_descriptors() -> tuple[KindDescriptor, ...]`, classified during `PluginRegistry._register` alongside `AuthProvider`/`FormatHandler`/`StoreFormatHandler`. This is how a future *external* plugin adds a kind.
- Internal optional modules register via the existing conditional-import path (the `NpzFormatHandler` pattern): when the extra is importable, register its `KindDescriptor` and handlers; otherwise skip.

#### D3. Derive policies keyed by kind name

`KIND_DERIVE_POLICIES` is re-keyed from `AssetKind` to `str` (no semantic change — it is already a dict with a `no_op_policy` default). A `KindDescriptor.derive_policy` is registered into this dict at kind-registration time. The RASTER policy is unchanged.

#### D4. Accessors: typed built-ins + generic extension accessor

The built-in typed accessors (`as_table`, `as_raster`, `as_array`, `as_tiles`, `as_blob`) stay in core for the common, statically-typed path. Extension kinds use a generic accessor:

```python
def require_kind(self, name: str) -> Any:
    if self.kind != name:
        raise IncompatibleAssetKindError(expected=name, actual=self.kind)
    return self.payload
```

`IncompatibleAssetKindError` is generalized to accept string kind names (it already stores `expected`/`actual`). A plugin that wants a typed accessor for its kind (geo does) provides it on its own wrapper, not on core `Asset`. **Core never imports geopandas**, so there is no core `as_vector()` returning a `GeoDataFrame`; the typed surface lives on the plugin's `GeoDataFrame` wrapper.

### Phase 2 — Geo as a self-contained `[geo]` plugin

#### D5. The `vector` kind is registered by `[geo]`, not core

`vector` is a `KindDescriptor` registered only when the `[geo]` extra is present. Semantics: payload is a `geopandas.GeoDataFrame`; CRS mirrored in `extras["crs"]` (existing `Asset.crs` reads it); derive policy clears `extras["crs"]` when a derivation drops the geometry column, keeps it otherwise (same shape as the RASTER profile policy). When `[geo]` is absent, the `vector` kind is simply unregistered — and resolution (D11) turns that into a loud error rather than a blob.

> Shape rigor note: `vector` is a distinct shape from `table` — a geometry-typed column plus a CRS contract that `table` does not admit — but it is table-*compatible* (rectangular, row-per-feature; `GeoDataFrame` IS-A `DataFrame`). `as_table()` on a vector is therefore an explicit, lossy downcast (geometry dropped/serialized), never an identity. A "vector" is conceptually the single geometry column + its contracts; adding non-geometry columns is the feature-collection refinement geopandas already models, not a different kind.

#### D6. `VectorFormatHandler` in `handlers_geo.py`

A new module (keeps geopandas/shapely/topojson out of the always-loaded `handlers.py`, exactly like `handlers_gcs.py`/`handlers_s3.py`/`handlers_npz.py`/`handlers_hdf5.py`).

```python
class VectorFormatHandler:
    __sunstone_handler_protocol__ = 2
    _EXTENSION_MAP = {".geojson": "geojson", ".topojson": "topojson"}
    _FORMATS = frozenset({"geojson", "topojson"})
    def supported_kinds(self): return ("vector",)
```

- `can_read`/`can_write` resolve by extension or explicit `format=` **only** — no geopandas import (mirrors the module-level `_READER_FORMATS` trick), so existence checks stay dependency-free.
- `supports_sunstone_metadata_embedding() -> True`; `supports_native_metadata_extraction() -> False`.
- geopandas/shapely/topojson imports are **lazy inside `read`/`write`**, re-raising `ImportError` as a clear "install `sunstone-py[geo]`" message (the `ParquetFormatHandler`/pyarrow pattern).
- **Read**: read stream → `json.loads` → pop top-level `"sunstone"` member into `Metadata` (D8) → build `GeoDataFrame` (`from_features`, default CRS `EPSG:4326` per RFC 7946 when absent). TopoJSON first decodes topology→FeatureCollection (arc-stitching) per named object. **Decode library: Open Question O1.**
- **Write**: GeoJSON via `gdf.to_json()` → dict; TopoJSON via `topojson.Topology(gdf).to_json()` → dict (topology computed here). Inject `"sunstone"` member (D8) → `json.dumps` to stream.

#### D7. Plain `.json` is NOT auto-detected as geo

`.geojson` → `geojson`, `.topojson` → `topojson` by extension; plain `.json` stays tabular. To read a `.json` file as vector, pass `format="geojson"` or pin it in `datasets.yaml`. Follows the established `.txt`/`.xls` precedent. (This is the "one format, many shapes" ambiguity made concrete — JSON alone cannot imply a shape.)

#### D8. Embed `Metadata` as a top-level `"sunstone"` foreign member

On write, serialize `Metadata.to_jsonld()` as a single top-level member named `"sunstone"`; on read, pop and parse it. Gives lineage round-trip parity with Parquet. Verified safe against primary sources:

- **RFC 7946 §6.1**: *"Members not described in this specification ('foreign members') MAY be used in a GeoJSON document."*
- **GDAL/OGR** (QGIS, geopandas via pyogrio/fiona) *preserves* foreign members by default (NATIVE_DATA round-trip).
- **Leaflet** and **OpenLayers** ignore unknown top-level members (verified against Leaflet source — no whitelist, no throw, no warn).
- Avoids the two names RFC 7946 forbids at `FeatureCollection` level (`geometry`, `properties`). `"sunstone"` is safe.

`datasets.yaml` remains authoritative; embedding is belt-and-suspenders. The asymmetric round-trip (JS tools drop the member on re-export, GDAL keeps it) costs nothing.

#### D9. `sunstone.geopandas` facade + `GeoDataFrame` wrapper (in the geo plugin)

- `from sunstone import geopandas as gpd`, then `gpd.read_file('x.geojson')` (auto-detect by extension), plus explicit `gpd.read_geojson(...)` / `gpd.read_topojson(...)`. Same project-path resolution and `datasets.yaml` registration as the `pandas` facade.
- `GeoDataFrame` wrapper wraps `Asset(kind="vector", payload=geopandas.GeoDataFrame)`. `.data` → the GeoDataFrame, `.metadata` → unified `Metadata`, `.asset` → envelope; lineage flows through ops, parallel to the tabular `DataFrame`. This wrapper is the typed `as_vector`-equivalent surface (D4).
- Writers `gdf.to_geojson(...)`/`gdf.to_topojson(...)` require `slug`+`name` for new outputs, like `to_csv`.
- The TABULAR-only guard in `DataFrame.read_dataset` (`dataframe.py:454`) stays; the geo wrapper has its own vector-accepting read path. Both share `Metadata`/lineage machinery but enforce their own kinds.

### Cross-cutting — `datasets.yaml` pinning and resolution

#### D10. `type` + `format` pins in `datasets.yaml` (Frictionless-aligned)

Add a `format` field to `datasets.yaml` → `DatasetMetadata.format`. Keep `type` as the orthogonal *shape* axis and extend its vocabulary to the registered kind names (`table`, `vector`, `raster`, `array`, `tiles`, `blob`).

```yaml
inputs:
  - slug: world-borders
    type: vector        # shape  → kind "vector" (load-bearing; see D11)
    format: geojson     # serialization → handler selection within the shape
    location: inputs/world.geojson
```

CLI validation extends its existing `type`-driven rules (`type: table` ⇒ fields required) with vector expectations (geometry/CRS).

#### D11. Resolution filters handlers by `supported_kinds()` — `type` is load-bearing

`read_dataset` (and the geo facade read path) thread the dataset's pinned `format` into resolution as the explicit format **before** extension detection, and filter candidate handlers to those whose `supported_kinds()` includes the pinned `type` (when set). Consequences:

- `type: vector` **alone** refuses `BlobFormatHandler` (`supported_kinds() == ("blob",)`) and `BuiltinFormatHandler` (`("tabular",)`) on a shape mismatch — the silent blob fallback dies even with no `format` pinned.
- Missing `[geo]` extra ⇒ `vector` kind unregistered ⇒ no vector-capable handler ⇒ the existing loud `"No format handler found ... Install a plugin"` error, naming the `[geo]` extra. Never a blob.
- `format: geojson` disambiguates within the vector shape (geojson vs topojson vs future geobuf).
- Both pinned ⇒ chosen handler must satisfy both. The blob fallback is reachable **only** for a fully-unpinned dataset whose extension no specific handler claims — the intended residual behavior.

#### D12. `[geo]` optional extra

```toml
[project.optional-dependencies]
geo = ["geopandas", "shapely", "pyogrio", "topojson"]
```

Strictly optional, never base (dependency-hygiene preference). `pyogrio` is geopandas's fast IO engine; `topojson` provides TopoJSON encoding. TopoJSON *decode* dependency is O1.

## Open Questions

- **O1. TopoJSON decode library.** `topojson` (mattijn/topojson) cleanly covers *encoding*; the decode direction (TopoJSON → GeoDataFrame) needs a verified library or a small hand-rolled arc-stitcher (~100 lines against the TopoJSON 1.0 spec). Resolve at plan time before finalizing the `[geo]` extra contents — do not guess.
- **O2. External-plugin kind registration surface.** D2 proposes `kind_descriptors()` on plugin objects classified during `_register`. Confirm this shape vs. a dedicated entry-point group at plan time. Geo uses the internal conditional-import path regardless, so this does not block Phase 2.

## Phasing

Phase 1 and Phase 2 are separate implementation plans / PRs:

1. **Phase 1** (core seam): D1–D4 + D10–D11's resolution mechanism, with built-in kinds registered exactly as today and the tabular/parquet/blob/array handlers declaring `supported_kinds()` (most already do). Behavior-preserving; lands on existing tests plus new registry tests. No geo dependency.
2. **Phase 2** (geo plugin): D5–D9 + D12, gated by `[geo]`. Depends on Phase 1.

This keeps the risky-looking refactor isolated and verifiable before any geopandas code lands.

## Testing

TDD throughout. Geo tests skip without the extra (`pytest.importorskip("geopandas")`).

- **Phase 1**: `tests/test_kind_registry.py` — register/lookup a custom kind; derive policy dispatched by name; `require_kind` + `IncompatibleAssetKindError` for string kinds; built-ins still resolve; `StrEnum` equality (`AssetKind.TABULAR == "tabular"`). Existing asset/handler/dataframe tests must stay green after the `is`→`==` migration.
- **Resolution (D10/D11)**: `type: vector` refuses blob/tabular handlers; pinned `format` wins over extension; both-pinned requires both; unpinned `.geojson` with `[geo]` absent errors loudly (not blob); fully-unpinned unknown extension still reaches blob.
- **Phase 2**: `tests/test_handlers_geo.py` — GeoJSON round-trip (geometry + CRS); TopoJSON round-trip (topology on write, geometry on read); `"sunstone"` foreign-member metadata round-trip; `.json` not claimed by the vector handler; explicit `format="geojson"` on a `.json` path works; missing-`[geo]` `ImportError` names the extra. `tests/test_geopandas.py` — facade reads, project-path resolution, `datasets.yaml` registration, lineage flow, `to_*` requires slug+name.

## CHANGELOG

Two lines under `[Unreleased]` (one per phase as they land):

```
- Added: Plugin-extensible asset kinds via a kind registry.
- Added: GeoJSON and TopoJSON read/write via the optional [geo] extra.
```
