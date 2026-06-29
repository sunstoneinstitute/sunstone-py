# Pandas Package Refactor Design

**Date**: 2026-05-11 (revised 2026-05-22)
**Status**: Approved — revised after Asset envelope and recent pandas additions landed
**Tracks**: Prerequisite for issue #62 (Polars support)
**Sequence**: Spec 0 of the polars integration. Lands before Spec 1 (Polars eager DataFrame).

> **Revision note (2026-05-22).** The Asset envelope (PR #63), `read_json` (PR #69),
> identity URI templates, component_metadata expansion, license auto-derive from
> sources, and per-dataset CSV dialect have all landed on `main` since the original
> draft. `dataframe.py` grew from 1,337 to **1,615 lines** and `pandas.py` from
> 295 to **346 lines** in that window. The refactor goal is unchanged but the
> file-size budgets and the `__init__.py` symbol list have been updated. See the
> Update Log at the bottom for the full diff.

## Problem

`src/sunstone/dataframe.py` has grown to **1,615 lines** and contains the full `DataFrame` class with reads, writes, metadata accessors, merge/concat operations, internal helpers, license auto-derivation, identity URI materialisation, and dunder methods. The size makes it hard to hold in context, hard to navigate, and a poor template for the parallel polars wrapper that Spec 1 will introduce.

The pandas wrapper is now a **facade over a `TABULAR` `Asset`** (see `docs/pandas.md`): the `DataFrame` class holds an `Asset` whose payload is the underlying `pandas.DataFrame`. The refactor preserves this facade exactly — no change to how the wrapper relates to the Asset envelope. Mixin internals continue to construct/unwrap Assets through the same code paths.

This spec is a **pure refactor**: no behavior changes, no new features, no API changes visible to users. All existing tests must pass without modification. The goal is to land smaller, well-scoped files that make Spec 1 (and Specs 2–5) easier to design and review.

## Design

### Target Layout

`src/sunstone/pandas.py` (currently a 346-line module) becomes a package:

```
src/sunstone/pandas/
├── __init__.py        # Module-level functions and re-exports (was pandas.py)
├── core.py            # DataFrame class + __init__ + dunders + internal helpers
├── read.py            # ReadMixin: read_csv, read_excel, read_json, read_dataset
├── write.py           # WriteMixin: to_csv, to_parquet, license enforcement, identity URI
├── metadata.py        # MetadataMixin: property accessors + set_field_metadata + component_metadata
└── ops.py             # OpsMixin: merge, join, concat
```

Target ceiling is **~400 lines** per file. `write.py` carries the heaviest load (CSV, Parquet, identity URI materialisation, license auto-derive/enforce, ComponentSchema → field-schema marshaling) and may land at ~450 lines on first split — acceptable. If it exceeds **500 lines**, subdivide into `write.py` + `write_parquet.py` (or hoist license logic into `core.py`) in the same commit. The split is by responsibility (read vs. write vs. metadata vs. relational ops), not by method count or alphabet.

`src/sunstone/dataframe.py` becomes a one-line backward-compatibility re-export:

```python
# src/sunstone/dataframe.py
from sunstone.pandas.core import DataFrame  # noqa: F401
```

This preserves `from sunstone.dataframe import DataFrame` (used by three test files) without requiring test changes.

### Class Composition via Mixins

The `DataFrame` class is assembled from mixins, each owning one responsibility:

```python
# src/sunstone/pandas/core.py
class DataFrame(ReadMixin, WriteMixin, MetadataMixin, OpsMixin):
    def __init__(self, data=None, lineage=None, metadata=None, strict=None,
                 project_path=None, datasets_file=None, **kwargs):
        ...

    # Dunders, _wrap_result, _get_datasets_manager, _get_default_strict_mode
    def __getattr__(self, name): ...
    def __getitem__(self, key): ...
    def __setitem__(self, key, value): ...
    def __repr__(self): ...
    def __str__(self): ...
    def __len__(self): ...
    def __iter__(self): ...
    def _wrap_result(self, result): ...
    def _get_datasets_manager(self): ...
    @staticmethod
    def _get_default_strict_mode(): ...
```

Each mixin is a plain class with no `__init__`. Method resolution order is left-to-right: `ReadMixin` methods win over `WriteMixin` etc. None of the current methods conflict, so MRO is uneventful.

Mixin classes use `TYPE_CHECKING` imports to type-hint `self` as `DataFrame` without runtime circular imports:

```python
# src/sunstone/pandas/read.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sunstone.pandas.core import DataFrame

class ReadMixin:
    @classmethod
    def read_csv(cls, path, ...) -> "DataFrame":
        ...
```

This is the same pattern pandas itself uses for its accessor mixins.

### File Contents

| File | Owns | Approx LOC |
|---|---|---|
| `__init__.py` | Module-level `read_csv`, `read_excel`, `read_json`, `read_dataset`, `merge`, `concat`; re-exports of `DataFrame`, `Series`, `Timestamp`, `NaT`, `isna`, `isnull`, `notna`, `notnull`, `to_datetime`, `to_numeric`, `to_timedelta`; `__all__` | ~90 |
| `core.py` | `DataFrame` class declaration assembling mixins; `__init__`; all dunders; `_wrap_result`; `_get_datasets_manager`; `_get_default_strict_mode`; Asset-construction / unwrapping helpers | ~340 |
| `read.py` | `ReadMixin` with `read_csv`, `read_excel`, `read_json`, `read_dataset` | ~430 |
| `write.py` | `WriteMixin` with `to_csv`, `to_parquet`, license auto-derive + enforcement, identity URI materialisation, `_infer_dtype`, `_build_field_schema`, ComponentSchema marshalling | ~450 |
| `metadata.py` | `MetadataMixin` with property accessors (`lineage`, `description`, `rdf_prefixes`, `custom_properties`, `unit_display`) and `set_field_metadata` (writes to both legacy `field_metadata` and the unified `component_metadata`) | ~140 |
| `ops.py` | `OpsMixin` with `merge`, `join`, `concat` | ~250 |

Spec-0 commits land with `write.py` at ~450 lines. The hard ceiling is 500; subdivision into `write_parquet.py` is the agreed escape hatch if a future addition pushes it past.

### Helper Placement

Helpers used by multiple mixins live in `core.py`:

- `_wrap_result` — used by `__getitem__` and dunder pass-throughs
- `_get_datasets_manager` — used by `read.py`, `write.py`, and `metadata.py`
- `_get_default_strict_mode` — used by `__init__`
- Asset wrap/unwrap helpers — the facade construction/teardown around `Asset(payload=..., kind=AssetKind.TABULAR, metadata=...)`

Helpers used by a single mixin live in that mixin's file:

- License auto-derive + `_enforce_license_compatibility` → `write.py`
- Identity URI materialisation (`_materialise_default_identity`) → `write.py`
- `_infer_dtype`, `_build_field_schema`, ComponentSchema marshaller → `write.py`

### Public API Surface

Unchanged. Every public symbol from the existing `sunstone.pandas` module is re-exported from the new package's `__init__.py` with the same name and signature. `__all__` is preserved.

The existing user-facing usage continues to work:

```python
from sunstone import pandas as pd                # imports the package
df = pd.read_csv("input.csv")                     # module-level function
df = pd.DataFrame(...)                            # class
df.to_csv("output.csv", slug="x", name="X")       # instance method
```

Internal imports also continue to work:

```python
from sunstone.dataframe import DataFrame          # via re-export shim
from sunstone.pandas.core import DataFrame        # direct, post-refactor
```

The shim path is the **backward-compatible** path. The direct path is the **post-refactor canonical** path. Existing tests are not updated as part of Spec 0 — they keep using the shim. A follow-up commit (not in Spec 0) may migrate them, but that is editorial, not required.

### What Stays In `sunstone.dataframe`

Only a one-line re-export. The old file is otherwise deleted. The new `src/sunstone/dataframe.py`:

```python
"""Backward-compatible re-export. Prefer `from sunstone.pandas import DataFrame`."""
from sunstone.pandas.core import DataFrame  # noqa: F401
```

No `DeprecationWarning` is emitted — this is an internal module path, not a documented public API. Adding a warning would be noise for callers who don't have a better path.

### Test Strategy

No new tests are written for Spec 0. The refactor is verified by:

1. `pytest` runs green on the existing suite with zero modifications
2. Coverage report shows no regression (every line previously covered remains covered, modulo file moves which `pytest-cov` follows)
3. `mypy` (if configured) passes without new errors
4. `ruff` lint passes
5. No new public imports break — verified by a deliberate `from sunstone.pandas import *` smoke test that asserts the same `__all__` symbols are present

The CI matrix (Linux + Windows) must remain green.

### Order of Implementation

Each step is an atomic commit. Tests pass after every step:

1. Create empty `src/sunstone/pandas/` package with `__init__.py` that re-exports everything from the current `pandas.py`. Delete the old `pandas.py`. **No class changes yet.** Tests pass via the same import path.
2. Extract `ReadMixin` into `read.py`. Update `DataFrame` to inherit from it. Tests pass.
3. Extract `WriteMixin` into `write.py`. Tests pass.
4. Extract `MetadataMixin` into `metadata.py`. Tests pass.
5. Extract `OpsMixin` into `ops.py`. Tests pass.
6. Move the slimmed `DataFrame` class skeleton from `dataframe.py` into `core.py`. Replace `dataframe.py` with a one-line re-export.
7. Final review: every file ≤ 400 lines; `__all__` preserved; tests still pass.

Each step is reversible by `git revert` and produces a working tree. If a step balloons a file beyond 400 lines, that's the signal to subdivide further within the same step.

## Boundaries

### In scope

1. `src/sunstone/pandas/` package with `__init__.py`, `core.py`, `read.py`, `write.py`, `metadata.py`, `ops.py`
2. Mixin-based assembly of the `DataFrame` class
3. `src/sunstone/dataframe.py` reduced to a one-line re-export
4. No file in `src/sunstone/pandas/` exceeds 500 lines (target ~400; `write.py` ~450 acceptable)
5. All public symbols of the existing `sunstone.pandas` module preserved (same names, same signatures, including `read_json`)
6. The DataFrame-over-`Asset` facade is preserved bit-for-bit — `core.py` continues to construct `Asset(payload=..., kind=AssetKind.TABULAR, metadata=...)` and read/write paths continue to flow through the central `sunstone.read()` / `sunstone.write()` entry points
7. Existing tests pass unchanged
8. Atomic, reversible commits per step

### Out of scope

| Item | Reasoning |
|---|---|
| Any behavior change | Pure refactor — separate spec for any new logic |
| New features or methods | Spec 0 is structural only |
| Test changes or additions | Existing tests must validate the refactor; new tests belong to later specs |
| Updating internal imports in tests | The shim handles it; migrating tests is editorial |
| Polars-related changes | Spec 1 |
| `DeprecationWarning` on `sunstone.dataframe` | Internal path; no need to warn |
| Splitting `units.py`, `lineage.py`, `datasets.py` | Separate refactors if needed; not driven by polars work |
| Type-annotation modernization (e.g., `Optional[X]` → `X \| None`) | Out of scope; would obscure the structural diff |
| Renaming methods | Refactor only — no renames |

## Acceptance Criteria

- [ ] `src/sunstone/pandas/` exists as a package directory with `__init__.py`, `core.py`, `read.py`, `write.py`, `metadata.py`, `ops.py`
- [ ] `src/sunstone/pandas.py` no longer exists
- [ ] `src/sunstone/dataframe.py` contains only a re-export line, total file ≤ 5 lines
- [ ] `wc -l src/sunstone/pandas/*.py` shows no file exceeding **500 lines** (target is 400; `write.py` carries the heaviest load and is expected to land ~450)
- [ ] `from sunstone import pandas as pd` works; `pd.read_csv`, `pd.read_excel`, `pd.read_json`, `pd.read_dataset`, `pd.merge`, `pd.concat`, `pd.DataFrame`, `pd.Series`, `pd.Timestamp`, `pd.NaT`, `pd.isna`, `pd.isnull`, `pd.notna`, `pd.notnull`, `pd.to_datetime`, `pd.to_numeric`, `pd.to_timedelta` are all importable
- [ ] `from sunstone.dataframe import DataFrame` works and returns the same class as `from sunstone.pandas import DataFrame`
- [ ] `DataFrame.__mro__` contains `ReadMixin`, `WriteMixin`, `MetadataMixin`, `OpsMixin`, and `object` in that order
- [ ] `pytest` passes with zero test modifications
- [ ] Coverage is non-regressive — every previously-covered line in `dataframe.py`/`pandas.py` is still covered under its new path
- [ ] `ruff` and `mypy` (if configured) pass without new errors
- [ ] CI passes on the Windows runner
- [ ] Git history shows seven (or fewer) atomic commits, each leaving tests green
- [ ] No commit message contains "WIP", "fixup", or "squash me" — every commit is shippable on its own
- [ ] **Lazy-load preserved**: `python -c "import sunstone"` must not pull `pandas` into `sys.modules` (verified by an assertion test). The refactor must not regress the PEP 562 `__getattr__` behavior introduced in `beddbd8`. The `sunstone.pandas` package is reachable via the same lazy resolution path as the prior `sunstone.pandas` module; only `from sunstone import pandas` (or attribute access on `sunstone`) triggers the pandas import.

## Update Log

### 2026-05-22 — revised after Asset envelope and pandas additions landed

Spec drift since 2026-05-11 that was reconciled into the body:

- **`pandas.py` is now 346 lines (was 295).** PR #69 added `read_json`. The `__init__.py` symbol list and the read mixin both gained `read_json`.
- **`dataframe.py` is now 1,615 lines (was 1,337).** Growth came from identity URI templates, `component_metadata` expansion, license auto-derive from sources, per-dataset CSV dialect, mapping sugar for custom_properties, and `read_json` plumbing. `write.py`'s LOC estimate rose from ~400 to ~450 and the hard ceiling was raised to 500.
- **Asset envelope (#63) landed.** The pandas wrapper is now explicitly a facade over an `AssetKind.TABULAR` `Asset`. The refactor preserves this facade; it does not rebuild it. A note to this effect was added to the Problem section and an in-scope item makes the preservation explicit.
- **`set_field_metadata` writes both `field_metadata` and `component_metadata`** (`ComponentSchema` entries with `component_kind="column"`). The `metadata.py` mixin description was updated.
- **Identity URI materialisation** (`_materialise_default_identity`) is invoked at write time and was added to `write.py`'s ownership list.
- The refactor remains a **pure structural change** — no behavior changes, no API changes, no test changes. The line-budget loosening reflects code that already exists on `main`, not new code introduced by Spec 0.

### 2026-05-22 — addendum after CLI lazy-load landed (beddbd8)

- `sunstone/__init__.py` no longer eagerly imports submodules; every name resolves through a PEP 562 `__getattr__` lazy attribute table. `sunstone --help` startup is ~70 ms (down from ~500 ms).
- The pandas-package refactor must **preserve** this behavior: turning `sunstone.pandas` from a module into a package must not regress `import sunstone` cost. An acceptance-criterion line was added asserting `pandas` is not in `sys.modules` after `import sunstone`.
- No change to the package layout or mixin design — the lazy-load mechanism lives in the parent `sunstone/__init__.py` and resolves the new package path identically to the old module path.
