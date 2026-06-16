# GeoJSON and TopoJSON Vector Support

**Date:** 2026-06-16
**Status:** Proposed
**Related:** `2026-05-12-generic-format-handler-asset-envelope-design.md` (Asset envelope), `2026-05-27-asset-kind-blob-and-content-type-discovery-design.md` (adding a new `AssetKind`, optional-dep handler pattern), `2026-04-07-dataframe-metadata-design.md` (Metadata model), `2026-04-23-parquet-metadata-design.md` (embedded-metadata precedent).

## Problem

sunstone-py has no geospatial vector support. The `.json` extension currently maps to pandas `read_json` in `BuiltinFormatHandler`, so a GeoJSON file — which *is* `.json` — gets silently slurped and mangled into a nonsense tabular frame. That is worse than not supporting it: it *pretends* to. There is no `geopandas`/`shapely` anywhere, no `AssetKind` for vector geometry, and no user-facing API for geometry data.

We need first-class read/write of **GeoJSON** and **TopoJSON**, returning a real `geopandas.GeoDataFrame` with geometry, CRS, and lineage tracking, so data scientists can consume basemaps and feature collections through the same metadata/lineage story as tabular data.

## Goals

- Add a `VECTOR` `AssetKind` whose payload is a `geopandas.GeoDataFrame`.
- Built-in handler reading and writing **GeoJSON** (full round-trip) and **TopoJSON** (full round-trip, including topology computation on write).
- A `sunstone.geopandas` facade plus a lineage-tracking `GeoDataFrame` wrapper, parallel to the existing `sunstone.pandas` / `DataFrame`.
- Round-trip the sunstone `Metadata` as a top-level `"sunstone"` foreign member in the JSON, giving lineage parity with the Parquet handler.
- All geo dependencies behind an optional `[geo]` extra; core install and existence checks stay free of `geopandas`.

## Non-Goals

- Raster/coverage formats (GeoTIFF, COG) — those are `AssetKind.RASTER`, a separate concern.
- Shapefile, GeoPackage, FlatGeobuf, KML, or other OGR vector formats. GeoJSON/TopoJSON only for now; the handler is structured so adding OGR-driver formats later is incremental.
- Reprojection / CRS transformation helpers. We preserve the file's CRS (defaulting to WGS84 per RFC 7946) and expose it; transformation is the user's call via geopandas.
- Content-sniffing. Detection stays extension-based plus explicit `format=`, as everywhere else.

## Design Decisions

### D1. Add `AssetKind.VECTOR`

Extend the closed enum in `sunstone.asset.AssetKind`:

```python
class AssetKind(Enum):
    TABULAR = "tabular"
    RASTER  = "raster"
    ARRAY   = "array"
    TILES   = "tiles"
    BLOB    = "blob"
    VECTOR  = "vector"   # NEW — geopandas.GeoDataFrame payload
```

Semantics:

- `Asset(kind=VECTOR).payload` is a `geopandas.GeoDataFrame`.
- CRS lives in `extras["crs"]`; the existing `Asset.crs` property already reads it. (The GeoDataFrame also carries `.crs` natively; `extras["crs"]` is the envelope-level mirror, consistent with how RASTER keeps its `profile`.)
- New typed accessor mirroring the others:

```python
def as_vector(self) -> "geopandas.GeoDataFrame":
    if self.kind is not AssetKind.VECTOR:
        raise IncompatibleAssetKindError(expected=AssetKind.VECTOR, actual=self.kind)
    return cast("geopandas.GeoDataFrame", self.payload)
```

- `derive()`: add a VECTOR entry to `derive_policies.apply_kind_derive_policy`. A derivation that keeps the geometry column keeps `extras["crs"]`; a derivation whose result is non-geometry (geopandas op that drops geometry) clears it — same shape as the RASTER profile-invalidation policy. The `as_vector()` import of `geopandas` is lazy (inside the method / `TYPE_CHECKING`), so importing `sunstone.asset` never drags geopandas in.

### D2. `VectorFormatHandler` in a new `handlers_geo.py`

A new module keeps the `geopandas`/`shapely`/`topojson` imports out of the always-loaded `handlers.py`, exactly as `handlers_gcs.py`, `handlers_s3.py`, `handlers_npz.py`, and `handlers_hdf5.py` isolate their optional deps.

```python
class VectorFormatHandler:
    __sunstone_handler_protocol__ = 2  # produces/consumes Asset

    # extension -> format string
    _EXTENSION_MAP = {".geojson": "geojson", ".topojson": "topojson"}
    _FORMATS = frozenset({"geojson", "topojson"})
```

- `supported_kinds() -> (AssetKind.VECTOR,)`.
- `can_read` / `can_write` resolve by extension or explicit `format=` **only** — no `geopandas` import (mirrors the module-level `_READER_FORMATS` trick in `BuiltinFormatHandler` so existence checks stay cheap and dependency-free).
- `supports_sunstone_metadata_embedding() -> True` (see D5); `supports_native_metadata_extraction() -> False`.
- All `geopandas` / `shapely` / `topojson` imports are **lazy, inside `read`/`write`**, with an `ImportError` re-raised as a clear message pointing at `pip install sunstone-py[geo]` — exactly how `ParquetFormatHandler` defers `pyarrow`.

**Read path** (both formats, stream in):

1. Read the full stream, `json.loads` it.
2. Pop the top-level `"sunstone"` foreign member, if present (D5), into a `Metadata` via `Metadata.from_jsonld`.
3. For `geojson`: build the `GeoDataFrame` from the remaining FeatureCollection (`geopandas.GeoDataFrame.from_features`, attaching CRS — default `EPSG:4326` per RFC 7946 when the file omits one).
4. For `topojson`: decode topology → GeoJSON FeatureCollection (arc-stitching) for each named object, then as step 3. **Decode library TBD — see Open Question O1.**
5. Return `Asset(payload=gdf, kind=VECTOR, metadata=meta, extras={"crs": gdf.crs})`.

**Write path** (Asset/GeoDataFrame in, stream out):

1. `geojson`: `gdf.to_json()` → JSON string → `json.loads` to a dict. (Use `to_json()` rather than `to_file()` — it is stream-friendly and avoids a temp path.)
2. `topojson`: `topojson.Topology(gdf).to_json()` → dict. Topology is computed here (shared-arc deduplication) — the whole point of TopoJSON.
3. Inject the sunstone `Metadata` as the top-level `"sunstone"` member (D5).
4. `json.dumps` to the stream.

### D3. Registration in `PluginRegistry`

Register inside the existing `_register_builtins` flow, **before** `BuiltinFormatHandler`, using the optional-dep try/except pattern already used for `NpzFormatHandler`:

```python
try:
    from .handlers_geo import VectorFormatHandler
    self._format_handlers.append(VectorFormatHandler())  # type: ignore[arg-type]
except ImportError:
    pass  # [geo] extra not installed
```

`.geojson`/`.topojson` are distinct extensions that no other built-in claims, and plain `.json` stays with `BuiltinFormatHandler`, so ordering never conflicts on extension. When the `[geo]` extra is absent, `.geojson`/`.topojson` fall through to `BlobFormatHandler`'s residual handling rather than the tabular mis-parse — an acceptable degraded mode (raw bytes + lineage, no geometry).

### D4. Plain `.json` is NOT auto-detected as geo

`.geojson` → `geojson`, `.topojson` → `topojson` by extension. A plain `.json` file stays tabular (`BuiltinFormatHandler`'s `read_json`). To read a `.json` file as vector data, the caller passes `format="geojson"`. This follows the established `.txt`/`.xls` precedent (extensions deliberately not auto-claimed to avoid ambiguity). Documented in the facade docstrings.

### D5. Embed `Metadata` as a top-level `"sunstone"` foreign member

On write, the sunstone `Metadata` is serialized via `Metadata.to_jsonld()` and attached as a single top-level member named `"sunstone"`; on read it is popped and parsed back. This gives GeoJSON/TopoJSON the same embedded-lineage round-trip the Parquet handler provides.

This is safe and was verified against primary sources:

- **RFC 7946 §6.1** explicitly permits foreign members: *"Members not described in this specification ('foreign members') MAY be used in a GeoJSON document."*
- **GDAL/OGR** (QGIS, geopandas via pyogrio/fiona) *preserves* foreign members by default (NATIVE_DATA round-trip).
- **Leaflet** and **OpenLayers** ignore unknown top-level members (verified against Leaflet source — no whitelist, no throw, no warn).
- The member name avoids the two reserved names RFC 7946 forbids at the `FeatureCollection` level (`geometry`, `properties`). `"sunstone"` is safe.

`datasets.yaml` remains the authoritative metadata store. Embedding is belt-and-suspenders: the asymmetric round-trip (JS tools drop the member on re-export; GDAL keeps it) costs us nothing because `datasets.yaml` is the source of truth.

### D6. `sunstone.geopandas` facade and `GeoDataFrame` wrapper

A new module `sunstone/geopandas.py` plus a lineage-tracking `GeoDataFrame` wrapper (new `sunstone/dataframe_geo.py`), parallel to `sunstone.pandas` / `sunstone.dataframe.DataFrame`.

- Usage: `from sunstone import geopandas as gpd`, then `gpd.read_file('x.geojson')` (auto-detect by extension), plus explicit `gpd.read_geojson(...)` / `gpd.read_topojson(...)`. Same project-path resolution (`set_project_path` / `use_project_path` / `project_path=`) and `datasets.yaml` registration as the `pandas` facade.
- `sunstone.geopandas.GeoDataFrame` wraps an `Asset(kind=VECTOR, payload=geopandas.GeoDataFrame)`. `.data` → the `GeoDataFrame`, `.metadata` → the unified `Metadata`, `.asset` → the envelope; lineage flows through operations, mirroring the tabular wrapper.
- Writers `gdf.to_geojson(...)` / `gdf.to_topojson(...)` require `slug` + `name` for new outputs (settable via `metadata.slug`/`metadata.name` or passed as params), identical to `to_csv`.
- The TABULAR-only guard in `DataFrame.read_dataset` (`dataframe.py:454`) is left untouched; the geo wrapper has its own VECTOR-accepting read path. The two wrappers share the `Metadata`/lineage machinery but enforce their own kinds. This keeps the tabular facade's invariant (`as_table()` always valid) intact.

### D7. `[geo]` optional extra

In `pyproject.toml`:

```toml
[project.optional-dependencies]
geo = ["geopandas", "shapely", "pyogrio", "topojson"]
```

Strictly optional, never a base dependency (per the project's dependency-hygiene preference). `pyogrio` is geopandas's fast IO engine; `topojson` provides TopoJSON encoding. The exact TopoJSON *decode* dependency is Open Question O1.

## Open Questions

- **O1. TopoJSON decode library.** `topojson` (mattijn/topojson) cleanly covers *encoding* (GeoDataFrame → TopoJSON). The decode direction (TopoJSON → features/GeoDataFrame) needs a verified library or a small hand-rolled arc-stitcher. To be resolved at plan time before committing to the `[geo]` extra's exact contents — do not guess. Candidates to evaluate: a dedicated decoder package vs. ~100 lines of arc-stitching against the TopoJSON 1.0 spec.

## Testing

TDD throughout. Geo-dependent tests skip when the `[geo]` extra is not installed (`pytest.importorskip("geopandas")`).

- `tests/test_handlers_geo.py`: GeoJSON round-trip (geometry + CRS preserved); TopoJSON round-trip (topology computed on write, geometry recovered on read); `"sunstone"` foreign-member metadata round-trip; `.json` is NOT claimed by the vector handler; explicit `format="geojson"` on a `.json` path works; missing-`[geo]` `ImportError` message names the extra.
- `tests/test_geopandas.py`: `read_file` / `read_geojson` / `read_topojson` via the facade; project-path resolution; `datasets.yaml` registration; lineage flow through an operation; `to_geojson`/`to_topojson` require `slug`+`name`.
- `tests/test_asset` (existing): `as_vector()` accessor and `IncompatibleAssetKindError` on mismatch; VECTOR `derive` policy (CRS kept vs. cleared).

## CHANGELOG

One line under `[Unreleased]`:

```
- Added: GeoJSON and TopoJSON read/write via the optional [geo] extra.
```
