# geopandas

Vector geospatial data backed by a geopandas `GeoDataFrame`. This is the
payload for GeoJSON and TopoJSON sources, mirroring the tabular
[pandas](pandas.md) kind for geometries and feature attributes.

- **AssetKind:** `AssetKind.GEOFEATURES`
- **Payload:** `geopandas.GeoDataFrame`
- **Typed accessor:** `Asset.as_geofeatures() -> geopandas.GeoDataFrame`
- **GeoDataFrame facade:** `sunstone.geopandas` (drop-in geopandas-style wrapper)

## Status

Supported via the optional `[geo]` extra. Install it with:

```bash
pip install sunstone-py[geo]
```

GeoJSON and TopoJSON are handled by the in-tree `GeoFeaturesFormatHandler`;
HTTP(S), local file, GCS, and S3/R2 URLs are handled by the same in-tree URL
handlers used for tabular data.

The `sunstone.geopandas` module always imports — even without the extra — so
code can reference it unconditionally. The geopandas/shapely dependency is only
required when you actually read or write geo data; without `[geo]` installed,
the format handler is not registered and read/write operations raise a clear
error pointing you at `pip install sunstone-py[geo]`.

## Two entry points

As with tabular data, there are two equivalent entry points for geo I/O. Pick
whichever fits your code.

### `sunstone.read()` / `sunstone.write()` — Asset-native

```python
import sunstone as ss

asset = ss.read("inputs/regions.geojson")
assert asset.kind is ss.AssetKind.GEOFEATURES

gdf = asset.as_geofeatures()       # geopandas.GeoDataFrame
populated = gdf[gdf["population"] > 10_000]

child = asset.derive(
    populated,
    slug="dense-regions",
    name="Densely Populated Regions",
)
ss.write(child, "outputs/dense.geojson")
```

`sunstone.read()` returns an `Asset`; `sunstone.write()` accepts one. The kind
is inferred from the registered format in `datasets.yaml`. If you try to
`write()` an asset whose kind does not match the destination slot, you get
`IncompatibleAssetKindError`.

### `sunstone.geopandas` — drop-in geopandas

```python
from sunstone import geopandas as gpd
import sunstone
from pathlib import Path

sunstone.set_project_path(Path.cwd())

gdf = gpd.read_geojson("regions")          # by registered slug or path
topo = gpd.read_topojson("regions.topojson")
auto = gpd.read_file("regions")            # format auto-detected from the dataset

dense = gdf.data[gdf.data["population"] > 10_000]
gpd.GeoDataFrame(gdf.asset.derive(
    dense, slug="dense-regions", name="Densely Populated Regions",
)).to_geojson("outputs/dense.geojson")
```

The read helpers resolve a slug or path against `datasets.yaml` and return a
`sunstone.geopandas.GeoDataFrame` facade over a `GEOFEATURES` asset:

- `read_geojson(slug_or_path, project_path=None)` — read GeoJSON
- `read_topojson(slug_or_path, project_path=None)` — read TopoJSON
- `read_file(slug_or_path, project_path=None)` — auto-detect format from the
  dataset's `format` field (falling back to the `.topojson` extension, else GeoJSON)

The facade exposes:

- `.data` — the underlying `geopandas.GeoDataFrame`
- `.asset` — the wrapped `Asset`
- `.metadata` — the unified metadata container
- `.to_geojson(path, slug=..., name=...)` — write GeoJSON and register
- `.to_topojson(path, slug=..., name=...)` — write TopoJSON and register

Writing a new output requires both `slug` and `name` (set on `metadata`
beforehand or passed to the write call), exactly as for tabular outputs.

Both routes record identical lineage; pick `sunstone.geopandas` for code that
should look like geopandas and the Asset API for code that needs to be uniform
across kinds.

## Coordinate reference system

`Asset.crs` is a convenience accessor over `extras["crs"]`. GeoJSON is
canonically WGS 84 (`EPSG:4326`) per RFC 7946; the handler round-trips the
declared CRS through `extras` so it survives read/write.

## Field-level metadata

Feature-attribute (column) metadata works the same as for tabular data — see
[pandas](pandas.md#field-level-metadata). The `geometry` column carries a
dedicated field value-type registered by the geo handler, so it is recognized
as a shapely geometry rather than an opaque object.

## Lineage

Lineage flows through derivations exactly as for tabular assets. Reads populate
sources; `derive()` records the parent assets and operations. See
[Core Concepts](concepts.md) for the full lineage model.

## Extras

`GEOFEATURES` assets use `extras["crs"]` to carry the coordinate reference
system. TopoJSON round-trips its topology through the handler; the user-facing
payload is always the decoded `geopandas.GeoDataFrame`.

## See also

- [Core Concepts](concepts.md) — lineage, strict mode, dataset registration
- [API Reference](api.md) — full API surface
- [pandas](pandas.md) — tabular payload and the analogous facade
- [Tile pyramids (nbtiles)](nbtiles.md) — pre-tiled geospatial data (roadmap)
