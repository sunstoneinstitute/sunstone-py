# polars

Tabular data backed by a polars `DataFrame`. The Asset envelope is
payload-agnostic, so the same `AssetKind.TABULAR` slot can hold a
polars frame; what's not yet in place are the format handlers that
return polars frames and the typed accessor.

- **AssetKind:** `AssetKind.TABULAR`
- **Payload:** `polars.DataFrame`
- **Typed accessor:** `Asset.as_table()` is currently typed to
  `pandas.DataFrame`; a polars-aware accessor is on the roadmap.
- **Status:** Roadmap — the envelope supports a polars payload today,
  but no in-tree format handler returns one and no convenience facade
  exists yet.

## Why polars

Polars is faster for many group-by, join, and projection workloads
than pandas, has lazy execution, and has a cleaner expression API.
For new analyses that don't need pandas-ecosystem integrations,
polars is often the better default.

## How it will work

The `Asset` envelope already accepts any object as its `payload`. A
polars frame can be wrapped today, but you have to manage the lineage
plumbing by hand:

```python
import polars as pl
import sunstone as ss
from sunstone.lineage import Metadata

df = pl.read_csv("inputs/schools.csv")
asset = ss.Asset(payload=df, kind=ss.AssetKind.TABULAR,
                 metadata=Metadata(slug="schools", name="Schools"))
```

The roadmap items that unlock first-class polars support:

1. **Polars-aware accessor.** `Asset.as_polars() -> pl.DataFrame`
   alongside `as_table()`, with a clear contract for which payload
   types each accepts and how to convert between them.
2. **Polars-returning format handlers.** Either by parametrising the
   existing `BuiltinFormatHandler` ("read this CSV with polars") or by
   shipping a `PolarsFormatHandler` plugin. Both routes are compatible
   with the new `FormatHandler` protocol.
3. **DataFrame facade for polars.** A `sunstone.polars` module
   mirroring `sunstone.pandas`, with lineage-aware read/write helpers
   and operation tracking for the polars expression API.
4. **Field-metadata bridge.** Polars uses a richer dtype system than
   pandas — `ComponentSchema` already abstracts the dtype as a string,
   so the metadata flows without change; the bridge is mostly about
   inference at read time.

## Selecting polars at the I/O boundary

The intended user-facing shape is per-call selection at the I/O
boundary, so the same `datasets.yaml` entry can be read into either
engine:

```python
# Roadmap — not yet implemented
asset = ss.read("inputs/schools.csv", payload="polars")
df = asset.as_polars()
```

The `payload=` argument is the dispatch knob; the format handler
remains the same. `payload=` names the returned Asset's payload type;
the same selection is recorded internally as the `engine` field on
lineage — same value (`"polars"`), different layer.

## Lineage parity

When polars support lands, lineage tracking will be at parity with the
pandas path: source attribution, activity chain, field derivations,
and component metadata all flow through `Metadata`, which is engine-
agnostic.

## Tracking issue

See the [Asset envelope design
spec](superpowers/specs/2026-05-12-generic-format-handler-asset-envelope-design.md)
for the kind taxonomy and the open-decisions log for the polars
dispatch question.

## See also

- [pandas](pandas.md) — today's supported tabular payload
- [API Reference](api.md) — current API surface
