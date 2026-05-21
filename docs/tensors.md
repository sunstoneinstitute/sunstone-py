# Tensors (n-D variable arrays)

Multi-variable n-dimensional arrays — climate reanalysis datasets,
neuroimaging volumes, simulation output, any data shaped as a
labelled collection of N-D NumPy arrays. The native representation
is `dict[str, numpy.ndarray]` keyed by variable name.

- **AssetKind:** `AssetKind.ARRAY`
- **Payload:** `dict[str, numpy.ndarray]`
- **Typed accessor:** `Asset.as_array() -> dict[str, numpy.ndarray]`
- **Status:** Asset envelope ready. NumPy `.npz`, Zarr (local
  directory store), and HDF5 / NetCDF-4 are all supported today.

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
- **Zarr** directory stores (local filesystem) round-trip via
  `ZarrStoreHandler`. Install with `pip install sunstone-py[zarr]`.
  The handler embeds the sunstone `Metadata` blob as JSON-LD in the
  root group's `.attrs` under key `"sunstone"`, and projects each
  variable's `units` / `long_name` / `description` onto the array's
  `.attrs` for ecosystem interop (xarray, Panoply, ncview, ...).
  Works with both zarr v2 (`>=2.18`) and zarr v3.
- **HDF5 / NetCDF-4 handler** (`sunstone.handlers_hdf5.Hdf5StoreHandler`)
  round-trips `dict[str, numpy.ndarray]` payloads plus the full
  sunstone `Metadata` blob (stored as JSON-LD in the root HDF5
  attribute `sunstone`). Supports `.h5`, `.hdf5`, `.he5`, `.nc`,
  `.nc4` extensions. Install with `sunstone-py[hdf5]`. NetCDF-3
  (classic) is out of scope — only NetCDF-4, which is HDF5
  underneath, is supported. Per-variable `ComponentSchema.units`
  and `ComponentSchema.description` are also written as CF-style
  HDF5 attributes (`units`, `long_name`, `description`) so xarray,
  ncdump, Panoply, MATLAB and other CF-aware tools read the same
  file without sunstone in the loop.

## What's coming

- **Remote Zarr stores** (`gs://`, `s3://`) — the v1 Zarr handler is
  local-directory only. Object-store routing through the URLHandler
  registry is planned.

## Reading a tensor

```python
import sunstone as ss

asset = ss.read("inputs/era5_2024.zarr")
assert asset.kind is ss.AssetKind.ARRAY

vars = asset.as_array()
temp = vars["temperature"]   # ndarray, shape (time, lat, lon)
pressure = vars["pressure"]
```

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
ss.write(child, "outputs/era5_monthly.zarr")
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
