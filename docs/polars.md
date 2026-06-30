# polars

Tabular data backed by a polars `DataFrame`. The Asset envelope is
payload-agnostic, so the same `AssetKind.TABULAR` slot can hold a
polars frame, and `sunstone.polars` provides a lineage-tracking facade
mirroring `sunstone.pandas`.

- **AssetKind:** `AssetKind.TABULAR`
- **Payload:** `polars.DataFrame`
- **Typed accessor:** `Asset.as_polars() -> polars.DataFrame`
  (alongside `Asset.as_pandas()` for pandas).
- **Status:** Supported (eager mode). Install with the `[polars]`
  extra: `pip install 'sunstone-py[polars]'`. Operation-level
  `Activity` tracking for chained polars ops is deferred — derived
  frames propagate their source lineage, and writing a derived frame
  emits a one-shot `LineageWarning`.

## Why polars

Polars is faster for many group-by, join, and projection workloads
than pandas, has lazy execution, and has a cleaner expression API.
For new analyses that don't need pandas-ecosystem integrations,
polars is often the better default.

## Usage

```python
from sunstone import polars as pl
import sunstone

sunstone.set_project_path(".")

df = pl.read_csv("inputs/schools.csv")            # -> sunstone.polars.DataFrame
has_students = df.filter(pl.col("students") > 0)  # chained polars ops
has_students.write_csv("outputs/has_students.csv", slug="schools-with-students", name="Schools with students")
```

`pl.read_csv`/`read_parquet`/`read_json`/`read_dataset` resolve a slug
or registered path against `datasets.yaml`, build construction-time
lineage (source attribution, a file-content hash, and field
derivations) with `engine="polars"`, and return a
`sunstone.polars.DataFrame`. The facade composes an
`AssetKind.TABULAR` Asset:

- `df.asset` — the underlying `Asset`
- `df.data` — the `polars.DataFrame` (`df.asset.as_polars()`)
- `df.metadata` — the `Metadata` container (`df.asset.metadata`)

Unknown attributes/methods delegate to the underlying polars frame.
DataFrame-returning operations are re-wrapped via `Asset.derive(...)`
so source lineage propagates; non-DataFrame results (Series, scalars,
`.shape`) pass through unchanged.

`df.set_field_metadata(col, unit=..., description=..., source=...)`
attaches column-level metadata that flows to `datasets.yaml` on write,
the same as the pandas facade.

## How it works

The roadmap items that unlocked first-class polars support, now in
place:

1. **Polars-aware accessor.** `Asset.as_polars() -> pl.DataFrame`
   alongside `as_pandas()`, raising `TypeError` on a pandas payload
   (convert explicitly with `pl.from_pandas`).
2. **Polars-returning format handlers.** `BuiltinFormatHandler` takes
   an `engine="polars"` knob on read/write, parsing/writing CSV, JSON,
   Parquet, and TSV via polars' native readers/writers.
3. **DataFrame facade for polars.** `sunstone.polars` mirrors
   `sunstone.pandas`, with lineage-aware read/write helpers. (Op-level
   `Activity` tracking for the expression API is deferred.)
4. **Field-metadata bridge.** Polars dtypes are inferred into the
   engine-agnostic field schema at write time; explicit
   `set_field_metadata` takes precedence over inference.

## Selecting polars at the I/O boundary

You can also select polars per-call at the generic I/O boundary, so
the same `datasets.yaml` entry can be read into either engine:

```python
import sunstone as ss

asset = ss.read("inputs/schools.csv", payload="polars")
df = asset.as_polars()
```

The `payload=` argument is the dispatch knob; the format handler
remains the same. `payload=` names the returned Asset's payload type;
the same selection is recorded internally as the `engine` field on
lineage — same value (`"polars"`), different layer.

## Lineage parity

Lineage tracking is at parity with the pandas path for reads and
writes: source attribution, field derivations, and component metadata
all flow through `Metadata`, which is engine-agnostic. The one gap is
operation-level `Activity` records for chained polars ops — these are
deferred, and the absence of an `Activity` chain is the honest signal
that an op is untracked. Writing a detectably-derived frame (a
different output slug than its source, or multiple sources) without an
`Activity` chain emits a one-shot `LineageWarning`.

## See also

- [pandas](pandas.md) — the sibling tabular payload
- [API Reference](api.md) — current API surface
