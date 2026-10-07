# pandas

Tabular data backed by a pandas `DataFrame`. This is the kind that
sunstone-py was originally built for, and it remains the most fully
supported.

- **AssetKind:** `AssetKind.TABULAR`
- **Payload:** `pandas.DataFrame`
- **Typed accessor:** `Asset.as_pandas() -> pandas.DataFrame`
  (`as_table()` remains as a backwards-compatible alias)
- **DataFrame facade:** `sunstone.DataFrame` (drop-in pandas wrapper)

## Status

Fully supported. CSV, JSON, Excel, TSV, and Parquet are handled by
in-tree format handlers; HTTP(S), local file, GCS, and S3/R2 URLs are
handled by in-tree URL handlers.

## Two entry points

There are two equivalent entry points for tabular I/O. Pick whichever
fits your code.

### `sunstone.read()` / `sunstone.write()` — Asset-native

```python
import sunstone as ss

asset = ss.read("inputs/schools.csv")
assert asset.kind is ss.AssetKind.TABULAR

df = asset.as_pandas()             # pandas.DataFrame
df_filtered = df[df["enrollment"] > 100]

child = asset.derive(
    df_filtered.groupby("district").sum(),
    slug="school-summary",
    name="School Enrollment Summary",
)
ss.write(child, "outputs/summary.csv")
```

`sunstone.read()` returns an `Asset`; `sunstone.write()` accepts one.
The kind is inferred from the registered format in `datasets.yaml`. If
you try to `write()` an asset whose kind does not match the destination
slot, you get `IncompatibleAssetKindError`.

### `sunstone.DataFrame` / `sunstone.pandas` — drop-in pandas

```python
from sunstone import pandas as pd
import sunstone
from pathlib import Path

sunstone.set_project_path(Path.cwd())

df = pd.read_csv("inputs/schools.csv")
summary = df[df["enrollment"] > 100].groupby("district").sum()
summary.to_csv(
    "outputs/summary.csv",
    slug="school-summary",
    name="School Enrollment Summary",
    index=False,
)
```

`sunstone.DataFrame` is a facade over a TABULAR `Asset`. Both routes
record identical lineage; pick `sunstone.pandas` for code that should
look like pandas and the Asset API for code that needs to be uniform
across kinds.

## Field-level metadata

Per-column metadata (description, units, dtype) is stored in
`Metadata.component_metadata` as `ComponentSchema` entries with
`component_kind="column"`. The legacy `Metadata.field_metadata` view
remains as a typed shortcut for tabular kinds and is the recommended
way to set per-column metadata for now.

```python
df.set_field_metadata("temperature", units="celsius",
                     description="Daily mean air temperature")
```

Units are Pint-parsable strings and emit as `qudt:unit` IRIs in JSON-LD
output.

## Lineage

Lineage flows through pandas operations (`merge`, `concat`, `groupby`,
column-level transforms). Field-level derivations populate on read and
update as columns change. See [Core Concepts](concepts.md) for the full
lineage model.

## Extras

TABULAR assets typically have empty `extras`. Partitioned Parquet
(directory-of-files) uses `extras` only when a future `StoreFormatHandler`
needs to round-trip partition keys.

## See also

- [Core Concepts](concepts.md) — lineage, strict mode, dataset registration
- [API Reference](api.md) — full API surface
- [polars](polars.md) — alternative tabular payload (roadmap)
