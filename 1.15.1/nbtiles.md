# Tile pyramids (nbtiles)

Pre-tiled, multi-resolution geospatial data — MBTiles, XYZ tile
directories, vector tiles. The native representation is a tile-pyramid
descriptor object the user opens to fetch tiles by `(z, x, y)`; the
underlying I/O is store-based (a SQLite file, a directory, or an
HTTP endpoint), not a single byte stream.

- **AssetKind:** `AssetKind.TILES`
- **Payload:** tile-pyramid descriptor object (format-specific)
- **Typed accessor:** `Asset.as_tiles() -> Any`
- **Handler protocol:** `StoreFormatHandler` (always store-based)
- **Status:** Asset envelope and `StoreFormatHandler` protocol ready;
  MBTiles and XYZ handlers are on the roadmap.

## What's in place today

- `AssetKind.TILES` is a first-class kind in the envelope.
- `Asset.as_tiles()` returns the payload and raises
  `IncompatibleAssetKindError` on kind mismatch.
- `Asset.crs` is a convenience accessor over `extras["crs"]`.
- `StoreFormatHandler` protocol exists in `sunstone.resource`,
  alongside `ResourceLocation` for describing where the tile store
  lives (path, S3 bucket, HTTP base).
- `datasets.yaml`'s `format` field is the primary dispatch signal,
  so `format: mbtiles` selects the MBTiles handler explicitly
  regardless of file extension.

## What's coming

The two canonical handlers are:

1. **MBTiles** — single SQLite file with random tile access. The
   handler opens the file, exposes a tile-fetch callable, and
   round-trips zoom range and CRS through `extras`.
2. **XYZ** — directory tree of `{z}/{x}/{y}.png` (or `.pbf`) tiles.
   The handler enumerates available zoom levels and resolves
   individual tiles by coordinate.

Vector tile formats (Mapbox Vector Tiles via `pbf`) layer on top of
either store.

## Reading a tile pyramid (planned API)

```python
import sunstone as ss

asset = ss.read("inputs/basemap.mbtiles")
assert asset.kind is ss.AssetKind.TILES

tiles = asset.as_tiles()
tile = tiles.fetch(z=10, x=523, y=400)   # bytes / decoded image
```

The descriptor object opens the store lazily, so reading the asset
does not pull all tiles into memory.

## Writing tiles

Tile pyramids are usually written by an external rendering pipeline
(`gdal2tiles`, `tippecanoe`, custom render jobs). The sunstone-py
handler's job is to wrap that output, record its location in
`datasets.yaml`, and propagate lineage from the source rasters or
vectors.

```python
child = source_raster.derive(
    tile_pyramid_descriptor,
    slug="basemap-2024",
    name="Basemap tiles, 2024",
    kind=ss.AssetKind.TILES,
    extras_updates={"zoom_min": 0, "zoom_max": 14, "crs": "EPSG:3857"},
)
ss.write(child, "outputs/basemap.mbtiles")
```

`derive()` collapses the in-memory tile pyramid through to provenance
metadata; the actual tile bytes are typically already written by the
renderer and the handler just records the manifest.

## Extras

Tile assets typically carry:

| key        | type     | purpose                                         |
|------------|----------|-------------------------------------------------|
| `zoom_min` | `int`    | Lowest zoom level available in the pyramid      |
| `zoom_max` | `int`    | Highest zoom level available                    |
| `crs`      | `str`    | Coordinate reference system (typically `EPSG:3857` for web tiles) |
| `bounds`   | tuple    | `(minx, miny, maxx, maxy)` covered by the pyramid |
| `tile_format` | `str` | `"png"`, `"jpg"`, `"webp"`, `"pbf"`             |

## Layers as components

A vector tile pyramid often carries multiple layers (roads, water,
buildings). Each layer is a `ComponentSchema` entry with
`component_kind="layer"`, mirroring the way raster bands and tabular
columns are described. Discovery code can list a tile asset's layers
without knowing the tile format.

## Design reference

See the
[design spec](superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md)
for the `StoreFormatHandler` contract and the `ResourceLocation`
dataclass, and the
[open-decisions log](superpowers/specs/2026-05-12-asset-envelope-open-decisions.md)
for the format-vs-extension dispatch rationale.

## See also

- [Images](images.md) — single-payload rasters (the input to a tile renderer)
- [tensors](tensors.md) — n-D variable arrays
- [API Reference](api.md)
