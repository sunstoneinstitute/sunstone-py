# File Formats

Sunstone ships with built-in handlers for the common tabular formats and
treats Parquet as a first-class self-describing target. This page lists
what each format supports, where its metadata lives, and the format-specific
features you can use from `datasets.yaml`.

## Overview

| Format  | Extensions       | Read | Write | Embedded metadata           | Format-specific features          |
|---------|------------------|------|-------|-----------------------------|-----------------------------------|
| CSV     | `.csv`           | yes  | yes   | no — sidecar YAML           | `dialect:` block                  |
| TSV     | `.tsv`, `.txt`   | yes  | no    | no — sidecar YAML           | tab delimiter is fixed            |
| JSON    | `.json`          | yes  | no    | no — sidecar YAML           | —                                 |
| Excel   | `.xlsx`, `.xls`  | yes  | no    | no — sidecar YAML           | —                                 |
| Parquet | `.parquet`       | yes  | yes   | **yes** — JSON-LD in footer | self-contained lineage           |

"Sidecar YAML" means the human-authored `datasets.yaml` plus the
auto-generated `datasets.lock.yaml` carry the lineage and field metadata.
For Parquet, the same JSON-LD that would live in the sidecar is also
embedded in the file footer, so a Parquet file can travel without the
sidecar and still describe itself.

## Reading and writing

The pandas-compatible wrapper exposes three readers, all of which dispatch
to the right format handler by extension (or by an explicit `format=` for
`read_dataset`):

```python
from sunstone import pandas as pd

df = pd.read_csv('inputs/data.csv')      # csv, tsv (via .tsv/.txt)
df = pd.read_excel('inputs/data.xlsx')   # xlsx, xls
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
   `excel`.

URLs are supported wherever local paths are — the URL handler reads the
bytes, then the format handler parses them.

## Extending Sunstone with a new format

Format handlers live behind the `FormatHandler` protocol
(`sunstone.plugins`). To add a format, implement:

```python
class FormatHandler(Protocol):
    def supports_metadata(self) -> bool: ...
    def can_read(self, path: str, format: str | None) -> bool: ...
    def can_write(self, path: str, format: str | None) -> bool: ...
    def read(self, stream, **kwargs) -> pandas.DataFrame: ...
    def write(self, df: pandas.DataFrame, stream, **kwargs) -> None: ...
```

Return `True` from `supports_metadata()` if your format can embed
Sunstone's JSON-LD document (see `ParquetFormatHandler` for a worked
example); otherwise the sidecar YAML carries the metadata as usual.

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
- [Frictionless Data](frictionlessdata.md) — the Table Dialect
  specification that Sunstone's `dialect:` block follows.
- [Data Package Spec](datapackage.md) — how dialects appear in the
  generated `datapackage.json`.
