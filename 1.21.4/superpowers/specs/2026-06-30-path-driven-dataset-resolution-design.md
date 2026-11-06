# Path-Driven Dataset Resolution — Design

**Date:** 2026-06-30
**Status:** Approved (ready for implementation planning)
**Base branch:** `main` (pandas + geopandas). Polars adoption is specified as a
contract for the `feat/polars-spec` branch to pick up on rebase; no polars code
lands in this work.

## Motivation

Data scientists adopting `sunstone-py` want to change as little of their existing
pandas (and, soon, polars) code as possible. The ideal migration is:

1. Change the import to `from sunstone import pandas as pd`.
2. Register inputs and outputs in `datasets.yaml`.
3. Leave existing `pd.read_csv('inputs/foo.csv')` / `df.to_csv('outputs/bar.csv')`
   calls **unchanged** — lineage tracking is derived from the path, not from an
   extra `slug=` argument.

Most of this already works: reads and writes accept the file path as the first
positional argument and look the dataset up via
`DatasetsManager.find_dataset_by_location()`, deriving the slug from the matched
dataset. This design closes the remaining gaps and removes duplicated resolution
logic so the behavior is correct and identical across surfaces.

## Problems with the current state

1. **Relative paths are resolved against the wrong base (correctness bug).**
   `find_dataset_by_location` joins a relative positional path to `project_path`
   (`datasets.py:904-905`):

   ```python
   location_abs = (self.project_path / location_path).resolve()
   ```

   Pandas and polars interpret relative paths against the **current working
   directory (cwd)**. So when a user runs from a subdirectory (e.g.
   `notebooks/`) and calls `pd.read_csv('../inputs/foo.csv')`, the match joins
   to `project_path` instead of cwd. It only works when `cwd == project_path`.

2. **The slug-vs-path heuristic is duplicated.** The check
   `"/" not in v and "\\" not in v and not Path(v).suffix` appears 3× in
   `pandas/read.py` (read_csv/read_excel/read_json) and once in
   `polars/io.py::_read_path_or_slug`. There is no single point of control.

3. **geopandas does not support paths at all.** `geopandas.read_file` /
   `read_geojson` / `read_topojson` call only `find_dataset_by_slug(slug_or_path)`.
   Passing a file path silently fails to match (it is treated as a slug that does
   not exist).

4. **Per-call resolution cost.** Each lookup iterates every registered dataset
   and calls `.resolve()` / `.samefile()` (filesystem syscalls). This is wasted
   work repeated on every read/write.

5. **No defined precedence** when an explicit `slug=` disagrees with the dataset
   the positional path resolves to.

## Goals

- Resolve relative positional paths against **cwd**, matching pandas/polars.
- One shared, dependency-light resolver used by pandas, geopandas, and (by
  contract) polars.
- Add path support to geopandas reads/writes.
- Cache resolved dataset locations so lookups are O(1) and resolve-once.
- Define precedence: an explicit `slug=` that conflicts with the path-resolved
  dataset is an error.

## Non-goals

- No changes to `datasets.yaml` schema or to how users register datasets.
- No glob/wildcard or new remote-URL resolution semantics.
- No polars code changes in this work (only a written adoption contract).
- No change to the relaxed-mode auto-register requirement that `slug` + `name`
  be supplied when writing to an **unregistered** path.

## Architecture

### New module: `src/sunstone/resolution.py`

A single home for path↔slug↔dataset resolution. It imports only the standard
library plus the `datasets` / `lineage` types — **no pandas, polars, or
geopandas imports** — so the lazy-load discipline (importing `sunstone` must not
pull in a dataframe engine) is preserved.

Contents:

1. **`looks_like_slug(value: str) -> bool`** — the single heuristic, replacing
   every duplicated copy:

   ```python
   def looks_like_slug(value: str) -> bool:
       return "/" not in value and "\\" not in value and not Path(value).suffix
   ```

   Behavior is identical to today's checks; this just centralizes it.

2. **A resolver** that, given a positional argument (path-or-slug) and a
   `DatasetsManager`, returns:

   - the matched `DatasetMetadata` (or `None` for an unregistered write target),
   - the effective slug, and
   - the fully-resolved absolute path.

   Suggested shape (final names settled during planning):

   ```python
   @dataclass(frozen=True)
   class ResolvedDataset:
       dataset: DatasetMetadata | None   # None only for unregistered write targets
       slug: str | None
       abs_path: Path                    # fully resolved, symlink-canonicalized

   def resolve_input(positional, manager) -> ResolvedDataset: ...
   def resolve_output(positional, manager, *, slug=None, name=None) -> ResolvedDataset: ...
   ```

   Resolution logic:
   - If `looks_like_slug(positional)` → slug lookup
     (`manager.find_dataset_by_slug`); absolute path from
     `manager.get_absolute_path(dataset.location)`.
   - Otherwise (a path) → resolve the positional against **cwd**
     (`Path(positional).expanduser().resolve()`) and look it up in the manager's
     resolved-location index (below).
   - **Conflict rule (writes):** if an explicit `slug=` is supplied **and** the
     positional path resolves to a registered dataset whose slug differs → raise
     `SlugConflictError`. A matching slug is harmless redundancy.

### DatasetsManager changes (`src/sunstone/datasets.py`)

- **Resolved-location index.** Build, lazily, a dict
  `{resolved_abs_path: DatasetMetadata}` keyed by
  `(project_path / location).resolve()` for every input and output. This:
  - makes matching correct and symlink-safe (both sides fully resolved), and
  - is the cache requested in brainstorming: resolve-once + O(1) lookup instead
    of O(n) `.resolve()`/`.samefile()` calls per read/write.
- **Invalidation.** Rebuild/clear the index whenever `_data` mutates — i.e. in
  `add_output_dataset` and the `update_output_*` paths — so a write that
  registers a new output is visible to the next path lookup. This sits alongside
  the process-level `DatasetsManager` cache added in #81; the index is per
  manager instance / per loaded `_data`.
- **Refactor `find_dataset_by_location`** to: resolve the positional against
  **cwd** (not `project_path`), then index lookup, keeping a direct
  registered-string fast path. The function keeps its signature so existing
  callers are unaffected.
- **Drop the fuzzy fallback (behavior change).** Remove the "same filename in
  `inputs`/`outputs`/`data` subdirectories" matching (current strategy 4 at
  `datasets.py:935-950`). It is surprising and the resolved-abspath index covers
  the legitimate cases (symlinks, relative-vs-absolute, different cwd). This is
  the one intentional behavior change in this design.

### Consumers refactored to use the resolver

- **pandas** (`src/sunstone/pandas/...` on the package layout; `pandas.py` on
  `main`): `read_csv` / `read_excel` / `read_json` and
  `to_csv` / `to_parquet` / `to_excel` / `to_json` replace their inline
  heuristic + `find_dataset_by_location` calls with the shared resolver.
- **geopandas** (`src/sunstone/geopandas.py`): `read_file` / `read_geojson` /
  `read_topojson` and the write path **gain path support** by routing through
  the resolver instead of `find_dataset_by_slug` only.
- **polars (contract, not code here):** when `feat/polars-spec` rebases onto
  this work, `polars/io.py::_read_path_or_slug` and the polars write helper
  replace their inline heuristic + `find_dataset_by_location` usage with calls to
  `sunstone.resolution`. The resolver API is designed so this is a drop-in swap.

### Unregistered-write location storage

When a write to an **unregistered** path auto-registers in relaxed mode, store
the dataset `location` as the **project_path-relative POSIX** form of the
resolved absolute path (`rel.as_posix()`), never the raw positional string. This
keeps `datasets.yaml` portable on Windows CI and stable regardless of the cwd the
write happened to run from.

## Behavior & precedence

| Situation | Behavior |
|---|---|
| Positional path, registered | Lineage tracked automatically; no `slug=` needed. |
| Positional path, unregistered, **read** | `DatasetNotFoundError` (must register first). Unchanged. |
| Positional path, unregistered, **write** (relaxed) | Requires `slug` + `name` to auto-register. Unchanged. |
| Positional slug | Slug lookup, as today. |
| Explicit `slug=` matches path-resolved dataset | Allowed (redundant). |
| Explicit `slug=` differs from path-resolved dataset | **`SlugConflictError`** (new). |
| Explicit `slug=` + unregistered path | Relaxed auto-register with that slug. Unchanged. |

## Error handling

- **`SlugConflictError`** (new; subclass of `ValueError` or the project's
  existing error base) for the explicit-slug-vs-path conflict. Message names both
  the path-resolved slug and the explicit slug.
- Reads on an unregistered path continue to raise `DatasetNotFoundError`.
- Strict-mode behavior is unchanged.

## Testing

- **cwd ≠ project_path:** run from a subdirectory, pass a cwd-relative path
  (`../inputs/foo.csv`), assert the dataset matches and lineage is recorded.
- **symlink:** a symlinked file (or a symlinked project dir) resolves to the same
  registered dataset.
- **relative on both sides; absolute positional; slug positional** — all resolve
  to the same dataset.
- **conflict:** explicit `slug=` disagreeing with the path-resolved dataset
  raises `SlugConflictError`; matching slug does not.
- **geopandas:** a path-based `read_file` / `read_geojson` now matches (was
  slug-only).
- **cache:** index is built once and reused; after a write that registers a new
  output, a subsequent path lookup finds it (invalidation works).
- **regression:** existing slug-based reads and already-registered-path reads/
  writes behave exactly as before; the dropped fuzzy fallback is covered by an
  explicit test asserting the new (stricter) behavior.

## Documentation

- README and `CLAUDE.md` "Key Differences from Plain Pandas" — reframe around
  "pass the path, register it in `datasets.yaml`, `slug=` is an optional
  override," not "`slug` is required."
- `docs/pandas.md` and `docs/geopandas.md` — document path-driven reads/writes;
  note geopandas now accepts paths.
- `CHANGELOG.md` — one short line under `[Unreleased]` (user-facing): paths are
  now resolved against the current working directory, and geopandas accepts file
  paths.

## Open items for planning

- Final names/signatures for the resolver functions and `ResolvedDataset`.
- Exact placement of the conflict check (write helpers vs. resolver) so pandas,
  geopandas, and the future polars adoption all get it for free.
- Whether `SlugConflictError` subclasses `ValueError` or the project error base.
