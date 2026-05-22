# File Formats

Sunstone wraps every payload — tabular, raster, array, tile — in a
uniform `Asset` envelope and dispatches I/O through a plugin registry.
This page covers the built-in handlers, where each one stores its
metadata, and how to extend Sunstone with your own formats.

## Tabular formats

| Format  | Extensions       | Read | Write | Embedded metadata           | Format-specific features          |
|---------|------------------|------|-------|-----------------------------|-----------------------------------|
| CSV     | `.csv`           | yes  | yes   | no — sidecar YAML           | `dialect:` block                  |
| TSV     | `.tsv`, `.txt`   | yes  | no    | no — sidecar YAML           | tab delimiter is fixed            |
| JSON    | `.json`          | yes  | no    | no — sidecar YAML           | —                                 |
| Excel   | `.xlsx`, `.xls`  | yes  | no    | no — sidecar YAML           | —                                 |
| Parquet | `.parquet`       | yes  | yes   | **yes** — JSON-LD in footer | self-contained lineage            |

"Sidecar YAML" means the human-authored `datasets.yaml` plus the
auto-generated `datasets.lock.yaml` carry the lineage and field metadata.
For Parquet, the same JSON-LD that would live in the sidecar is also
embedded in the file footer, so a Parquet file can travel without the
sidecar and still describe itself.

## Non-tabular formats

| Format          | Extensions                       | Kind                  | Extra            | Embedded metadata                          |
|-----------------|----------------------------------|-----------------------|------------------|--------------------------------------------|
| NumPy `.npz`    | `.npz`                           | `AssetKind.ARRAY`     | built-in         | **yes** — JSON-LD entry in the archive     |
| Zarr            | `.zarr` (directory store)        | `AssetKind.ARRAY`     | `sunstone-py[zarr]`  | **yes** — JSON-LD in root group `.attrs` |
| HDF5 / NetCDF-4 | `.h5`, `.hdf5`, `.he5`, `.nc`, `.nc4` | `AssetKind.ARRAY` | `sunstone-py[hdf5]`  | **yes** — JSON-LD in root attribute      |

See [Tensors](tensors.md) for the array workflow and per-variable
component metadata. NetCDF-3 (classic) is out of scope — only NetCDF-4,
which is HDF5 underneath, is supported.

Raster (GeoTIFF) and tile-pyramid (XYZ/MBTiles) handlers are on the
roadmap — see [Images](images.md) and [Tile pyramids](nbtiles.md).

## Reading and writing

There are two equivalent entry points: the pandas-compatible wrapper
(tabular only) and the kind-agnostic `sunstone.read()` / `sunstone.write()`
pair (any kind).

### Pandas wrapper (tabular only)

```python
from sunstone import pandas as pd

df = pd.read_csv('inputs/data.csv')      # csv, tsv (via .tsv/.txt)
df = pd.read_excel('inputs/data.xlsx')   # xlsx, xls
df = pd.read_json('inputs/data.json')    # json
df = pd.read_dataset('my-slug')          # any format; uses datasets.yaml location
```

For writes, only CSV and Parquet are supported by built-in handlers:

```python
df.to_csv('outputs/result.csv', slug='result', name='Result')
df.to_parquet('outputs/result.parquet', slug='result', name='Result')
```

There is no `to_tsv`, `to_json`, or `to_excel` — write a CSV with a tab
dialect if you need TSV (see below), or register a third-party
`FormatHandler` plugin for the others.

### Kind-agnostic `sunstone.read()` / `sunstone.write()`

```python
import sunstone as ss

asset = ss.read('inputs/era5_2024.zarr')  # any kind, any handler
arrays = asset.as_array()                  # dict[str, ndarray]

child = asset.derive(
    {k: v.mean(axis=0) for k, v in arrays.items()},
    slug='era5-2024-yearly-mean',
    name='ERA5 2024 annual mean',
)
ss.write(child, 'outputs/era5_yearly.zarr')
```

`sunstone.read()` returns an `Asset`; `sunstone.write()` accepts one.
Dispatch order is:

1. Explicit `kind=` / `format=` arguments.
2. The `format:` field on the matching `datasets.yaml` entry (resolved
   by location).
3. The path itself — directory paths route through the
   `StoreFormatHandler` registry, single-file paths route through both
   the store and the stream registries (in that order, so HDF5/NetCDF-4
   handlers can claim them).

Writing an `Asset` whose `kind` does not match the destination handler
raises `IncompatibleAssetKindError`.

## Where metadata lives

Sunstone tracks two layers of metadata:

- **Dataset-level**: name, slug, description, license, sources, RDF
  prefixes, custom properties, package membership.
- **Field-level**: per-column description, unit, source, derivation, type.

How that metadata is stored depends on the output format:

### CSV / TSV / JSON / Excel (sidecar formats)

The file on disk is just the data. All Sunstone metadata lives in the
sidecar pair:

- `datasets.yaml` — human-authored: registrations, descriptions, RDF
  properties, license, dialect overrides.
- `datasets.lock.yaml` — auto-generated on write: lineage (PROV-O
  Activities, Agents, sources, hashes), field derivations, denormalized
  source attribution and license.

If you ship one of these files without the YAML pair, the consumer loses
the lineage record.

### Parquet (self-describing)

Sunstone embeds the full JSON-LD metadata document (the same one written
to `datasets.lock.yaml`) into the Parquet schema metadata under the
`sunstone` key. On read, this is decoded back into `df.metadata` (a
`Metadata` object), so a Parquet file is fully self-describing.

The sidecar YAML is still written and remains the source of truth inside
the project; the embedded copy exists for handoff and archival.

You can inspect the embedded metadata directly:

```python
import pyarrow.parquet as pq
table = pq.read_table('outputs/result.parquet')
raw = table.schema.metadata[b'sunstone']  # JSON-LD bytes
```

Programmatically the same data is available via `Metadata.from_jsonld()`
/ `Metadata.to_jsonld()`.

## CSV dialect

CSV files are not always plain comma-separated UTF-8. The `dialect:`
block on a dataset entry in `datasets.yaml` controls how the file is
parsed and written without forcing every call site to pass kwargs:

```yaml
inputs:
  - name: Semi-Colon Sample
    slug: semi
    location: inputs/semi.csv
    dialect:
      delimiter: ";"
      quoteChar: "'"
      header: true
```

Fields (all optional, matching the Frictionless `csv` dialect):

| Field       | Default | Meaning                                                          |
|-------------|---------|------------------------------------------------------------------|
| `delimiter` | `,`     | Field separator. Translates to pandas `sep`.                     |
| `quoteChar` | `"`     | Character used to quote fields containing special characters.    |
| `header`    | `true`  | Whether the file has (read) or should be written with (write) a header row. |

The dialect applies both on read and on write — the same dataset reads
back what it wrote.

**Caller kwargs always win.** If you pass `sep=`, `quotechar=`, or
`header=` directly to `read_csv` / `to_csv`, those values override the
dialect block. The dialect only fills in keys the caller did not specify.

An empty block (`dialect: {}`) is valid and equivalent to plain pandas
defaults.

### TSV via CSV dialect

`.tsv` and `.txt` files are read with `sep='\t'` automatically. To
*write* a tab-delimited file, use `to_csv` with a `.tsv` path and a
dialect (or pass `sep='\t'` explicitly):

```yaml
outputs:
  - slug: tab-output
    location: outputs/result.tsv
    dialect:
      delimiter: "\t"
```

## Format detection

Format detection follows this order:

1. An explicit `format=` argument on `read_dataset` (`csv`, `json`,
   `excel`, `parquet`, `tsv`).
2. The file extension (`.csv` → csv, `.tsv`/`.txt` → tsv, `.json` →
   json, `.xlsx`/`.xls` → excel, `.parquet` → parquet).
3. For `read_csv` the format is always `csv`; for `read_excel` always
   `excel`; for `read_json` always `json`.

URLs are supported wherever local paths are — the URL handler reads the
bytes, then the format handler parses them.

## Extending Sunstone with a new format

There are two handler protocols depending on what your format needs:

### Stream-based: `FormatHandler`

Use for single-file formats whose library can read or write a byte
stream (CSV, JSON, Parquet, `.npz`):

```python
class FormatHandler(Protocol):
    def supports_metadata(self) -> bool: ...
    def can_read(self, path: str, format: str | None) -> bool: ...
    def can_write(self, path: str, format: str | None) -> bool: ...
    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
    def read(self, stream, **kwargs) -> Asset: ...
    def write(self, asset: Asset, stream, **kwargs) -> None: ...
```

Return `True` from `supports_metadata()` if your format can embed
Sunstone's JSON-LD document (see `ParquetFormatHandler` and
`NpzFormatHandler` for worked examples); otherwise the sidecar YAML
carries the metadata as usual. `supported_kinds()` lets the registry
reject mismatched assets at write time.

### Store-based: `StoreFormatHandler`

Use for formats whose library needs a real path or directory (HDF5,
Zarr, MBTiles, partitioned Parquet):

```python
class StoreFormatHandler(Protocol):
    __sunstone_handler_protocol__: int  # must be 2

    def supports_native_metadata_extraction(self) -> bool: ...
    def supports_sunstone_metadata_embedding(self) -> bool: ...
    def can_read_store(self, location: ResourceLocation, format: str | None) -> bool: ...
    def can_write_store(self, location: ResourceLocation, format: str | None) -> bool: ...
    def supported_kinds(self) -> tuple[AssetKind, ...]: ...
    def read(self, location: ResourceLocation, **kwargs) -> Asset: ...
    def write(self, asset: Asset, location: ResourceLocation, **kwargs) -> None: ...
```

`ResourceLocation` wraps a path that may refer to a single file or a
directory. Use `loc.is_dir()`, `loc.list(glob)`, `loc.subpath()`, and
`loc.as_path()` for random access, partition enumeration, or chunked
reads. Single-file store handlers (HDF5, NetCDF-4) are dispatched before
the stream registry, so they can claim paths like `inputs/data.h5`.

### Registration

Register the class via the `sunstone.plugins` entry point group in your
package's `pyproject.toml`:

```toml
[project.entry-points."sunstone.plugins"]
my_format = "my_pkg.handlers:MyFormatHandler"
```

External plugins are discovered at registry construction and take
priority over the built-ins.

## See also

- [Core Concepts](concepts.md) — `datasets.yaml` structure and lineage.
- [pandas](pandas.md) — tabular workflow details.
- [Tensors](tensors.md) — array workflow (`.npz`, Zarr, HDF5/NetCDF-4).
- [Images](images.md) — raster workflow (roadmap).
- [Tile pyramids (nbtiles)](nbtiles.md) — pre-tiled multi-resolution data.
- [Frictionless Data](frictionlessdata.md) — the Table Dialect
  specification that Sunstone's `dialect:` block follows.
- [Data Package Spec](datapackage.md) — how dialects appear in the
  generated `datapackage.json`.
