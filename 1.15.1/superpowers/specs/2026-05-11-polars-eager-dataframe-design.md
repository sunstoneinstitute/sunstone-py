# Polars Eager DataFrame Design

**Date**: 2026-05-11 (revised 2026-05-22)
**Status**: Approved — substantially revised after Asset envelope landed on `main`
**Tracks**: GitHub issue #62 (Polars support)
**Sequence**: First sub-spec of the polars integration. Depends on Spec 0 (pandas package refactor). Followed by Spec 2 (operation-level lineage), Spec 3 (LazyFrame), Spec 4 (units), Spec 5 (cross-engine interop).

> **Revision note (2026-05-22).** The Asset envelope (PR #63), centralized
> `sunstone.read()` / `sunstone.write()` dispatch, PROV-O Activity-based lineage,
> `datasets.lock.yaml` split, license auto-derive from sources, and the
> published `docs/polars.md` roadmap have all landed since the original
> draft. Several core design decisions changed as a result: the polars facade
> is now a thin wrapper over an `AssetKind.TABULAR` `Asset` (not a parallel
> implementation), construction-time lineage uses main's actual fields
> (`sources`, `data_hash`, `activity`, `field_derivations`), and the proposed
> `derived_from` / `derivation_status` fields are dropped in favour of the
> existing `Asset.derive()` parent-chain mechanism. The only new
> `LineageMetadata` field is `engine`. See the Update Log at the bottom for
> the full diff.

## Problem

Issue #62 requests Polars support as a drop-in replacement for pandas with the same Sunstone guarantees: automatic lineage, table/column metadata, units, and dataset-registration integration. The full surface area is roughly equivalent to the existing pandas integration and is too large for a single spec.

This spec covers the foundational slice: **eager-mode read and write of Polars DataFrames through the Asset envelope, with construction-time lineage**. Operation-level lineage (PROV-O `Activity` composition), LazyFrame support, units, and cross-engine interop are explicitly out of scope and deferred to later sub-specs.

`docs/polars.md` already commits Sunstone to four roadmap items:

1. A polars-aware `Asset.as_polars()` accessor alongside `as_table()`.
2. Polars-returning format handlers (parametrise the existing `BuiltinFormatHandler` with an `engine=` knob).
3. A `sunstone.polars` DataFrame facade mirroring `sunstone.pandas`.
4. A field-metadata bridge (mostly free — `ComponentSchema` is already engine-neutral).

The committed user-facing dispatch knob is `ss.read(path, payload="polars")`. Spec 1 delivers items 1–3 and confirms item 4 needs no new code beyond an inference path at read time.

**Terminology — `payload=` vs `engine`.** The public knob is `payload=` because `read()` returns an `Asset` and the argument selects that Asset's payload type — it mirrors the envelope's own vocabulary (`Asset.payload`, `as_table()`, `as_polars()`). The same choice is recorded internally as the `engine` field on `LineageMetadata` and switches `BuiltinFormatHandler(engine=...)`, because at that layer the concern is *which engine produced the representation* (provenance), not *what you get back*. The two map 1:1 — `payload="polars"` ⇄ `engine="polars"` — so the difference is layer, not meaning.

When the user reaches for a Polars operation on a Spec-1 DataFrame, the facade must communicate honestly that operation-level lineage is not yet tracked, without forcing the user to drop out of the facade API. This is the central design tension Spec 1 resolves — and the resolution is now straightforward: `Asset.derive(child_payload, derived_from=[parent_asset])` produces a child lineage with parent sources but no `Activity`. The absence of an `Activity` chain is the honest, observable signal that ops are untracked.

## Design

### Module Layout

`src/sunstone/polars/` is a package, mirroring the post-Spec-0 layout of `src/sunstone/pandas/`:

```
src/sunstone/polars/
├── __init__.py        # Public re-exports
├── core.py            # DataFrame class
├── io.py              # read_csv / read_parquet / read_json / read_dataset / write_*
└── metadata.py        # Property accessors, set_field_metadata
```

No file exceeds 400 lines. The split is by responsibility, not by polars method group.

### Public API

`from sunstone import polars as pl` exposes:

| Symbol | Source | Notes |
|---|---|---|
| `pl.read_csv` | Sunstone facade | Thin wrapper over `sunstone.read(path, payload="polars")`; returns `sunstone.polars.DataFrame` |
| `pl.read_parquet` | Sunstone facade | Same shape |
| `pl.read_json` | Sunstone facade | Same shape |
| `pl.read_dataset` | Sunstone facade | Slug-based; resolves location via `DatasetsManager` then delegates as above |
| `pl.DataFrame` | Sunstone facade | `sunstone.polars.core.DataFrame` |
| `pl.Series`, `pl.col`, `pl.lit`, `pl.when`, `pl.LazyFrame`, dtypes (`pl.Int64`, ...) | Pass-through | Re-exported from upstream `polars` |

Two writer surfaces, both delegating to `sunstone.write(self.asset, path, format=...)`:

- `df.write_csv(path, slug=..., name=..., ...)`
- `df.write_parquet(path, slug=..., name=..., ...)`
- `df.write_json(path, slug=..., name=..., ...)`

Polars' native `write_*` naming is preserved (rather than pandas' `to_*`), so muscle memory carries over. The facade methods stamp `slug` / `name` onto `self.asset.metadata` and hand off to `sunstone.write()`, which runs the centralized write path: license auto-derive + enforcement, identity URI materialisation, `datasets.lock.yaml` update, plugin dispatch, and per-dataset CSV dialect honor (all engine-neutral).

A new typed accessor lands as part of this spec: `Asset.as_polars() -> pl.DataFrame` (analogous to `as_table()`). It raises `IncompatibleAssetKindError` if the asset's `kind` is not `TABULAR`, and `TypeError` if the payload is not a `polars.DataFrame` (e.g., it's a `pandas.DataFrame` — call `as_table()` and convert with `pl.from_pandas()` explicitly; Spec 5 lands lineage-preserving cross-engine conversion).

**Not in Spec 1:** `pl.read_excel` (requires `xlsx2csv`/`fastexcel` extras — separate spec), `pl.scan_csv` / `pl.scan_parquet` (lazy readers — Spec 3), `pl.concat`, `pl.merge` (operations — Spec 2).

### `pl.DataFrame` Class

Composition over an `Asset`, mirroring how `sunstone.pandas.DataFrame` is a facade over a `TABULAR` Asset:

```python
class DataFrame:
    asset: Asset                    # underlying Asset (kind=TABULAR, payload=pl.DataFrame)
    strict_mode: bool

    def __init__(
        self,
        data: Any = None,
        *,
        metadata: Optional[Metadata] = None,
        asset: Optional[Asset] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        datasets_file: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ):
        ...

    @property
    def data(self) -> "polars.DataFrame":
        """The underlying polars frame (shortcut for `self.asset.as_polars()`)."""
        return self.asset.as_polars()

    @property
    def metadata(self) -> Metadata:
        return self.asset.metadata
```

`Metadata` and `LineageMetadata` are reused as-is — engine-agnostic by design.

`__init__` accepts:
- An existing `Asset` (used directly when `asset=` is passed — the primary internal construction path used by `pl.read_csv` etc.)
- `pl.DataFrame` payload (wrapped in a fresh `Asset(kind=TABULAR, ...)` with any supplied metadata)
- `pd.DataFrame` (converted via `pl.from_pandas` — lineage is *not* preserved across this conversion; Spec 5)
- Any other type accepted by `pl.DataFrame()` constructor (dict, list of dicts, etc.)

The constructor's positional `data=` and keyword `metadata=` mirror the pandas facade signature for ergonomic parity. The `lineage=` argument that appeared in the original draft is dropped — lineage now lives inside `metadata`, and there is no longer a reason to pass it separately.

### Construction-Time Lineage Payload

When `pl.read_csv(path, slug=...)` succeeds, the underlying `Asset.metadata.lineage` is populated using main's actual `LineageMetadata` shape:

| Field | Value at read time |
|---|---|
| `lineage.sources` | One-element list with a `DatasetMetadata` describing the source (slug, name, location, optional `Source` with license/attribution) |
| `lineage.data_hash` | SHA-256 of bytes read (file-content hash), prefixed `"sha256:"` |
| `lineage.field_derivations` | Auto-populated via `populate_field_derivations(columns, slug)` — one `FieldDerivation` per column, identity mapping |
| `lineage.activity` | `None` (Activity is reserved for explicit operations — Spec 2) |
| `lineage.created_at` | now |
| `lineage.engine` | `"polars"` (new optional field — see below) |

**File-content hashing** is the deliberate Spec 1 choice: polars' internal layout differs from pandas, so reusing `compute_dataframe_hash` (which pickles a pandas frame) would require materialising through pandas. File-content hashing is engine-neutral and matches what `datasets.lock.yaml` already records. The same approach back-applies to pandas reads in a future cleanup (out of scope here).

### Lineage Schema Additions

**One** new field on `LineageMetadata`:

```python
@dataclass
class LineageMetadata:
    # ... existing fields ...
    engine: Optional[str] = None
```

| Field | Semantics |
|---|---|
| `engine` | `"pandas"` / `"polars"` / `None` (legacy / unspecified). Identifies the engine that produced the in-memory representation. Spec 1 also stamps `"pandas"` on the pandas facade's reads/writes so future audits can distinguish. Omitted from serialised output when `None` (no diff for unchanged `datasets.lock.yaml` files). |

The original draft proposed adding `derived_from: Optional[List[LineageMetadata]]` and `derivation_status: Literal["fresh", "unknown", "tracked"]`. **Both are dropped.** Main already encodes derivation lineage through `Asset.derive(child_payload, derived_from=[parent_asset, ...])`, which calls `_build_child_lineage(parents)` and composes child lineage from the parents' `sources` list. The "fresh / unknown / tracked" tri-state collapses to a natural binary: an `Asset` whose `lineage.activity is None` but whose `lineage.sources` is non-empty either came from a direct read (matches `data_hash`) or from an untracked op chain. Spec 2 will populate `Activity` for tracked ops; Spec 1 leaves `Activity` as `None` and relies on the warning at write time to flag the gap.

### Op Boundary Contract

Spec 1 does **not** track operation-level lineage. The facade lets users chain polars operations naturally, but the absence of an `Activity` chain communicates the gap honestly to anyone inspecting the lineage.

Mechanism: `DataFrame.__getattr__` delegates unknown attribute access to `self.asset.payload` (the underlying `pl.DataFrame`). When the delegated call returns a `pl.DataFrame`, the facade derives a child Asset via:

```python
child_asset = self.asset.derive(
    new_payload,                # pl.DataFrame returned by the op
    derived_from=[self.asset],  # parent chain composed via _build_child_lineage
)
# child_asset.metadata.lineage:
#   sources        ← propagated from self.asset (single-parent chain collapses)
#   activity       ← None (no op-level tracking yet)
#   field_derivations ← carried forward where unambiguous; cleared otherwise
#   data_hash      ← None (recomputed only on write)
#   engine         ← "polars"
```

`derived_from=[self.asset]` is the canonical PROV-O parent chain on `main`. Multi-parent ops (joins) pass both parents. When the delegated call returns a non-DataFrame value (e.g. `df.height: int`, `df.columns: list[str]`), pass it through unchanged.

Explicitly implemented dunders that need wrapping behavior (not handled by `__getattr__`):

- `__getitem__` — wraps DataFrame results, passes through Series results
- `__len__`, `__contains__`, `__iter__`, `__repr__`, `__str__` — pass-through

Other dunders (`__add__`, `__sub__`, etc.) are out of scope for Spec 1 — those are unit-aware operations (Spec 4).

### Write Path

`df.write_csv(path, slug=..., name=..., ...)`:

1. Stamp `slug` and `name` onto `self.asset.metadata` (overwriting any pre-existing values supplied at construction time).
2. Set `self.asset.metadata.lineage.engine = "polars"` (idempotent — already stamped at read time).
3. Delegate to `sunstone.write(self.asset, path, format="csv", **kwargs)`. The central write path handles:
   - URL handler resolution via `PluginRegistry`
   - Plugin dispatch to a polars-aware `FormatHandler` (see *Plugin Reuse* below)
   - License **auto-derive** from `lineage.sources` and **enforcement** against the target slot's declared license
   - Identity URI materialisation (`_materialise_default_identity`)
   - `datasets.lock.yaml` update with hash + sources, using `Path.as_posix()` for cross-platform paths
   - Per-dataset CSV dialect honor (writes go through the same dialect resolution as pandas)
4. **Before** delegating, the facade inspects `self.asset` for the "derivation gap": if `lineage.sources` indicates the Asset is derived (i.e., the slug differs from any source slug, or there are multiple sources) AND `lineage.activity is None`, emit a `LineageWarning` exactly once per write call:
   > `"Output '{slug}' written from a polars DataFrame whose derivation chain has no Activity records. Operation-level lineage is not yet tracked for the polars engine. See Spec 2."`

   (The same warning is wired into the pandas path in Spec 2 — once `Activity` is consistently populated for tracked ops, its absence is a real signal regardless of engine. Spec 1 emits the warning only for polars writes.)

Same pattern for `write_parquet` and `write_json` — the slug/name stamping, warning emission, and `sunstone.write()` delegation are shared in a helper inside `io.py`.

### Plugin Reuse

The `FormatHandler` protocol on `main` already returns an `Asset` and declares `supported_kinds()`. Plugins can opt into the new protocol with `__sunstone_handler_protocol__ = 2`; older plugins are wrapped by `TabularDataFrameAdapter` and still produce `Asset(kind=TABULAR, payload=pd.DataFrame, ...)`. Spec 1 leverages this directly rather than parallelling it.

| Plugin layer | Reuse in Spec 1 | Notes |
|---|---|---|
| `AuthProvider` | Full | Credential resolution is engine-neutral |
| `URLHandler` (HTTP, local, GCS, S3) | Full | Returns binary streams; polars consumes them directly |
| Built-in `FormatHandler` | **Parametrised** | The existing `BuiltinFormatHandler` gains an `engine: Literal["pandas", "polars"] = "pandas"` knob (constructor arg, default preserves current behavior). When `engine="polars"`, it reads via `pl.read_csv` / `pl.read_parquet` / `pl.read_json` and returns `Asset(payload=pl.DataFrame, kind=TABULAR, ...)`. `sunstone.read(path, payload="polars")` instantiates / selects the polars-engine handler. |
| External `FormatHandler` plugins (legacy protocol) | Unchanged | They keep returning `pd.DataFrame` payloads via the adapter. The user opts into polars at the call site; if no polars-engine handler claims the format, the call falls back to pandas with a warning. (A future spec defines an engine-aware claim for external plugins.) |
| External `FormatHandler` plugins (protocol 2) | Pass-through | If a third-party plugin returns a polars-payload Asset, the facade accepts it as-is. |

`PluginRegistry` itself is reused unchanged. The polars facade queries it for URL/auth handlers identically to pandas — in fact, it never queries `PluginRegistry` directly. The `sunstone.read()` / `sunstone.write()` entry points do that work centrally.

### Dependency

Polars is an **optional extra**: `sunstone-py[polars]`. Existing pandas-only users do not pay the install cost.

The polars import is also **lazy**, matching the pattern introduced for pandas in `beddbd8`. The `sunstone` package's PEP 562 `__getattr__` resolves `sunstone.polars` on first access; `import sunstone` does not pull polars into `sys.modules`. Inside `src/sunstone/polars/__init__.py`, the actual `import polars` happens at module load (which is fine — by the time the user has done `from sunstone import polars`, they have already opted in). What does need lazy-import discipline is the polars-engine path inside `BuiltinFormatHandler`: `import polars` must happen inside `read()` / `write()`, not at module load, so that `import sunstone.handlers` continues to be cheap.

`src/sunstone/polars/__init__.py` raises `ImportError` with a clear message if polars is not installed:

```python
try:
    import polars as _pl
except ImportError as e:
    raise ImportError(
        "Polars support requires the [polars] extra. "
        "Install with: pip install sunstone-py[polars]"
    ) from e
```

`pyproject.toml` adds:

```toml
[project.optional-dependencies]
polars = ["polars>=1.0.0"]
```

Pinned minimum version chosen to match Polars' 1.x stable API guarantees.

### Errors and Warnings

| Condition | Behavior |
|---|---|
| `from sunstone import polars` without `[polars]` extra | `ImportError` with install instruction |
| `pl.read_csv("unregistered.csv")` in strict mode | `DatasetNotFoundError` (existing exception, reused) |
| `pl.read_csv("unregistered.csv")` in relaxed mode | Auto-register in `datasets.yaml`, proceed |
| Write of a derived Asset with `lineage.activity is None` and multi-source/different-slug indicators | `LineageWarning` (existing pattern, reused), once per write call |
| Write with license incompatible with source | `LicenseCompatibilityError` (existing exception, reused via central write path) |
| `Asset.as_polars()` on a non-TABULAR Asset | `IncompatibleAssetKindError` (existing exception, reused) |
| `Asset.as_polars()` on a TABULAR Asset whose payload is `pd.DataFrame` | `TypeError` with a hint about `pl.from_pandas` (Spec 5 will land lineage-preserving conversion) |

No new exception types are introduced.

### Order of Implementation

Each step below is an atomic commit. Tests must pass after every step (or, for steps that add a test before its implementation, the bracket completes within the same commit). Steps are ordered to avoid forward references — every step's implementation can rely only on what landed before it.

1. **`pyproject.toml`: add `polars` optional extra.** Adds `polars = ["polars>=1.0.0"]` under `[project.optional-dependencies]`. Refresh `uv.lock`. No code yet — verify `uv pip install -e .[polars]` works in the project venv. Tests still 1281 / 2 skipped.

2. **`LineageMetadata.engine: Optional[str] = None`.** Add the field with default `None`. Update `LineageMetadata.to_dict()` / serialisation to **omit** the field when `None` (so `datasets.lock.yaml` of legacy records doesn't churn). Add a unit test in `tests/test_lineage_persistence.py` covering: default value, explicit set/get, serialise-when-non-None, omit-when-None. Existing tests keep passing.

3. **Pandas facade back-fill: stamp `engine="pandas"` on reads/writes.** Add the stamp inside the existing pandas read path (`pandas/read.py` constructor calls) and write path (`pandas/write.py` lineage updates). Add tests asserting the stamp lands on the resulting lineage. Existing tests pass unchanged.

4. **`Asset.as_polars()` typed accessor.** Add to `sunstone/asset.py` alongside `as_table()`. Returns `polars.DataFrame` (via the existing payload). Raises `IncompatibleAssetKindError` on non-TABULAR Assets. Raises `TypeError` (with a `pl.from_pandas(...)` hint) on TABULAR Assets whose payload is a `pandas.DataFrame`. Tests in `tests/test_asset.py` (or wherever Asset tests live) cover: success path with a polars payload, `IncompatibleAssetKindError` path, `TypeError` path on pandas payload. The polars import inside `as_polars` must be **lazy** (inside the method body).

5. **`BuiltinFormatHandler` gains `engine` parameter.** Add `engine: Literal["pandas", "polars"] = "pandas"` to the constructor (or class attribute). When `engine="polars"`, the `read()` path uses `pl.read_csv` / `pl.read_parquet` / `pl.read_json` and returns `Asset(payload=pl.DataFrame, kind=TABULAR, metadata=Metadata(...))`. Write paths follow the same pattern for `pl.DataFrame` payloads. The `import polars` happens **inside `read()` / `write()`**, not at module load — `import sunstone.handlers` must remain cheap. Add tests covering: polars-engine CSV/Parquet/JSON round-trip via the handler directly (not yet via the facade). Existing pandas tests stay green.

6. **`sunstone.read(path, payload="polars")` dispatch knob.** Wire the existing `sunstone.read()` entry point to honour `payload="polars"` (and the symmetric `payload="pandas"`, default) by selecting the engine-appropriate `BuiltinFormatHandler`. Tests cover the dispatch — same fixture file read both ways yields different payload types but identical lineage shape (modulo `engine` field). Existing tests stay green.

7. **`src/sunstone/polars/` package skeleton + lazy-load wiring.** Create the package with `__init__.py`, `core.py`, `io.py`, `metadata.py` (initially mostly empty — just the import guard + minimal scaffolding). The package's `__init__.py` raises `ImportError` if polars isn't installed, with the install hint. Wire `sunstone.polars` into `sunstone/__init__.py`'s PEP 562 `__getattr__` lazy table — `import sunstone` must NOT pull `polars` (or even attempt to). Tests cover: `import sunstone` succeeds without `[polars]` extra; `from sunstone import polars` raises `ImportError` without the extra; both work cleanly with the extra installed. Lazy-load sys.modules assertion still passes.

8. **`pl.DataFrame` facade class (core.py + metadata.py).** Implements:
   - `core.py`: `DataFrame` composing an `Asset`, with `asset`, `data` (returns `self.asset.as_polars()`), `metadata`, `strict_mode` properties; `__init__` accepting `asset=`, payload `data=`, `metadata=`; `__getitem__`, `__len__`, `__contains__`, `__iter__`, `__repr__`, `__str__` dunders.
   - `metadata.py`: property accessors (`description`, `rdf_prefixes`, `custom_properties`) and `set_field_metadata` writing through to both `field_metadata` (legacy) and `component_metadata` (ComponentSchema entries).

   Tests cover construction from `pl.DataFrame`, from existing `Asset`, from `pd.DataFrame` (with conversion via `pl.from_pandas`), and the metadata accessors.

9. **Read facade functions (io.py — reads).** Implement `read_csv`, `read_parquet`, `read_json`, `read_dataset` as thin wrappers that call `sunstone.read(path, payload="polars", ...)` and wrap the returned Asset in a `pl.DataFrame` facade. Slug-based `read_dataset` resolves location via `DatasetsManager` then delegates the same way. Tests cover: each reader returns a `sunstone.polars.DataFrame`; lineage is populated correctly with `engine="polars"`; strict-mode + relaxed-mode behaviour; URL routing through `HttpURLHandler` (mock).

10. **Op boundary contract (`__getattr__` in `core.py`).** Delegate unknown attribute access on `pl.DataFrame` facade to `self.asset.payload`. When the delegated call returns a `pl.DataFrame`, re-wrap via `self.asset.derive(new_payload, derived_from=[self.asset])`. When it returns a non-DataFrame value, pass through unchanged. Tests cover: `df.filter(...)`, `df.select(...)`, `df.with_columns(...)`, `df.group_by(...).agg(...)`, `df.join(other, ...)` all return facade DataFrames with parent chain populated; `df.height`, `df.shape`, `df.columns` pass through unchanged.

11. **Write facade methods (io.py — writes + LineageWarning).** Implement `write_csv`, `write_parquet`, `write_json` instance methods on the facade. Each stamps `slug`/`name` onto `self.asset.metadata`, then delegates to `sunstone.write(self.asset, path, format=...)`. Before the delegation, if the asset is detectably derived (multi-source OR output slug differs from any source slug) AND `lineage.activity is None`, emit a `LineageWarning`. Tests cover: end-to-end write of a fresh asset (no warning), write of a derived asset (exactly one warning per call), license compatibility error via central path, `datasets.lock.yaml` update with POSIX-style path.

12. **Docs update: `docs/polars.md` marks roadmap items 1–3 as done.** Replace the "Roadmap" status with "Supported" for the four roadmap items now landed (Asset.as_polars, polars-returning handlers, sunstone.polars facade, field-metadata bridge). Add a usage example mirroring the pandas examples. Add `polars.md` link from `docs/api.md`. No code changes.

Each step ends with `uv run pytest --no-cov -q` green and `uv run mypy src/` clean. Pyright in the venv should also be clean for all touched files.

**Step sequencing notes:**
- Steps 1–6 build the engine-neutral substrate (extra, lineage field, accessor, handler param, dispatch).
- Steps 7–11 build the polars facade on top of that substrate.
- Step 12 closes the loop with documentation.
- The `engine="pandas"` back-fill (Step 3) lands before the polars work so the test suite gains the new field assertions early.
- The op boundary (Step 10) lands *after* reads (Step 9) so basic round-tripping tests exist before the more nuanced derivation logic.
- The writes (Step 11) land last because they depend on the op boundary's `derived_from` semantics for the `LineageWarning` heuristic.

## Boundaries

### In scope

1. `src/sunstone/polars/` package with `__init__.py`, `core.py`, `io.py`, `metadata.py`
2. Reader functions: `read_csv`, `read_parquet`, `read_json`, `read_dataset` (slug-based) — thin facades over `sunstone.read(path, payload="polars")`
3. Writer instance methods: `write_csv`, `write_parquet`, `write_json` — thin facades over `sunstone.write(self.asset, path, ...)`
4. `pl.DataFrame` facade class composing an `Asset` (kind=TABULAR, payload=`pl.DataFrame`); exposes `asset`, `data`, `metadata`, `strict_mode`
5. `set_field_metadata` and metadata property accessors (description, rdf_prefixes, custom_properties) writing through to `Metadata` and `component_metadata`
6. **`Asset.as_polars()` typed accessor** on the `Asset` class (alongside `as_table()`)
7. Construction-time lineage population using current `LineageMetadata` shape (`sources`, `data_hash`, `field_derivations`, `activity=None`)
8. `Asset.derive()`-based op delegation: unknown attr lookups returning `pl.DataFrame` are re-wrapped via `self.asset.derive(new_payload, derived_from=[self.asset])`
9. **One** new `LineageMetadata` field: `engine: Optional[str]` (defaults to `None`, omitted when serialised)
10. `engine="pandas"` stamped on the pandas facade's reads/writes (back-fill)
11. `engine="polars"` stamped on every polars facade read/write
12. `BuiltinFormatHandler` parametrised with `engine: Literal["pandas", "polars"] = "pandas"` for the polars I/O path
13. `LineageWarning` emission when writing a derived Asset that has no `Activity` chain (Spec 1 emits for polars writes; Spec 2 generalises to pandas)
14. `sunstone-py[polars]` optional extra in `pyproject.toml` (`polars>=1.0.0`)
15. Test coverage parallel to `tests/test_dataframe.py` and `tests/test_lineage_persistence.py`
16. Cross-platform path handling — `Path.as_posix()` continues to be used by the central write path
17. Per-dataset CSV dialect and Windows `\n` newline default are honored by the polars CSV write path (already wired into the central path)
18. **Lazy-load discipline**: `sunstone.polars` is exposed via the PEP 562 `__getattr__` lazy table in `sunstone/__init__.py`; `import sunstone` does not pull polars (or pandas) into `sys.modules`. The polars-engine code path inside `BuiltinFormatHandler` imports polars inside `read()` / `write()`, not at module load.
19. No file in `src/sunstone/polars/` exceeds 400 lines

### Out of scope

| Item | Where it goes |
|---|---|
| Operation-level lineage propagation through polars ops (PROV-O `Activity` population) | Spec 2 |
| `pl.LazyFrame` wrapping, `pl.scan_csv`, `pl.scan_parquet` | Spec 3 |
| Unit-aware arithmetic, Pint-backed columns | Spec 4 |
| Lineage-preserving `df.to_pandas()` / `pl.from_pandas()` | Spec 5 |
| `pl.read_excel` | Separate spec (sub-dependency burden) |
| `pl.concat`, `pl.merge` module-level wrappers | Spec 2 (operations) |
| Engine-aware claim semantics for external `FormatHandler` plugins (legacy protocol) | Future spec |
| Dataframe-content hashing for polars | Not needed — file-content hash sufficient |
| `derived_from` / `derivation_status` fields on `LineageMetadata` | **Dropped** — derivation lineage is encoded via `Asset.derive()` parent chain |
| Spec 0 (pandas package refactor) | Separate spec, lands first |

## Acceptance Criteria

Each criterion is a pass/fail check that must be satisfied before Spec 1 is considered done.

- [ ] `from sunstone import polars as pl` works when `sunstone-py[polars]` is installed; raises `ImportError` with install instruction otherwise
- [ ] `pl.read_csv("input.csv")` on a path registered in `datasets.yaml` returns a `sunstone.polars.DataFrame` where `df.asset.kind is AssetKind.TABULAR` and `df.asset.payload` is a `polars.DataFrame`; `df.data` returns the same `polars.DataFrame`
- [ ] After `pl.read_csv("input.csv")`: `df.metadata.lineage.engine == "polars"`, `df.metadata.lineage.sources` contains a single `DatasetMetadata` for the source, `df.metadata.lineage.data_hash` matches `"sha256:" + hashlib.sha256(file_bytes).hexdigest()`, `df.metadata.lineage.activity is None`, `df.metadata.lineage.field_derivations` is populated one-per-column
- [ ] `pl.read_csv("unregistered.csv")` raises `DatasetNotFoundError` in strict mode
- [ ] `pl.read_csv("unregistered.csv")` auto-registers in relaxed mode and proceeds
- [ ] `pl.read_parquet`, `pl.read_json`, `pl.read_dataset(slug)` all satisfy the analogous criteria
- [ ] HTTP URL reads route through `HttpURLHandler` (verified via handler mock asserting it was called with the expected URL)
- [ ] GCS reads route through `GcsURLHandler` when `sunstone-py[gcs,polars]` extras installed
- [ ] `df.write_csv("output.csv", slug="x", name="X")` writes the file via the central `sunstone.write()` path AND adds/updates the entry in `datasets.lock.yaml` with a forward-slash POSIX path
- [ ] `df.write_parquet`, `df.write_json` satisfy the analogous criteria
- [ ] `df.filter(pl.col("a") > 0)` returns a `sunstone.polars.DataFrame` (not raw `pl.DataFrame`); its `asset.metadata.lineage.sources` carries the parent's source(s); `asset.metadata.lineage.activity is None`; `asset.metadata.lineage.engine == "polars"`
- [ ] `df.height`, `df.shape`, `df.columns` (non-DataFrame returns) pass through unchanged
- [ ] `df.select(["a", "b"])`, `df.with_columns(...)`, `df.group_by("a").agg(...)`, `df.join(other, on="key")` all return wrapped `sunstone.polars.DataFrame`s whose underlying child `Asset` was produced via `Asset.derive(..., derived_from=[parent_asset, ...])`
- [ ] Writing a derived Asset with `lineage.activity is None` emits exactly one `LineageWarning` per write call
- [ ] Writing an Asset that came straight from a read (no derivation) emits no `LineageWarning`
- [ ] License compatibility check fires on polars writes via the central path (verified by writing with an incompatible target license — `LicenseCompatibilityError` raised); license auto-derive from `lineage.sources` is exercised when the target slot has no declared license
- [ ] `Asset.as_polars()` returns a `polars.DataFrame` payload; raises `IncompatibleAssetKindError` on non-TABULAR Assets; raises `TypeError` on TABULAR Assets whose payload is `pd.DataFrame`
- [ ] Pandas wrapper test suite (`tests/test_dataframe.py`, `tests/test_lineage_persistence.py`, `tests/test_dataframe_coverage.py`) passes unchanged
- [ ] New `engine` field on `LineageMetadata` defaults to `None` for legacy lineage records and is omitted from serialized output when `None` (no `datasets.lock.yaml` diff for unchanged files)
- [ ] `engine="pandas"` is stamped on pandas-facade reads/writes (back-fill) so audits can distinguish engines
- [ ] No file in `src/sunstone/polars/` exceeds 400 lines
- [ ] CI passes on Windows runner (path handling and CSV newline defaults verified)
- [ ] Public API surface documented in `docs/api.md`; `docs/polars.md` updated to mark items 1–3 of the roadmap as **done** and link to this spec
- [ ] **Lazy-load preserved**: `python -c "import sunstone"` adds neither `polars` nor `pandas` to `sys.modules` (assertion test). `python -c "from sunstone import polars"` adds `polars` but still not `pandas`. `python -c "from sunstone import pandas"` adds `pandas` but still not `polars`.
- [ ] `python -c "import sunstone.handlers"` does not add `polars` to `sys.modules`; reading a CSV with `payload="polars"` is what triggers the polars import

## Update Log

### 2026-05-22 — substantially revised after Asset envelope landed on `main`

The original 2026-05-11 draft predates several decisions that have since landed. The body of this spec was revised in place; this log records the diff so reviewers can see what was reconciled.

**Architectural shift — facade over Asset, not parallel implementation.**
- The pandas wrapper is now publicly documented (`docs/pandas.md`) as a facade over an `AssetKind.TABULAR` `Asset`. The polars facade follows the same pattern: `pl.DataFrame.asset` is the underlying `Asset` whose `payload` is a `polars.DataFrame`.
- Module-level `pl.read_*` functions are thin wrappers around `sunstone.read(path, payload="polars")`. Instance `df.write_*` methods are thin wrappers around `sunstone.write(self.asset, path, ...)`.
- The committed user-facing dispatch knob is `ss.read(path, payload="polars")`, per `docs/polars.md`. Spec 1 implements this knob via a parametrised `BuiltinFormatHandler(engine="polars")`.

**`LineageMetadata` schema change — dropped `derived_from` and `derivation_status`.**
- Main's `LineageMetadata` carries `sources: List[DatasetMetadata]`, `activity: Optional[Activity]` (PROV-O), `field_derivations: Optional[List[FieldDerivation]]`, `data_hash`, `created_at`, `project_path`. The original draft's proposed `source_url`, `dataset_slug`, `dataset_hash`, `format`, `timestamp` field names were aspirational — main's actual field names are used throughout the revised body.
- The original draft proposed three new fields: `engine`, `derived_from`, `derivation_status`. **`engine` stays.** **`derived_from` is dropped** because `Asset.derive(child_payload, derived_from=[parent_asset])` already encodes the parent chain through `_build_child_lineage(parents)`, which composes the child's `sources` list. **`derivation_status` is dropped** because the tri-state collapses: `lineage.activity is None` with non-empty `sources` is the natural signal that an Asset is derived from sources but not op-tracked.
- The `LineageWarning` semantics changed accordingly: warning fires on write when an Asset has a derivation indicator (multi-source, or output slug differs from any source slug) AND `lineage.activity is None`. The polars facade emits this in Spec 1; Spec 2 generalises to pandas.

**`Asset.as_polars()` added as in-scope.**
- `docs/polars.md` lists this as roadmap item 1. It moves into Spec 1 as a small typed accessor on `Asset`, alongside the existing `as_table()`.

**Plugin protocol re-use — embrace, not avoid.**
- The new `FormatHandler` protocol on `main` already returns `Asset` and declares `supported_kinds()`. The original draft said external `FormatHandler` plugins were "Not supported in Spec 1"; that stance is dropped. Existing legacy handlers wrapped by `TabularDataFrameAdapter` keep returning pandas payloads, and the user opts into polars at the call site. Protocol-2 plugins can return polars payloads natively.

**Write path — centralised, not duplicated.**
- The original draft duplicated URL resolution, license enforcement, and `datasets.yaml` update logic into the polars facade. Main has a centralised `sunstone.write(asset, path)` that already handles all of this engine-neutrally. The facade now stamps slug/name and delegates.
- `datasets.yaml` is the human-authored registry; lineage / hashes go into `datasets.lock.yaml` (PR #49, confirmed by 0ed3e26's read-side fix). Terminology updated throughout.
- License auto-derive from `lineage.sources` (1d779b9) is exercised automatically.
- Per-dataset CSV dialect (820808a) and Windows `\n` newline default (02d138c) are inherited from the central path.

**`read_json` already exists.**
- PR #69 added `read_json` to `sunstone.pandas`. The polars version is parallel work, not novel precedent.

**Other minor reconciliations.**
- Constructor's `lineage=` argument is dropped — lineage lives inside `metadata` now and there's no longer a reason to pass it separately.
- `set_field_metadata` writes through to both legacy `field_metadata` and the unified `component_metadata` (`ComponentSchema` entries) — same behaviour as the pandas facade gained in 5ce7443.

### 2026-05-22 — addendum after CLI lazy-load landed (beddbd8)

The CLI lazy-loading refactor (PEP 562 `__getattr__` in `sunstone/__init__.py`, deferred `import pandas` in `sunstone.handlers`) imposes a constraint Spec 1 must honor:

- **`sunstone.polars` is exposed through the same lazy `__getattr__` mechanism.** `import sunstone` must not add `polars` to `sys.modules`. The polars import only fires when the user does `from sunstone import polars` (or accesses `sunstone.polars` directly).
- **`BuiltinFormatHandler(engine="polars")` must defer `import polars` to the read/write call site**, mirroring how the pandas path now uses `_get_reader(fmt)` to defer pandas. Importing `sunstone.handlers` must remain cheap.
- The pandas back-fill (`engine="pandas"` stamp on pandas-facade reads/writes) does not change anything about lazy loading — by the time the pandas facade is involved, pandas is already being imported.
- Three new acceptance criteria capture the lazy-load assertions; one is added to the in-scope list as item 18.
- The "Dependency" section was expanded with a paragraph explaining the lazy-import discipline.
