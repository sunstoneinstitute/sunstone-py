# Tensors (n-D variable arrays)

Multi-variable n-dimensional arrays — climate reanalysis datasets,
neuroimaging volumes, simulation output, any data shaped as a
labelled collection of N-D NumPy arrays. The native representation
is `dict[str, numpy.ndarray]` keyed by variable name.

- **AssetKind:** `AssetKind.ARRAY`
- **Payload:** `dict[str, numpy.ndarray]`
- **Typed accessor:** `Asset.as_array() -> dict[str, numpy.ndarray]`
- **Status:** Asset envelope ready. NumPy `.npz` is supported today;
  Zarr and NetCDF handlers are on the roadmap.

## Why a dict, not a single ndarray

Most real-world n-D scientific data comes in *several* arrays that
share coordinates — `(temperature, pressure, humidity)` over the same
`(time, lat, lon)` grid. Modelling the payload as a dict makes that
shared-coordinate structure explicit and avoids forcing users to pack
unrelated variables into a single higher-rank array.

For raster imagery — bands of a single 2D scene — use
[`AssetKind.RASTER`](images.md) instead. RASTER is for one ndarray;
ARRAY is for many.

## What's in place today

- `AssetKind.ARRAY` is a first-class kind in the envelope.
- `Asset.as_array()` returns the dict and raises
  `IncompatibleAssetKindError` on kind mismatch.
- Per-variable metadata flows through `Metadata.component_metadata`
  with `component_kind="variable"` — same shape as for tabular
  columns, raster bands, and tile layers.
- **NumPy `.npz`** — single-file zip of `.npy` arrays. Stream-based
  `FormatHandler` that round-trips the sunstone `Metadata` blob (slug,
  name, description, RDF prefixes, custom properties, and per-variable
  `component_metadata`) inside the archive under a reserved key.

## What's coming

Two further handlers cover the rest of the common formats:

1. **Zarr** — chunked, compressed n-D arrays in a directory or cloud
   store. Uses `StoreFormatHandler` because the data is spread across
   many objects and is opened, not streamed.
2. **NetCDF** / HDF5 — single-file but with random access semantics;
   handler choice depends on whether the underlying library is
   stream-friendly.

## Reading a tensor

```python
import sunstone as ss

asset = ss.read("inputs/era5_2024.npz")
assert asset.kind is ss.AssetKind.ARRAY

vars = asset.as_array()
temp = vars["temperature"]   # ndarray, shape (time, lat, lon)
pressure = vars["pressure"]
```

Zarr and NetCDF use the same dispatch — once those handlers land, swap
the extension and the rest of the code is unchanged.

## Writing a derived tensor

```python
import sunstone as ss

monthly = {
    name: arr.reshape(12, -1, *arr.shape[1:]).mean(axis=1)
    for name, arr in source.as_array().items()
}
child = source.derive(
    monthly,
    slug="era5-2024-monthly",
    name="ERA5 2024, monthly means",
)
ss.write(child, "outputs/era5_monthly.npz")
```

## Component metadata per variable

Each variable's dtype, units, description, and any RDF triples live in
`Metadata.component_metadata`:

```python
from sunstone.lineage import ComponentSchema

asset.metadata.component_metadata["temperature"] = ComponentSchema(
    name="temperature",
    component_kind="variable",
    dtype="float32",
    units="kelvin",
    description="2-metre air temperature",
)
```

Units are Pint-parsable strings (e.g. `"kelvin"`, `"m/s"`, `"W/m**2"`)
and emit as `qudt:unit` IRIs in JSON-LD output.

## Unit-aware compute (planned)

The intended pattern for unit-aware numeric work on tensor variables:

```python
# Roadmap — gated on the units follow-up spec
T_kelvin = asset.metadata.component_metadata["temperature"].as_quantity()
T_celsius = T_kelvin.to("celsius")
```

`as_quantity()` returns a `unyt.unyt_array` by default (stronger NumPy
subclass integration) or a `pint.Quantity` with
`as_quantity(backend="pint")`.

## Extras

ARRAY assets commonly carry:

| key             | type    | purpose                                          |
|-----------------|---------|--------------------------------------------------|
| `dimensions`    | dict    | Dimension labels, e.g. `{"time": 365, "lat": 720, "lon": 1440}` |
| `coordinates`   | dict    | Coordinate arrays for each dimension             |
| `chunks`        | dict    | Chunk shape per variable (Zarr-style)            |

## Design reference

See the [Asset envelope design
spec](superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md)
for the kind taxonomy and component-metadata model, and the
[open-decisions log](superpowers/specs/2026-05-12-asset-envelope-open-decisions.md)
for the stream-vs-store handler dispatch rationale.

## See also

- [Images](images.md) — single-payload rasters
- [Tile pyramids (nbtiles)](nbtiles.md) — pre-tiled multi-resolution data
- [API Reference](api.md)
