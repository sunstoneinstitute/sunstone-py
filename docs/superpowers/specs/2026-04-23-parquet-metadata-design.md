# Parquet Metadata Embedding & Hash Cleanup

**Date:** 2026-04-23
**Version:** sunstone-py 1.8.0

## Problem

Parquet files written by `sunstone.pandas` contain no metadata. Lineage,
field descriptions, RDF properties, and provenance exist only in
`datasets.yaml` / `datasets.lock.yaml`. When a Parquet file travels
outside its project (shared with a collaborator, uploaded to a catalog),
all context is lost.

Additionally, the hash system has critical inconsistencies: the CLI and
DataFrame write paths both write to a field called `content_hash` but
compute fundamentally different hashes (file bytes vs. pickled DataFrame),
use inconsistent prefix formats (`sha256:...` vs. bare hex), and silently
overwrite each other.

## Design

Three interrelated changes:

1. **Metadata in Parquet** -- embed a self-contained JSON-LD document in
   the Parquet file footer.
2. **Hash cleanup** -- split `content_hash` into `file_hash` and
   `data_hash` with consistent `sha256:` prefixes.
3. **`min_sunstone_version`** -- compatibility field in `datasets.yaml`
   to manage schema evolution.

## 1. FormatHandler Protocol Changes

The `FormatHandler` protocol gains one new method:

```python
class FormatHandler(Protocol):
    def supports_metadata(self) -> bool: ...  # NEW

    def can_read(self, path: str, format: str | None) -> bool: ...
    def read(self, stream: BinaryIO, **kwargs) -> pd.DataFrame: ...
    def can_write(self, path: str, format: str | None) -> bool: ...
    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs) -> None: ...
```

`supports_metadata()` returns `True` if the handler can embed/extract
metadata in the file format. It is a method (not an attribute) to prevent
modification.

### Metadata transport convention

Metadata travels between the Sunstone DataFrame and the format handler
via `df.attrs["sunstone_metadata"]`:

- **Write path:** Before calling `format_writer.write()`, the Sunstone
  DataFrame attaches `self.metadata` to `self.data.attrs["sunstone_metadata"]`.
  Handlers where `supports_metadata()` returns `True` check for it and
  embed it. Others ignore it. After the handler returns, the transport
  copy is removed from attrs.
- **Read path:** Handlers where `supports_metadata()` returns `True`
  extract metadata from the file and set `df.attrs["sunstone_metadata"]`
  (as a `Metadata` object) before returning. The Sunstone DataFrame layer
  merges it into `self.metadata`.

`df.attrs` is a transport mechanism, not the backing store for metadata.
The Sunstone DataFrame's `self.metadata` remains the authoritative
in-memory store. `pd.DataFrame.attrs` does not reliably propagate through
pandas operations like `groupby`, `merge`, or `concat`.

### BuiltinFormatHandler split

The existing `BuiltinFormatHandler` (CSV, JSON, Excel, Parquet, TSV)
is split:

- `BuiltinFormatHandler` -- CSV, JSON, Excel, TSV.
  `supports_metadata()` returns `False`.
- `ParquetFormatHandler` -- Parquet only.
  `supports_metadata()` returns `True`.

Both are registered in the plugin registry. `ParquetFormatHandler` takes
priority for `.parquet` files.

## 2. Parquet Metadata Format

The `ParquetFormatHandler` embeds a JSON-LD document under the
`b"sunstone"` key in the Parquet schema metadata (via pyarrow), alongside
the existing `b"pandas"` key.

### Example document

```json
{
  "@context": {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "si": "https://sunstone.institute/ns/",
    "schema": "http://schema.org/"
  },
  "@type": "dcat:Distribution",
  "si:version": "1.0",
  "dct:identifier": "climate-summary",
  "dct:title": "Climate Summary",
  "dct:description": "Aggregated climate indicators by region",
  "dct:created": "2026-04-23T14:30:00",
  "si:dataHash": "sha256:abc123...",
  "prov:wasDerivedFrom": [
    {
      "dct:identifier": "raw-climate-data",
      "dct:title": "Raw Climate Data",
      "dcat:downloadURL": "inputs/raw_climate.csv"
    }
  ],
  "si:fields": {
    "temperature": {
      "dct:description": "Mean surface temperature",
      "si:unit": "degC",
      "prov:wasDerivedFrom": "raw-climate-data"
    },
    "region": {
      "dct:description": "Geographic region code"
    }
  }
}
```

### Field mapping

| Metadata field                | JSON-LD key             | Notes                                         |
| ----------------------------- | ----------------------- | --------------------------------------------- |
| `slug`                        | `dct:identifier`        |                                               |
| `name`                        | `dct:title`             |                                               |
| `description`                 | `dct:description`       |                                               |
| `lineage.created_at`          | `dct:created`           | ISO 8601                                      |
| `lineage.data_hash`           | `si:dataHash`           | With `sha256:` prefix                         |
| `lineage.sources`             | `prov:wasDerivedFrom`   | Array of source objects                       |
| `lineage.field_derivations`   | `si:fields` per-column  | `prov:wasDerivedFrom` on each field            |
| `field_metadata`              | `si:fields`             | Per-column dict (unit, description, type)      |
| `rdf_prefixes`                | Merged into `@context`  | User prefixes added alongside defaults         |
| `custom_properties`           | Top-level keys          | Already use full URIs or prefixed names        |

**Excluded:** `lineage.project_path` (local filesystem, not portable).

### Prior art

- **DataDoc** (`b"datadoc"` key) -- JSON-LD in Parquet footer for
  variable-level metadata. Closest existing implementation.
- **GeoParquet** (`b"geo"` key) -- JSON in Parquet footer for geometry
  metadata. OGC standard.
- **h5rdmtoolbox** -- RDF triples as HDF5 attributes
  (object=subject, key=predicate, value=object).
- **W3C DCAT v3** -- vocabulary for describing datasets as RDF resources.
- **W3C PROV-O** -- vocabulary for provenance/lineage.

JSON-LD was chosen because it is valid JSON (readable by non-RDF tools
like DuckDB, pandas) while also being full RDF (interpretable by semantic
tools via `@context`).

## 3. Metadata Serialization

Two new methods on the `Metadata` class:

### `to_jsonld() -> dict`

- Builds `@context` from default prefixes (`dcat`, `dct`, `prov`, `si`,
  `schema`) merged with user's `rdf_prefixes`
- Maps fields to their RDF predicates per the table above
- Expands prefixed names in `custom_properties` to full URIs
- Excludes `project_path`
- Includes `si:version: "1.0"` for future schema evolution

### `Metadata.from_jsonld(doc: dict) -> Metadata` (classmethod)

- Extracts known fields back into the typed dataclass
- Unrecognized top-level keys go into `custom_properties` (forward
  compatibility -- a file from sunstone 1.9 doesn't lose data when
  read by 1.8)
- Prefixes from `@context` go into `rdf_prefixes`
- Gracefully handles missing fields (a minimal document with just
  `dct:identifier` is valid)

### `LineageMetadata.to_dict()` update

Updated to use new field names (`data_hash` instead of `content_hash`)
and include `sha256:` prefix.

## 4. Read Path -- Metadata Restoration

When reading a Parquet file via `read_dataset()`:

1. Format handler reads the file, checks for `b"sunstone"` in Parquet
   schema metadata.
2. If present, deserializes via `Metadata.from_jsonld()` and sets
   `df.attrs["sunstone_metadata"]`.
3. Sunstone DataFrame layer merges it into `self.metadata`.

### Merge strategy

`datasets.yaml` wins on all conflicts, silently. No warnings in either
strict or relaxed mode.

| Field                           | Rule                                                 |
| ------------------------------- | ---------------------------------------------------- |
| `slug`, `name`, `description`   | `datasets.yaml` if set, else embedded                |
| `field_metadata`                | `datasets.yaml` overrides per-column, embedded fills gaps |
| `rdf_prefixes`                  | Merged, `datasets.yaml` wins on duplicate prefix     |
| `custom_properties`             | Merged, `datasets.yaml` wins on duplicate key        |
| `lineage.sources`               | `datasets.yaml` (lock file) is authoritative         |
| `data_hash`                     | Lock file is authoritative                           |

When no `datasets.yaml` exists (standalone Parquet file), embedded
metadata is used as-is.

## 5. Write Path -- Metadata Embedding

When writing a Parquet file via `to_parquet()`:

1. Sunstone DataFrame attaches `self.metadata` to
   `self.data.attrs["sunstone_metadata"]`.
2. Calls `format_writer.write(self.data, stream, **kwargs)`.
3. `ParquetFormatHandler.write()` detects metadata in `df.attrs`, calls
   `metadata.to_jsonld()`, and injects JSON bytes into pyarrow schema
   metadata under `b"sunstone"`.
4. After the handler returns, transport copy is removed from attrs.

### pyarrow integration

```python
import pyarrow as pa
import pyarrow.parquet as pq

table = pa.Table.from_pandas(df)
existing_meta = table.schema.metadata or {}
existing_meta[b"sunstone"] = json.dumps(jsonld_doc).encode("utf-8")
table = table.replace_schema_metadata(existing_meta)
pq.write_table(table, stream)
```

This replaces the current `df.to_parquet(stream)` call in the handler.

### track=False path

Metadata is NOT attached to attrs. The handler writes a plain Parquet
file with no `b"sunstone"` key.

### pyarrow dependency

pyarrow is already an optional dependency for Parquet support. The
`ParquetFormatHandler` imports it at use time, same pattern as GCS/S3
handlers.

## 6. Hash Cleanup

### Two distinct hashes

| Hash      | Field name  | What's hashed                    | Where stored                          | Format         |
| --------- | ----------- | -------------------------------- | ------------------------------------- | -------------- |
| File hash | `file_hash` | Raw bytes of the file on disk    | `datasets.lock.yaml`                  | `sha256:...`   |
| Data hash | `data_hash` | DataFrame content via pickle     | `datasets.lock.yaml` + Parquet footer | `sha256:...`   |

### Changes

- `compute_dataframe_hash()` returns `sha256:`-prefixed string.
- CLI `resolve` command writes `file_hash` (not `content_hash`).
- DataFrame write path writes `data_hash` (not `content_hash`).
- `update_output_lineage` change-detection (`datasets.py:959`) uses
  `data_hash`.
- All hash comparisons are prefix-aware: bare hex from old lock files
  is treated as `sha256:` for backwards compatibility on read.

### Bugs fixed

1. **Prefix mismatch** -- CLI stored `sha256:...`, DataFrame stored bare
   hex. Now both are consistently prefixed.
2. **Silent overwrite** -- CLI resolve overwrote DataFrame's hash. Now
   they are separate fields.
3. **Comparison failure** -- `datasets.py:959` compared prefixed vs.
   unprefixed values. Now `data_hash` is always prefixed.
4. **Test inconsistencies** -- `test_dataframe.py` expected 64 chars,
   `test_lock_file.py` expected prefix. Updated for new field names
   and consistent format.

## 7. `min_sunstone_version`

A new field in `datasets.yaml`:

```yaml
min_sunstone_version: "1.8.0"
```

### Behavior

- On any `datasets.yaml` load, the library compares
  `min_sunstone_version` against the running library version.
- If the library is too old, raises a clear error:
  `"This project requires sunstone-py >= 1.8.0 (you have 1.7.0). Run: uv add sunstone-py@latest"`
- If absent, no check -- full backwards compatibility with pre-1.8
  projects.
- Uses standard semver comparison (major.minor.patch).

### Auto-bumping

The library always writes the current format. On any write to
`datasets.lock.yaml`, if `min_sunstone_version` is absent or lower
than `1.8.0`, it is set to `1.8.0`.

The invariant is: **if we write it, we declare it.**

## 8. Migration

`sunstone dataset migrate` gains these steps:

1. **Rename `content_hash`** -- in all lock file entries, rename to
   `file_hash` and add `sha256:` prefix if bare hex.
2. **Compute `data_hash`** -- for each output that exists on disk, read
   the file, parse to DataFrame, compute hash, store with prefix.
3. **Set `min_sunstone_version`** -- add `min_sunstone_version: "1.8.0"`
   to `datasets.yaml`.
4. **Idempotent** -- running migrate twice produces the same result.

Migration does NOT rewrite Parquet files to embed metadata. That happens
on the next `to_parquet()` call.

Migration is a convenience, not a requirement. Projects that never run
it still work -- the library reads `content_hash` as a fallback for
`file_hash` on read, and the first write produces the new format and
bumps `min_sunstone_version`.

## External plugin compatibility

The `FormatHandler` protocol change is backwards compatible. The
`PluginRegistry` checks for `supports_metadata` with `hasattr()` before
calling it. Existing plugins that don't implement the method are treated
as not supporting metadata. Plugins should add the method to opt in.

The Iceberg plugin (in the data-platform repo) is a known consumer
that should implement `supports_metadata() -> True` and embed the
JSON-LD document in Iceberg table properties.
