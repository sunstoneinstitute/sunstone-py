# Path-Driven Dataset Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make path↔slug↔dataset resolution correct (cwd-relative, symlink-safe), centralized, and cached, so users pass a file path and lineage is derived from `datasets.yaml` without an explicit `slug=`.

**Architecture:** A new dependency-light `sunstone.resolution` module owns the slug-vs-path heuristic and the path→dataset orchestration. `DatasetsManager.find_dataset_by_location` is rewritten to resolve the positional path against the **current working directory** and match it against a cached `{resolved_abs_path → dataset}` index. pandas reads, geopandas reads, and the write methods route through these, and an explicit-`slug=`-vs-path conflict becomes an error.

**Tech Stack:** Python 3.11+, pandas, ruamel.yaml, pytest, `uv`. Geo tests require the `[geo]` extra (run tests with `uv run --all-extras`).

**Spec:** `docs/superpowers/specs/2026-06-30-path-driven-dataset-resolution-design.md`

---

## Refinements to the spec (decided during planning)

These are concrete decisions that resolve the spec's "Open items for planning" and correct two assumptions:

1. **No new write methods.** `to_json` / `to_excel` do **not** exist in the codebase — only `to_csv` and `to_parquet`. Per YAGNI, this plan refactors only those two; it does not add new writers.
2. **geopandas scope = reads only.** geopandas writes already only require `slug`/`name` on the asset metadata and do no path→dataset lookup; the real gap is that geopandas *reads* are slug-only. This plan adds path support to geopandas reads (`read_geojson`/`read_topojson`/`read_file`) and leaves writes unchanged.
3. **Resolver API.** Instead of a heavyweight `ResolvedDataset` dataclass, `sunstone.resolution` exposes three small functions: `looks_like_slug`, `resolve_to_dataset`, `check_slug_conflict`, plus a `portable_location` helper. The manager owns the cwd-aware path match; the module owns orchestration.
4. **`find_dataset_by_location` keeps an exact-string-match fast path first** (backward compatibility for URLs and registered relative strings), then the new cwd-resolved abspath match. The dropped behavior is only the fuzzy "same filename in inputs/outputs/data subdirs" fallback (current strategy 4).
5. **`SlugConflictError`** is defined in `exceptions.py` and subclasses both `SunstoneError` and `ValueError` (catchable either way; consistent with the existing `ValueError` raised for missing slug/name).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/sunstone/exceptions.py` | Exception hierarchy | Add `SlugConflictError`. |
| `src/sunstone/resolution.py` | Slug/path heuristic + path→dataset orchestration + location normalization | **New file.** |
| `src/sunstone/datasets.py` | `DatasetsManager` | Rewrite `find_dataset_by_location` (cwd-aware + index); add `_location_index` + `_get_location_index`; invalidate in `_stamp_mtimes`. |
| `src/sunstone/dataframe.py` | pandas DataFrame reads/writes | Reads: use `looks_like_slug`, read from `dataset.location`. Writes (`to_csv`, `to_parquet`): conflict check + portable location on auto-register. |
| `src/sunstone/geopandas.py` | geopandas facade | Reads route through `resolve_to_dataset` (path support). |
| `tests/test_resolution.py` | Unit tests for the new module | **New file.** |
| `tests/test_location_resolution.py` | `find_dataset_by_location` cwd/symlink/index tests | **New file.** |
| `tests/test_dataframe.py` | pandas read cwd integration | Add tests. |
| `tests/test_geopandas_paths.py` | geopandas path-read test | **New file.** |
| `CHANGELOG.md`, `README.md`, `CLAUDE.md`, `docs/pandas.md`, `docs/geopandas.md` | User docs | Update. |
| `docs/superpowers/notes/polars-resolution-adoption.md` | Polars rebase contract | **New file.** |

**Test command (use throughout):** `uv run --all-extras pytest --no-cov <path> -v`
(`--no-cov` per repo convention; `--all-extras` so geo/parquet handlers load.)

---

### Task 1: Add `SlugConflictError`

**Files:**
- Modify: `src/sunstone/exceptions.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_errors.py`:

```python
def test_slug_conflict_error_is_sunstone_and_value_error():
    from sunstone.exceptions import SlugConflictError, SunstoneError

    err = SlugConflictError("boom")
    assert isinstance(err, SunstoneError)
    assert isinstance(err, ValueError)
    assert str(err) == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-extras pytest --no-cov tests/test_errors.py::test_slug_conflict_error_is_sunstone_and_value_error -v`
Expected: FAIL with `ImportError: cannot import name 'SlugConflictError'`.

- [ ] **Step 3: Add the exception**

In `src/sunstone/exceptions.py`, after the `StrictModeError` class, add:

```python
class SlugConflictError(SunstoneError, ValueError):
    """Raised when an explicit ``slug=`` disagrees with the dataset that the
    positional path already resolves to in datasets.yaml."""

    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-extras pytest --no-cov tests/test_errors.py::test_slug_conflict_error_is_sunstone_and_value_error -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/exceptions.py tests/test_errors.py
git commit -m "feat: add SlugConflictError exception"
```

---

### Task 2: Create `resolution.py` with `looks_like_slug`

**Files:**
- Create: `src/sunstone/resolution.py`
- Test: `tests/test_resolution.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolution.py`:

```python
"""Tests for sunstone.resolution — the shared path/slug/dataset resolver."""

from sunstone.resolution import looks_like_slug


def test_looks_like_slug_true_for_bare_kebab_identifier():
    assert looks_like_slug("official-un-member-states") is True


def test_looks_like_slug_false_for_path_with_separator():
    assert looks_like_slug("inputs/data.csv") is False
    assert looks_like_slug("inputs\\data.csv") is False


def test_looks_like_slug_false_for_bare_filename_with_extension():
    assert looks_like_slug("data.csv") is False


def test_looks_like_slug_true_for_identifier_without_extension_or_separator():
    assert looks_like_slug("my_data") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-extras pytest --no-cov tests/test_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sunstone.resolution'`.

- [ ] **Step 3: Create the module with `looks_like_slug`**

Create `src/sunstone/resolution.py`:

```python
"""Shared resolution of a positional path-or-slug to a registered dataset.

This module is intentionally dependency-light: it imports only the standard
library and ``sunstone.exceptions``. It must NOT import a dataframe engine
(pandas/polars/geopandas), so importing ``sunstone`` never pulls one in. The
``DatasetsManager`` is always passed in by the caller (duck-typed) rather than
imported at module load time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .exceptions import SlugConflictError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .datasets import DatasetMetadata, DatasetsManager


def looks_like_slug(value: str) -> bool:
    """Return True if ``value`` should be treated as a dataset slug rather than
    a filesystem path. A slug has no path separators and no file extension."""
    return "/" not in value and "\\" not in value and not Path(value).suffix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-extras pytest --no-cov tests/test_resolution.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/resolution.py tests/test_resolution.py
git commit -m "feat: add sunstone.resolution with looks_like_slug"
```

---

### Task 3: Add `resolve_to_dataset`, `check_slug_conflict`, `portable_location`

**Files:**
- Modify: `src/sunstone/resolution.py`
- Test: `tests/test_resolution.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolution.py`:

```python
import pytest

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import SlugConflictError
from sunstone.resolution import check_slug_conflict, portable_location, resolve_to_dataset


def test_resolve_to_dataset_by_slug(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    assert ds is not None
    assert ds.slug == "official-un-member-states"


def test_resolve_to_dataset_by_path(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("inputs/official_un_member_states_raw.csv", manager)
    assert ds is not None
    assert ds.slug == "official-un-member-states"


def test_resolve_to_dataset_unknown_returns_none(project_copy):
    manager = DatasetsManager(project_copy)
    assert resolve_to_dataset("nope-not-here", manager) is None
    assert resolve_to_dataset("inputs/missing.csv", manager) is None


def test_check_slug_conflict_raises_on_mismatch(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    with pytest.raises(SlugConflictError):
        check_slug_conflict(ds, "some-other-slug")


def test_check_slug_conflict_silent_when_matching_or_none(project_copy):
    manager = DatasetsManager(project_copy)
    ds = resolve_to_dataset("official-un-member-states", manager)
    # matching slug -> no error
    check_slug_conflict(ds, "official-un-member-states")
    # no explicit slug -> no error
    check_slug_conflict(ds, None)
    # no resolved dataset -> no error (relaxed auto-register path)
    check_slug_conflict(None, "anything")


def test_portable_location_relative_within_project(project_copy):
    p = project_copy / "outputs" / "new.csv"
    assert portable_location(str(p), project_copy.resolve()) == "outputs/new.csv"


def test_portable_location_leaves_urls_untouched(project_copy):
    assert portable_location("gs://bucket/x.csv", project_copy.resolve()) == "gs://bucket/x.csv"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-extras pytest --no-cov tests/test_resolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_to_dataset'`.

- [ ] **Step 3: Implement the three functions**

Append to `src/sunstone/resolution.py`:

```python
def resolve_to_dataset(
    value: str,
    manager: "DatasetsManager",
    dataset_type: Optional[str] = None,
) -> Optional["DatasetMetadata"]:
    """Resolve a positional path-or-slug to a registered dataset, or ``None``.

    If ``value`` looks like a slug it is looked up by slug; otherwise it is
    treated as a filesystem path and matched (cwd-relative, symlink-safe) by
    :meth:`DatasetsManager.find_dataset_by_location`.
    """
    value = str(value)
    if looks_like_slug(value):
        return manager.find_dataset_by_slug(value, dataset_type)
    return manager.find_dataset_by_location(value, dataset_type)


def check_slug_conflict(
    path_dataset: Optional["DatasetMetadata"],
    explicit_slug: Optional[str],
) -> None:
    """Raise :class:`SlugConflictError` if an explicit ``slug=`` disagrees with
    the dataset the positional path already resolves to. No-op when either is
    absent or they agree."""
    if path_dataset is not None and explicit_slug is not None and path_dataset.slug != explicit_slug:
        raise SlugConflictError(
            f"slug={explicit_slug!r} conflicts with the dataset already "
            f"registered at this path (slug={path_dataset.slug!r}). "
            f"Remove the slug= argument or write to a different path."
        )


def portable_location(location: str, project_path: Path) -> str:
    """Return a portable, project-relative POSIX location for storage in
    datasets.yaml. URLs are returned unchanged. Paths inside ``project_path``
    become forward-slash relative paths (Windows-safe); paths outside become
    absolute POSIX paths."""
    if "://" in location:
        return location
    abs_path = Path(location).expanduser().resolve()
    try:
        return abs_path.relative_to(project_path).as_posix()
    except ValueError:
        return abs_path.as_posix()
```

Also extend the imports at the top of the file: `Any` is unused — keep the import line as `from typing import TYPE_CHECKING, Optional` (remove `Any` if present from Task 2; it was not used there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --all-extras pytest --no-cov tests/test_resolution.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/resolution.py tests/test_resolution.py
git commit -m "feat: add resolve_to_dataset, check_slug_conflict, portable_location"
```

---

### Task 4: Make `find_dataset_by_location` cwd-aware, indexed, and cached

**Files:**
- Modify: `src/sunstone/datasets.py` (`__init__` ~line 230, `_stamp_mtimes` ~line 393, `find_dataset_by_location` lines 877-952)
- Test: `tests/test_location_resolution.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_location_resolution.py`:

```python
"""Resolution semantics for DatasetsManager.find_dataset_by_location."""

import json

from sunstone.datasets import DatasetsManager
from sunstone.field_types import FieldSchema


def test_exact_registered_string_matches_regardless_of_cwd(project_copy, monkeypatch, tmp_path):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(tmp_path)  # somewhere unrelated
    ds = manager.find_dataset_by_location("inputs/official_un_member_states_raw.csv")
    assert ds is not None and ds.slug == "official-un-member-states"


def test_cwd_relative_path_from_subdir_matches(project_copy, monkeypatch):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy / "outputs")
    ds = manager.find_dataset_by_location("../inputs/official_un_member_states_raw.csv")
    assert ds is not None and ds.slug == "official-un-member-states"


def test_symlinked_absolute_path_is_canonicalized(project_copy, tmp_path):
    link = tmp_path / "linked_project"
    link.symlink_to(project_copy)
    manager = DatasetsManager(project_copy)
    through_link = link / "inputs" / "official_un_member_states_raw.csv"
    ds = manager.find_dataset_by_location(str(through_link))
    assert ds is not None and ds.slug == "official-un-member-states"


def test_same_filename_in_other_directory_does_not_match(project_copy, monkeypatch):
    # The dropped fuzzy fallback: a file with the same NAME but a different
    # location must NOT resolve to the registered dataset.
    other = project_copy / "elsewhere"
    other.mkdir()
    decoy = other / "official_un_member_states_raw.csv"
    decoy.write_text("x\n")
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy)
    assert manager.find_dataset_by_location("elsewhere/official_un_member_states_raw.csv") is None


def test_index_invalidated_after_add_output_dataset(project_copy, monkeypatch):
    manager = DatasetsManager(project_copy)
    monkeypatch.chdir(project_copy)
    # Build the index once.
    assert manager.find_dataset_by_location("inputs/official_un_member_states_raw.csv") is not None
    # Register a new output, then look it up by location.
    manager.add_output_dataset(
        name="Brand New",
        slug="brand-new",
        location="outputs/brand_new.csv",
        fields=[FieldSchema(name="x", type="string")],
    )
    ds = manager.find_dataset_by_location("outputs/brand_new.csv", "output")
    assert ds is not None and ds.slug == "brand-new"
```

> Note: `FieldSchema` lives in `sunstone.field_types`. If its constructor differs, mirror the shape used by `tests/test_datasets.py` for `add_output_dataset`; the existing tests there are the source of truth for the exact `FieldSchema` call.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-extras pytest --no-cov tests/test_location_resolution.py -v`
Expected: `test_cwd_relative_path_from_subdir_matches` and `test_symlinked_absolute_path_is_canonicalized` FAIL (return None); `test_same_filename_in_other_directory_does_not_match` may currently PASS-or-FAIL depending on the old fuzzy logic — it documents the target behavior either way.

- [ ] **Step 3: Initialize the index field in `__init__`**

In `src/sunstone/datasets.py`, in `DatasetsManager.__init__`, immediately before `self._load(check_version=True)`, add:

```python
        # Cached {resolved_abs_path -> (dataset_data, dtype)} index for fast,
        # cwd-correct, symlink-safe path matching. Invalidated on every load/save
        # via _stamp_mtimes.
        self._location_index: Optional[
            tuple[Dict[str, Any], Dict[Path, Any]]
        ] = None
        self._load(check_version=True)
```

(Replace the existing bare `self._load(check_version=True)` line.)

- [ ] **Step 4: Invalidate the index in `_stamp_mtimes`**

In `_stamp_mtimes` (after the two mtime assignments), add:

```python
        # Any load or save changes the dataset set; drop the derived index.
        self._location_index = None
```

- [ ] **Step 5: Add the index builder and rewrite `find_dataset_by_location`**

Replace the entire body of `find_dataset_by_location` (lines 877-952) with:

```python
    def _get_location_index(self) -> "tuple[Dict[str, Any], Dict[Path, Any]]":
        """Build (and cache) the resolved-location index.

        Returns ``(by_string, by_abspath)`` where ``by_string`` maps the raw
        stored ``location`` string to ``(dataset_data, dtype)`` (covers URLs and
        exact relative strings) and ``by_abspath`` maps each dataset location,
        resolved against ``project_path`` and symlink-canonicalized, to the same.
        Earlier datasets win on collisions (``setdefault``).
        """
        if self._location_index is None:
            by_string: Dict[str, Any] = {}
            by_abspath: Dict[Path, Any] = {}
            for dtype, key in (("input", "inputs"), ("output", "outputs")):
                for dataset_data in self._data.get(key, []):
                    loc = dataset_data["location"]
                    by_string.setdefault(loc, (dataset_data, dtype))
                    if "://" in str(loc):
                        continue
                    loc_path = Path(loc)
                    abs_path = loc_path.resolve() if loc_path.is_absolute() else (self.project_path / loc_path).resolve()
                    by_abspath.setdefault(abs_path, (dataset_data, dtype))
            self._location_index = (by_string, by_abspath)
        return self._location_index

    def find_dataset_by_location(self, location: str, dataset_type: Optional[str] = None) -> Optional[DatasetMetadata]:
        """Find a dataset by its file location.

        Resolution order:
          1. Exact string match against the stored ``location`` — covers URLs and
             registered relative strings, and is independent of the cwd (backward
             compatible).
          2. Filesystem match — the positional path is resolved against the
             **current working directory** (matching pandas/polars), then compared
             fully-resolved and symlink-canonicalized against each dataset's
             location resolved against ``project_path``.

        Args:
            location: The file path or URL to search for.
            dataset_type: Optional filter by 'input' or 'output'.

        Returns:
            DatasetMetadata if found, None otherwise.
        """
        by_string, by_abspath = self._get_location_index()

        def _accept(entry: Any) -> Optional[DatasetMetadata]:
            dataset_data, dtype = entry
            if dataset_type is None or dtype == dataset_type:
                return self._parse_dataset(dataset_data, dtype)
            return None

        # 1. Exact string match (URLs, registered relative strings).
        entry = by_string.get(location)
        if entry is not None:
            result = _accept(entry)
            if result is not None:
                return result

        # 2. Filesystem match, resolved against cwd. Skip URL-like inputs.
        if "://" not in location:
            target_abs = Path(location).expanduser().resolve()
            entry = by_abspath.get(target_abs)
            if entry is not None:
                result = _accept(entry)
                if result is not None:
                    return result

        return None
```

- [ ] **Step 6: Run the new tests**

Run: `uv run --all-extras pytest --no-cov tests/test_location_resolution.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the existing datasets tests for regressions**

Run: `uv run --all-extras pytest --no-cov tests/test_datasets.py tests/test_datasets_coverage.py -v`
Expected: PASS. If any test relied on the dropped fuzzy filename fallback, update that test to reflect the new (stricter, spec'd) behavior and note it.

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/datasets.py tests/test_location_resolution.py
git commit -m "feat: resolve dataset paths against cwd with a cached location index"
```

---

### Task 5: Route pandas reads through the shared heuristic and read from `dataset.location`

**Files:**
- Modify: `src/sunstone/dataframe.py` (imports near top; read path branches at ~566/599, ~692/711, ~808/830)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dataframe.py`:

```python
def test_read_csv_with_cwd_relative_path_from_subdir(project_copy, monkeypatch):
    import sunstone
    from sunstone import pandas as pd

    monkeypatch.chdir(project_copy / "outputs")
    df = pd.read_csv(
        "../inputs/official_un_member_states_raw.csv",
        project_path=project_copy,
    )
    # Lineage is derived from the registered dataset, not the raw path.
    sources = df.metadata.lineage.sources
    assert any(s.slug == "official-un-member-states" for s in sources)
    assert len(df.data) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-extras pytest --no-cov "tests/test_dataframe.py::test_read_csv_with_cwd_relative_path_from_subdir" -v`
Expected: FAIL — old code joins the relative path to `project_path`, so either the dataset is not found (`DatasetNotFoundError`) or the file read targets the wrong absolute path.

- [ ] **Step 3: Add the shared import**

Near the top of `src/sunstone/dataframe.py`, with the other `from .` imports, add:

```python
from .resolution import looks_like_slug
```

- [ ] **Step 4: Replace the three slug heuristics**

In `read_csv`, `read_excel`, and `read_json`, replace each occurrence of:

```python
        is_slug = "/" not in location and "\\" not in location and not Path(location).suffix
```

with:

```python
        is_slug = looks_like_slug(location)
```

- [ ] **Step 5: Read from the registered location, not the positional path**

In the path branch of `read_csv` (line ~599), `read_excel` (~724), and `read_json` (~837), replace:

```python
        # Use the requested location
        absolute_path = manager.get_absolute_path(location)
```

with:

```python
        # Resolve the file from the registered dataset location (the positional
        # path may be cwd-relative or symlinked; dataset.location is canonical).
        absolute_path = manager.get_absolute_path(dataset.location)
```

(There are three occurrences — one per read method. The `read_excel` line number is approximate; match on the `get_absolute_path(location)` text within each path branch.)

- [ ] **Step 6: Run the new test and read regressions**

Run: `uv run --all-extras pytest --no-cov "tests/test_dataframe.py::test_read_csv_with_cwd_relative_path_from_subdir" tests/test_dataframe.py -k "read_csv or read_json or read_excel or read_dataset" -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: pandas reads resolve cwd-relative paths and read registered location"
```

---

### Task 6: Conflict check + portable location on writes (`to_csv`, `to_parquet`)

**Files:**
- Modify: `src/sunstone/dataframe.py` (`to_csv` ~960-996, `to_parquet` ~1124-1160)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dataframe.py`:

```python
def test_to_csv_slug_conflict_with_registered_path_raises(project_copy):
    from sunstone import pandas as pd
    from sunstone.exceptions import SlugConflictError

    df = pd.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy)
    with pytest.raises(SlugConflictError):
        df.to_csv(
            "outputs/current_un_member_states.csv",  # registered as 'current-un-member-states'
            slug="a-different-slug",
            name="Mismatch",
        )


def test_to_csv_autoregister_stores_portable_location(project_copy, monkeypatch):
    from sunstone import pandas as pd
    from sunstone.datasets import DatasetsManager

    df = pd.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy)
    # Write from an unrelated cwd using an absolute path inside the project.
    monkeypatch.chdir(project_copy / "inputs")
    target = project_copy / "outputs" / "fresh_output.csv"
    df.to_csv(str(target), slug="fresh-output", name="Fresh Output")

    manager = DatasetsManager(project_copy)
    ds = manager.find_dataset_by_slug("fresh-output", "output")
    assert ds is not None
    assert ds.location == "outputs/fresh_output.csv"  # portable, project-relative POSIX
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --all-extras pytest --no-cov "tests/test_dataframe.py::test_to_csv_slug_conflict_with_registered_path_raises" "tests/test_dataframe.py::test_to_csv_autoregister_stores_portable_location" -v`
Expected: FAIL — no conflict raised; stored location is the raw absolute string, not `outputs/fresh_output.csv`.

- [ ] **Step 3: Add the shared import**

In `src/sunstone/dataframe.py`, extend the resolution import added in Task 5:

```python
from .resolution import check_slug_conflict, looks_like_slug, portable_location
```

- [ ] **Step 4: Add the conflict check in `to_csv`**

In `to_csv`, immediately after:

```python
    # Try to find existing dataset
    dataset = manager.find_dataset_by_location(location, "output")
```

add:

```python
    # An explicit slug= that disagrees with the dataset already registered at
    # this path is a conflict (per design: explicit must not silently override).
    check_slug_conflict(dataset, slug)
```

- [ ] **Step 5: Store a portable location on auto-register in `to_csv`**

In the relaxed-mode auto-register branch of `to_csv`, change the `add_output_dataset` call's `location=location` argument to a portable form. Replace:

```python
            # Register the new output with full metadata
            dataset = manager.add_output_dataset(
                name=effective_name,
                slug=effective_slug,
                location=location,
```

with:

```python
            # Register the new output with full metadata. Store a portable,
            # project-relative POSIX location (the positional path may be
            # cwd-relative or absolute).
            dataset = manager.add_output_dataset(
                name=effective_name,
                slug=effective_slug,
                location=portable_location(location, manager.project_path),
```

- [ ] **Step 6: Apply the same two edits to `to_parquet`**

Repeat Step 4 (conflict check after `find_dataset_by_location`) and Step 5 (portable `location=`) in `to_parquet`, which has the identical structure.

- [ ] **Step 7: Run the new tests and write regressions**

Run: `uv run --all-extras pytest --no-cov "tests/test_dataframe.py::test_to_csv_slug_conflict_with_registered_path_raises" "tests/test_dataframe.py::test_to_csv_autoregister_stores_portable_location" tests/test_dataframe.py -k "to_csv or to_parquet" -v`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: writes reject conflicting slug= and store portable locations"
```

---

### Task 7: geopandas reads accept file paths

**Files:**
- Modify: `src/sunstone/geopandas.py` (`_read`, `read_file`)
- Test: `tests/test_geopandas_paths.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geopandas_paths.py`:

```python
"""geopandas reads should accept a file path, not only a slug."""

import json

import pytest

pytest.importorskip("geopandas")


def _make_geo_project(root):
    (root / "shapes.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "A"},
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                    }
                ],
            }
        )
    )
    (root / "datasets.yaml").write_text(
        "package:\n"
        "  title: Geo Test\n"
        '  version: "1.0.0"\n'
        "inputs:\n"
        "  - name: Shapes\n"
        "    slug: shapes\n"
        "    location: shapes.geojson\n"
        "    fields:\n"
        "      - name: name\n"
        "        type: string\n"
        "outputs: []\n"
    )


def test_read_geojson_by_path(tmp_path):
    from sunstone.geopandas import read_geojson

    _make_geo_project(tmp_path)
    gdf = read_geojson("shapes.geojson", project_path=tmp_path)
    assert len(gdf.data) == 1
    assert gdf.metadata.slug == "shapes"


def test_read_geojson_by_slug_still_works(tmp_path):
    from sunstone.geopandas import read_geojson

    _make_geo_project(tmp_path)
    gdf = read_geojson("shapes", project_path=tmp_path)
    assert len(gdf.data) == 1
```

- [ ] **Step 2: Run tests to verify the path case fails**

Run: `uv run --all-extras pytest --no-cov tests/test_geopandas_paths.py -v`
Expected: `test_read_geojson_by_path` FAILS with `DatasetNotFoundError` (path treated as a slug); `test_read_geojson_by_slug_still_works` PASSES.

- [ ] **Step 3: Route geopandas reads through `resolve_to_dataset`**

In `src/sunstone/geopandas.py`, add the import:

```python
from .resolution import resolve_to_dataset
```

In `_read`, replace:

```python
    dataset = manager.find_dataset_by_slug(slug_or_path)
```

with:

```python
    dataset = resolve_to_dataset(slug_or_path, manager)
```

In `read_file`, replace:

```python
    dataset = manager.find_dataset_by_slug(slug_or_path)
```

with:

```python
    dataset = resolve_to_dataset(slug_or_path, manager)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --all-extras pytest --no-cov tests/test_geopandas_paths.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/geopandas.py tests/test_geopandas_paths.py
git commit -m "feat: geopandas reads accept file paths, not only slugs"
```

---

### Task 8: Documentation, changelog, and polars adoption note

**Files:**
- Modify: `CHANGELOG.md`, `README.md`, `CLAUDE.md`, `docs/pandas.md`, `docs/geopandas.md`
- Create: `docs/superpowers/notes/polars-resolution-adoption.md`

- [ ] **Step 1: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]` (create the section if absent), add (one short line each, per repo convention):

```markdown
- Changed: file paths in `read_csv`/`to_csv` etc. now resolve against the current working directory, so reads/writes from a subdirectory match `datasets.yaml`.
- Added: geopandas readers (`read_geojson`/`read_topojson`/`read_file`) accept a file path, not only a dataset slug.
- Changed: passing `slug=` that conflicts with the dataset registered at the given path now raises `SlugConflictError`.
```

- [ ] **Step 2: Reframe the "Key Differences" docs**

In `README.md`, `CLAUDE.md`, and `docs/pandas.md`, update the dataset-registration guidance so it leads with: *pass the file path; register it in `datasets.yaml`; `slug=` is an optional override, not a requirement*. In `docs/geopandas.md`, note that readers now accept a path or a slug.

- [ ] **Step 3: Write the polars adoption note**

Create `docs/superpowers/notes/polars-resolution-adoption.md`:

```markdown
# Polars adoption of shared path resolution

When `feat/polars-spec` rebases onto the path-driven-resolution work, adopt the
shared resolver so polars matches pandas/geopandas exactly:

- Replace the inline `is_slug = "/" not in loc and ...` heuristic in
  `src/sunstone/polars/io.py::_read_path_or_slug` with
  `from sunstone.resolution import looks_like_slug` and route the path branch
  through `sunstone.resolution.resolve_to_dataset(loc, manager)`.
- In the polars write helper (`src/sunstone/polars/write.py::_write`), after the
  `find_dataset_by_location(location, "output")` lookup, call
  `sunstone.resolution.check_slug_conflict(dataset, slug)` and store the
  auto-register `location=` via `sunstone.resolution.portable_location(...)`.
- No changes to `find_dataset_by_location` are needed — polars already calls it
  and inherits the cwd-aware, cached behavior.
- Add polars equivalents of the cwd-relative and slug-conflict tests.
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md CLAUDE.md docs/pandas.md docs/geopandas.md docs/superpowers/notes/polars-resolution-adoption.md
git commit -m "docs: document path-driven resolution and polars adoption contract"
```

---

### Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run --all-extras pytest --no-cov -q`
Expected: all pass except the pre-existing `tests/test_handlers_gcs.py::TestGcsURLHandlerLazyAuth::test_missing_dependency_raises_import_error` (an artifact of running with the gcs extra installed; unrelated to this work). If any other test fails, fix it before proceeding.

- [ ] **Step 2: Type-check**

Run: `uv run --all-extras mypy src/sunstone/resolution.py src/sunstone/datasets.py src/sunstone/dataframe.py src/sunstone/geopandas.py`
Expected: no new errors. Fix any introduced by the new code (e.g. the `_location_index` tuple annotation).

- [ ] **Step 3: Lint/format**

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
Expected: clean. Run `uv run ruff format src/ tests/` if formatting is needed, then re-commit.

- [ ] **Step 4: Final commit (if lint/format changed anything)**

```bash
git add -A
git commit -m "chore: lint/format for path-driven resolution"
```

---

## Self-Review

**Spec coverage:**
- Cwd-relative resolution fix → Task 4. ✓
- Single shared resolver (`looks_like_slug` + `resolve_to_dataset`) → Tasks 2-3, consumed in Tasks 5/7. ✓
- Resolved-location cache + invalidation → Task 4 (`_get_location_index` + `_stamp_mtimes`). ✓
- geopandas path support → Task 7. ✓
- Explicit-slug-vs-path conflict = error → Task 6 (`check_slug_conflict`, `SlugConflictError` Task 1). ✓
- Portable unregistered-write location → Task 6 (`portable_location`). ✓
- Drop fuzzy filename fallback → Task 4 (test `test_same_filename_in_other_directory_does_not_match`). ✓
- Polars adoption contract → Task 8 note. ✓
- Docs + changelog → Task 8. ✓

**Refinements vs spec:** `to_json`/`to_excel` do not exist (only `to_csv`/`to_parquet` refactored); geopandas scope narrowed to reads. Both documented at the top.

**Type consistency:** `looks_like_slug(value: str) -> bool`, `resolve_to_dataset(value, manager, dataset_type=None) -> Optional[DatasetMetadata]`, `check_slug_conflict(path_dataset, explicit_slug) -> None`, `portable_location(location, project_path) -> str`, `SlugConflictError(SunstoneError, ValueError)`, `_get_location_index() -> (by_string, by_abspath)` used consistently across tasks.
