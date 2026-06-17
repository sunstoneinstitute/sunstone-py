# GeoJSON/TopoJSON Support + Extensible Field Types

**Date:** 2026-06-16 · **Status:** Proposed
**Related:** `2026-06-14-field-observed-property-design.md` (field metadata — the extension point), `2026-04-23-parquet-metadata-design.md` (embedded-metadata precedent), `2026-05-27-asset-kind-blob...md` (optional-dep handler pattern).
**Format refs:** `docs/references/geojson.md`, `docs/references/topojson.md` (normative rules).
**Prior art:** Frictionless (`geojson`/`geopoint` *field* types), GeoParquet/GeoArrow (geometry = column metadata over an unchanged format), pandas `ExtensionDtype` / geopandas `"geometry"` dtype (CRS per column). All agree: **geometry is a field type, not a resource type.**

## Problem

GeoJSON shipped as `.json` is silently mis-parsed by `read_json`. There is no geo support, and no way to mark a column as geometry. We want GeoJSON/TopoJSON read+write into a `geopandas.GeoDataFrame` with lineage, gated behind an optional `[geo]` extra.

## Design

**D1 — Geo is its own `AssetKind`: `GEOFEATURES`** (payload = `geopandas.GeoDataFrame`; accessor `as_geofeatures()`; CRS-aware derive policy). Not `TABULAR` (a GeoDataFrame isn't a plain table — `as_table()` would be gymnastics) and not `VECTOR` (overloaded by embeddings). Adding one enum member is cheap — nothing matches `AssetKind` exhaustively. Core declares the member (a bare string, no geopandas dep); `[geo]` supplies the handlers, typed wrapper, and accessor. This is the runtime payload label — **distinct from** the catalog `type` axis (D4), not a resource-catalog discriminator.

**D2 — Field-type registry (the extensibility seam).** Extend the field-metadata `type` axis with a registry: a plugin exposes `field_types() -> tuple[FieldTypeDescriptor, ...]` (`name`, optional `validate` hook, optional (de)serialization), classified in `PluginRegistry._register`. Built-in scalar types pre-registered. This is the pandas-`ExtensionDtype` / GeoArrow-extension-type / Frictionless-field-type pattern — `geometry` now, an embedding `vector` later. No top-level kind registry.

**D3 — `geometry` field type** (registered by `[geo]`): per-**column** CRS, with one designated **primary** geometry column (GeoParquet's `primary_column`); multiple geometry columns allowed. shapely (via geopandas) owns geometry validity; sunstone records the field type + CRS and validates at the boundary (mode-gated). The kind (`GEOFEATURES`, D1) says "this payload has geometry"; the field type says *which* column and its CRS. Catalog `type` stays a thin `table` (D4) — geometry is never a catalog resource-type.

**D4 — `format` drives resolution; `type` stays thin.** Handler resolution = pinned `datasets.yaml` `format` → else file extension. `type` is optional, inferred, Frictionless-shaped (`table`), descriptive only — **not** load-bearing. Consequences: `format: geojson` on a `.json` file reads correctly (the real silent-failure fix); `.geojson`/`.topojson` auto-detect by extension; a missing `[geo]` extra → loud "install `sunstone-py[geo]`" error (no built-in claims those extensions, so never a blob fallback). Add a `format` field to `DatasetMetadata`.

**D5 — `GeoFeaturesFormatHandler`** in `handlers_geo.py` (keeps geopandas out of always-loaded code, per the npz/hdf5 pattern). `can_read`/`can_write` by extension/format only (no geopandas import); geopandas/shapely/topojson imported lazily with a clear `[geo]` error. Read: `json.loads` → pop `"sunstone"` member (D6) → `GeoDataFrame` (default CRS EPSG:4326). Write: `gdf.to_json()` (GeoJSON) / `topojson.Topology(gdf).to_json()` (TopoJSON). Both formats decode to a `GEOFEATURES` payload (one kind, two serializations); TopoJSON's shared-arc **topology is recomputed on write, not preserved** through the GeoDataFrame (geopandas has no topology concept — geometrically equivalent, not arc-identical). **RFC 7946 conformance** (per `geojson.md`): never emit a `crs` member (warn if CRS≠WGS84; reprojection is out of scope); orient rings right-hand on write; preserve Feature `id` (geopandas drops it by default); accept null geometry/properties; lon-lat order (assert in tests).

**D6 — Embed metadata as a top-level `"sunstone"` foreign member** (JSON-LD), like Parquet. Safe per RFC 7946 §6.1 (foreign members allowed; ignored by Leaflet/OpenLayers, preserved by GDAL; `"sunstone"` isn't a reserved name). `datasets.yaml` stays authoritative; embedding is belt-and-suspenders.

**D7 — `sunstone.geopandas` facade + `GeoDataFrame` wrapper** (in `[geo]`): `gpd.read_file()/read_geojson()/read_topojson()`, project-path resolution and `datasets.yaml` registration like the `pandas` facade. Wrapper wraps `Asset(kind=GEOFEATURES, payload=GeoDataFrame)`, knows the geometry column, flows lineage. `to_geojson()/to_topojson()` require `slug`+`name`. Core never imports geopandas.

**D8 — `[geo]` extra:** `geopandas, shapely, pyogrio, topojson`. Optional, never base.

## Open question

**O1 — TopoJSON decode.** Fully specified in `topojson.md` (delta-decode + transform + arc-stitch + negative-index reversal). At plan time pick: (a) GDAL's read-only TopoJSON driver via pyogrio (no new dep), else (b) hand-roll ~40 lines. Encode uses `topojson`. Either way no decode-only dependency.

## Phasing

1. **Core, no geo dep:** D2 field-type registry, D4 `format` pin + format-driven resolution.
2. **`[geo]` plugin:** D1, D3, D5–D8. Depends on (1).

## Testing (TDD; geo tests `importorskip("geopandas")`)

- Registry: register/look up a field type; mode-gated validation; built-ins unaffected.
- Resolution: `format: geojson` on `.json` selects geo handler (not `read_json`); pinned format beats extension; `.geojson` without `[geo]` errors loudly naming the extra.
- Geo round-trip: GeoJSON + TopoJSON geometry/CRS; primary geometry column; `"sunstone"` metadata round-trip; Feature `id` preserved; no `crs` member emitted; facade reads + lineage; `to_*` require slug+name.

## CHANGELOG (one line per phase as it lands)

```
- Added: Extensible field value-types (registry) for structured columns.
- Added: GeoJSON and TopoJSON read/write via the optional [geo] extra.
```
