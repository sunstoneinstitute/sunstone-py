# Images (raster ndarrays)

Single-payload raster data — satellite imagery, photographs, scanned
documents, gridded climate fields. The native representation is a
NumPy `ndarray` shaped `(bands, height, width)` or `(height, width)`
for single-band data.

- **AssetKind:** `AssetKind.RASTER`
- **Payload:** `numpy.ndarray`
- **Typed accessor:** `Asset.as_raster() -> numpy.ndarray`
- **Status:** Asset envelope ready; first format handler (GeoTIFF) is
  on the roadmap.

## What's in place today

- `AssetKind.RASTER` is a first-class kind in the envelope.
- `Asset.as_raster()` returns the `ndarray` and raises
  `IncompatibleAssetKindError` if you call it on a non-raster asset.
- `Asset.profile` and `Asset.crs` are convenience read-only accessors
  over `extras["profile"]` and `extras["crs"]`.
- The **RASTER derive policy** automatically invalidates the stale
  profile fields (`width`, `height`, `count`, `dtype`) when you derive
  a child asset whose shape or dtype differs from the parent. This
  keeps `rasterio` writers from emitting headers that disagree with
  the actual pixel data.
- Component metadata for raster bands flows through
  `Metadata.component_metadata` with `component_kind="band"`.

## What's coming

A first concrete handler — GeoTIFF — is the next planned step. After
that, Zarr-based rasters via `StoreFormatHandler`, then any other
single-file raster format (NetCDF, HDF5 slices, EXR) as plugins.

The units story is locked but the implementation is gated on a
follow-up RDF/units spec. Bands will carry Pint-parsable units in
`ComponentSchema.units` and expose `band.as_quantity()` for unit-aware
compute.

## Reading a raster (planned API)

```python
import sunstone as ss

asset = ss.read("inputs/sentinel2_b04.tif")
assert asset.kind is ss.AssetKind.RASTER

arr = asset.as_raster()            # ndarray, shape (bands, H, W)
profile = asset.profile            # rasterio-style dict
crs = asset.crs
```

## Writing a derived raster

```python
import numpy as np
import sunstone as ss

ndvi = (nir.as_raster() - red.as_raster()) / (nir.as_raster() + red.as_raster())

child = nir.derive(
    ndvi,
    slug="ndvi-2024",
    name="NDVI 2024",
    derived_from=[nir, red],          # multi-parent lineage
)
ss.write(child, "outputs/ndvi.tif")
```

`derive()` records `prov:wasDerivedFrom` for each parent. Because the
shape and dtype may differ from the parent, the RASTER derive policy
clears the stale `profile` fields so the writer recomputes them from
the new payload.

## Extras

Raster assets typically carry these `extras` keys:

| key       | type     | source              | purpose                                            |
|-----------|----------|---------------------|----------------------------------------------------|
| `profile` | `dict`   | `rasterio` profile  | GeoTIFF header round-trip                          |
| `crs`     | `str`/object | rasterio CRS     | Coordinate reference system                        |
| `transform` | affine | `rasterio.transform` | Pixel-to-world transform                          |

These are kind-specific accessory info — never copies of the payload.

## Bands and component metadata

Each band's description, units, dtype, and any RDF triples live in
`Metadata.component_metadata["<band_name>"]`. This is the same shape
used for tabular columns, array variables, and tile layers — so
discovery code reads band metadata via `ComponentSchema` uniformly.

```python
asset.metadata.component_metadata["B04"] = ComponentSchema(
    name="B04",
    component_kind="band",
    dtype="uint16",
    units=None,
    description="Sentinel-2 red band reflectance, scaled by 10000",
)
```

## Design reference

The kind taxonomy, derive-policy semantics, and units plan are
documented in the [Asset envelope design
spec](superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md).

## See also

- [tensors](tensors.md) — multi-variable n-D arrays (NetCDF, Zarr)
- [Tile pyramids (nbtiles)](nbtiles.md) — pre-tiled multi-resolution rasters
- [API Reference](api.md)
