# sunstone.polars Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an eager-mode `sunstone.polars` DataFrame facade — read/write of Polars frames through the existing `Asset` envelope with construction-time lineage — mirroring `sunstone.pandas`.

**Architecture:** A thin facade over an `AssetKind.TABULAR` `Asset` whose `payload` is a `polars.DataFrame`. Reads/writes reuse the central plugin registry and `BuiltinFormatHandler`, which gains an `engine="pandas"|"polars"` knob. Lineage reuses `Metadata`/`LineageMetadata` unchanged except for one new optional `engine` field. Operation-level lineage (PROV-O `Activity`) is out of scope (Spec 2); ops re-wrap via `Asset.derive(...)` and the absence of an `Activity` chain is the honest signal that ops are untracked.

**Tech Stack:** Python 3.12+, Polars ≥1.0 (optional extra `[polars]`), pandas (existing), pytest, mypy, ruff. Lazy-import discipline via PEP 562 `__getattr__`.

**Spec:** `docs/superpowers/specs/2026-05-11-polars-eager-dataframe-design.md` (Spec 1). This plan implements its 12-step Order of Implementation.

**Conventions for every task:**
- Run tests with `uv run pytest --no-cov -q` (this repo treats coverage as opt-in).
- After each task: `uv run pytest --no-cov -q` green AND `uv run mypy src/` clean.
- The `[polars]` extra must be installed in the dev venv: `uv pip install -e '.[polars]'` (done in Task 1).
- Test project fixture: `tests/conftest.py` exposes `project_path` → `tests/testdata/UNMembersProject` (has a real `datasets.yaml` and `inputs/official_un_member_states_raw.csv`), and `project_copy` (a writable temp copy).
- Commit messages: do NOT advertise the assistant. Add a CHANGELOG `[Unreleased]` entry only for user-visible changes (Tasks 4, 6, 8–12 are user-visible; Tasks 1–3, 5 are plumbing — judge per task notes).

---

## File Structure

**New files:**
- `src/sunstone/polars/__init__.py` — package: import guard, PEP 562 lazy `__getattr__`, re-exports (`read_csv`/`read_parquet`/`read_json`/`read_dataset`/`DataFrame` + pass-through polars symbols).
- `src/sunstone/polars/core.py` — `DataFrame` facade class composing an `Asset`; `__getattr__` op boundary.
- `src/sunstone/polars/io.py` — module-level reader functions + instance writer methods (shared helper).
- `src/sunstone/polars/metadata.py` — `MetadataMixin`-style property accessors + `set_field_metadata`.
- `tests/test_polars.py` — facade tests (mirror `tests/test_dataframe.py`).
- `tests/test_polars_lineage.py` — lineage/engine field + warning tests.

**Modified files:**
- `pyproject.toml` — add `[project.optional-dependencies] polars`.
- `src/sunstone/lineage.py` — add `LineageMetadata.engine` field + `to_dict()` omit-when-None.
- `src/sunstone/pandas/read.py` — stamp `engine="pandas"` on read lineage.
- `src/sunstone/pandas/write.py` — stamp `engine="pandas"` on write lineage (2 sites).
- `src/sunstone/asset.py` — add `as_polars()` accessor.
- `src/sunstone/handlers.py` — `BuiltinFormatHandler` gains `engine` knob (read + write).
- `src/sunstone/__init__.py` — add `read(..., payload=...)`; wire `sunstone.polars` into the lazy submodule table.
- `docs/polars.md`, `docs/api.md` — mark roadmap items done; document the facade.

**Boundary rule:** no file in `src/sunstone/polars/` exceeds 400 lines (Spec acceptance criterion).

---

## Task 1: Add the `[polars]` optional extra

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies]`, after the `geo` block ~line 60)
- Test: `tests/test_polars_packaging.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_polars_packaging.py
"""Polars is an optional extra; the import guard and dependency wiring."""
import tomllib
from pathlib import Path


def test_polars_extra_declared() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    extras = data["project"]["optional-dependencies"]
    assert "polars" in extras, "expected a [polars] optional extra"
    assert any(dep.startswith("polars") for dep in extras["polars"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/test_polars_packaging.py`
Expected: FAIL with `KeyError: 'polars'` / assertion error.

- [ ] **Step 3: Add the extra**

In `pyproject.toml`, immediately after the `geo = [ ... ]` block under `[project.optional-dependencies]`:

```toml
polars = [
    "polars>=1.0.0",
]
```

- [ ] **Step 4: Install the extra into the dev venv and verify**

Run: `uv pip install -e '.[polars]' && uv run python -c "import polars; print(polars.__version__)"`
Expected: prints a version ≥ 1.0.0 (refreshes `uv.lock` if needed — `uv lock` then commit the lock change).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest --no-cov -q tests/test_polars_packaging.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/test_polars_packaging.py
git commit -m "feat(polars): add [polars] optional extra"
```

(No CHANGELOG entry — plumbing; nothing user-visible works yet.)

---

## Task 2: Add `LineageMetadata.engine` field

The only new lineage field. Defaults to `None`; omitted from serialized output when `None` so legacy `datasets.lock.yaml` files don't churn.

**Files:**
- Modify: `src/sunstone/lineage.py` (`LineageMetadata` dataclass ~line 439; `to_dict()` ~line 541)
- Test: `tests/test_lineage_persistence.py` (Modify — append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_persistence.py  (append)
from sunstone.lineage import LineageMetadata


def test_engine_field_defaults_to_none() -> None:
    lm = LineageMetadata()
    assert lm.engine is None


def test_engine_omitted_when_none() -> None:
    lm = LineageMetadata()
    assert "engine" not in lm.to_dict()


def test_engine_serialized_when_set() -> None:
    lm = LineageMetadata(engine="polars")
    assert lm.to_dict()["engine"] == "polars"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/test_lineage_persistence.py -k engine`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'engine'`.

- [ ] **Step 3: Add the field**

In `src/sunstone/lineage.py`, inside `@dataclass class LineageMetadata`, after the `field_derivations` field (~line 466) add:

```python
    engine: Optional[str] = None
    """Engine that produced the in-memory representation: "pandas" / "polars"
    / None (legacy / unspecified). Provenance only; omitted from serialised
    output when None so unchanged lock files don't churn."""
```

- [ ] **Step 4: Omit-when-None in `to_dict()`**

In `LineageMetadata.to_dict()` (~line 558), after the `data_hash` block and before `return result`:

```python
        if self.engine is not None:
            result["engine"] = self.engine
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_lineage_persistence.py`
Expected: PASS (existing tests unchanged + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py tests/test_lineage_persistence.py
git commit -m "feat(lineage): add optional engine field to LineageMetadata"
```

---

## Task 3: Back-fill `engine="pandas"` on pandas reads/writes

So audits can distinguish engines once polars lands. Read path and both write sites.

**Files:**
- Modify: `src/sunstone/pandas/read.py` (`read_dataset`, the lineage-build block ~line 175)
- Modify: `src/sunstone/pandas/write.py` (`to_csv` ~line 267, `to_parquet` ~line 443)
- Test: `tests/test_dataframe.py` (Modify — append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dataframe.py  (append to the module)
def test_read_stamps_pandas_engine(project_path) -> None:
    import sunstone
    df = sunstone.DataFrame.read_csv(
        "inputs/official_un_member_states_raw.csv",
        project_path=project_path,
        strict=False,
    )
    assert df.metadata.lineage.engine == "pandas"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/test_dataframe.py::test_read_stamps_pandas_engine`
Expected: FAIL — `assert None == "pandas"`.

- [ ] **Step 3: Stamp on read**

In `src/sunstone/pandas/read.py`, inside `read_dataset`, right after the lineage is created (~line 175, after `metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))`):

```python
        metadata.lineage.engine = "pandas"
```

- [ ] **Step 4: Stamp on write (both sites)**

In `src/sunstone/pandas/write.py`, in `to_csv` immediately after `effective_lineage = self.metadata.lineage` (~line 267):

```python
        effective_lineage.engine = "pandas"
```

Do the identical insert in `to_parquet` after its `effective_lineage = self.metadata.lineage` (~line 443). (If a `to_json` writer exists with the same `effective_lineage = self.metadata.lineage` line, add it there too — grep `effective_lineage = self.metadata.lineage` to confirm all sites.)

- [ ] **Step 5: Add a write-side test and run**

```python
# tests/test_dataframe.py  (append)
def test_write_stamps_pandas_engine(project_copy) -> None:
    import sunstone
    df = sunstone.DataFrame.read_csv(
        "inputs/official_un_member_states_raw.csv",
        project_path=project_copy,
        strict=False,
    )
    out = df.to_csv("outputs/out.csv", slug="out-data", name="Out", index=False)
    assert df.metadata.lineage.engine == "pandas"
```

Run: `uv run pytest --no-cov -q tests/test_dataframe.py -k pandas_engine`
Expected: PASS (both).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/pandas/read.py src/sunstone/pandas/write.py tests/test_dataframe.py
git commit -m "feat(pandas): stamp engine=\"pandas\" on read/write lineage"
```

---

## Task 4: `Asset.as_polars()` typed accessor

Mirrors `as_table()`. Lazy polars import inside the method.

**Files:**
- Modify: `src/sunstone/asset.py` (after `as_table()` ~line 64)
- Test: `tests/test_asset.py` (Create if absent, else append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_asset.py
import pytest
from sunstone.asset import Asset, AssetKind
from sunstone.errors import IncompatibleAssetKindError
from sunstone.lineage import Metadata


def _tabular(payload) -> Asset:
    return Asset(payload=payload, kind=AssetKind.TABULAR, metadata=Metadata())


def test_as_polars_returns_payload() -> None:
    pl = pytest.importorskip("polars")
    frame = pl.DataFrame({"a": [1, 2]})
    asset = _tabular(frame)
    assert asset.as_polars() is frame


def test_as_polars_wrong_kind_raises() -> None:
    pytest.importorskip("polars")
    asset = Asset(payload=b"x", kind=AssetKind.BLOB, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError):
        asset.as_polars()


def test_as_polars_on_pandas_payload_raises_typeerror() -> None:
    pytest.importorskip("polars")
    import pandas as pd
    asset = _tabular(pd.DataFrame({"a": [1]}))
    with pytest.raises(TypeError, match="pl.from_pandas"):
        asset.as_polars()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_asset.py -k as_polars`
Expected: FAIL — `AttributeError: 'Asset' object has no attribute 'as_polars'`.

- [ ] **Step 3: Implement `as_polars()`**

In `src/sunstone/asset.py`, immediately after the `as_table()` method (~line 64):

```python
    def as_polars(self) -> "pl.DataFrame":
        """Return the payload as a polars DataFrame (no conversion).

        Raises IncompatibleAssetKindError if kind is not TABULAR, and TypeError
        if the payload is a pandas DataFrame (use pl.from_pandas explicitly;
        lineage-preserving conversion is Spec 5).
        """
        if self.kind is not AssetKind.TABULAR:
            raise IncompatibleAssetKindError(expected=AssetKind.TABULAR, actual=self.kind)
        import polars as pl

        if not isinstance(self.payload, pl.DataFrame):
            type_name = type(self.payload).__module__ + "." + type(self.payload).__qualname__
            raise TypeError(
                f"Asset payload is {type_name}, not a polars.DataFrame. "
                "If it is a pandas DataFrame, convert explicitly with pl.from_pandas(asset.as_table())."
            )
        return self.payload
```

Add the type-checking import near the top of `asset.py` (in the existing `if TYPE_CHECKING:` block):

```python
    import polars as pl
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_asset.py -k as_polars`
Expected: PASS (3).

- [ ] **Step 5: Verify lazy import preserved**

Run: `uv run python -c "import sunstone.asset, sys; assert 'polars' not in sys.modules; print('ok')"`
Expected: prints `ok` (importing the module must not import polars).

- [ ] **Step 6: Commit + CHANGELOG**

Add to CHANGELOG `[Unreleased]`:
```
- Added: `Asset.as_polars()` typed accessor for polars-payload assets.
```

```bash
git add src/sunstone/asset.py tests/test_asset.py CHANGELOG.md
git commit -m "feat(asset): add as_polars() typed accessor"
```

---

## Task 5: `BuiltinFormatHandler` gains an `engine` knob

`engine="polars"` makes `read()` return an `Asset` whose payload is a `pl.DataFrame`, and `write()` accept one. Polars import is lazy (inside read/write), keeping `import sunstone.handlers` cheap.

**Files:**
- Modify: `src/sunstone/handlers.py` (`_get_reader` ~line 82; `BuiltinFormatHandler.read`/`write`/`_read_to_dataframe`/`_write_dataframe`)
- Test: `tests/test_handlers.py` (append)

- [ ] **Step 1: Write the failing test (round-trip via the handler directly)**

```python
# tests/test_handlers.py  (append)
import io
import pytest
from sunstone.asset import AssetKind
from sunstone.handlers import BuiltinFormatHandler


def test_builtin_handler_reads_csv_as_polars() -> None:
    pl = pytest.importorskip("polars")
    raw = b"a,b\n1,x\n2,y\n"
    handler = BuiltinFormatHandler()
    asset = handler.read(io.BytesIO(raw), format="csv", path="t.csv", engine="polars")
    assert asset.kind is AssetKind.TABULAR
    assert isinstance(asset.payload, pl.DataFrame)
    assert asset.payload.columns == ["a", "b"]


def test_builtin_handler_writes_polars_csv() -> None:
    pl = pytest.importorskip("polars")
    from sunstone.asset import Asset
    from sunstone.lineage import Metadata
    asset = Asset(payload=pl.DataFrame({"a": [1, 2]}), kind=AssetKind.TABULAR, metadata=Metadata())
    buf = io.BytesIO()
    BuiltinFormatHandler().write(asset, buf, format="csv", path="t.csv", engine="polars")
    assert buf.getvalue().startswith(b"a\n1\n2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_handlers.py -k polars`
Expected: FAIL — engine kwarg flows into the pandas reader and raises (unexpected keyword), or payload type mismatch.

- [ ] **Step 3: Add a lazy polars reader/writer map**

In `src/sunstone/handlers.py`, near `_get_reader` (~line 82) add:

```python
def _get_polars_reader(fmt: str) -> "Callable[..., object]":
    """Resolve a polars reader lazily (keeps import sunstone.handlers cheap)."""
    import polars as pl

    if fmt == "csv":
        return pl.read_csv
    if fmt == "json":
        return pl.read_json
    if fmt == "parquet":
        return pl.read_parquet
    if fmt == "tsv":
        return lambda src, **kw: pl.read_csv(src, separator="\t", **kw)
    raise KeyError(fmt)


_POLARS_WRITER_MAP: dict[str, str] = {
    "csv": "write_csv",
    "json": "write_json",
    "parquet": "write_parquet",
}
```

- [ ] **Step 4: Branch `read()` and `write()` on engine**

Replace `BuiltinFormatHandler.read` (~line 157) with:

```python
    def read(self, stream: "BinaryIO | Path", **kwargs: object) -> "Asset":
        from .asset import Asset, AssetKind
        from .lineage import Metadata

        engine = kwargs.pop("engine", "pandas")
        if engine == "polars":
            payload: object = self._read_to_polars(stream, **kwargs)
        else:
            payload = self._read_to_dataframe(stream, **kwargs)
        return Asset(payload=payload, kind=AssetKind.TABULAR, metadata=Metadata())
```

Add `_read_to_polars` next to `_read_to_dataframe`:

```python
    def _read_to_polars(self, stream: "BinaryIO | Path", **kwargs: object) -> object:
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        kwargs.pop("dialect", None)  # polars dialect handling is Spec-1-out-of-scope
        if isinstance(stream, Path) and path is None:
            path = stream
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"
        reader = _get_polars_reader(str(fmt))
        return reader(stream, **kwargs)
```

Replace `BuiltinFormatHandler.write` (~line 184) with:

```python
    def write(self, asset: object, stream: "BinaryIO", **kwargs: object) -> None:
        engine = kwargs.pop("engine", "pandas")
        if engine == "polars":
            self._write_polars(asset, stream, **kwargs)
            return
        df = asset.as_table() if hasattr(asset, "as_table") else asset
        self._write_dataframe(df, stream, **kwargs)  # type: ignore[arg-type]
```

Add `_write_polars`:

```python
    def _write_polars(self, asset: object, stream: "BinaryIO", **kwargs: object) -> None:
        pdf = asset.as_polars() if hasattr(asset, "as_polars") else asset
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        kwargs.pop("dialect", None)
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"
        method_name = _POLARS_WRITER_MAP[str(fmt)]
        getattr(pdf, method_name)(stream, **kwargs)
```

Confirm `_resolve_format` accepts `parquet` — extend `_EXTENSION_MAP`/`_READER_FORMATS` (~lines 64–79) to include parquet if missing:

```python
_EXTENSION_MAP = {".csv": "csv", ".json": "json", ".xlsx": "excel", ".tsv": "tsv", ".parquet": "parquet"}
_READER_FORMATS = frozenset({"csv", "json", "excel", "tsv", "parquet"})
```

- [ ] **Step 5: Run tests to verify they pass; verify lazy import**

Run: `uv run pytest --no-cov -q tests/test_handlers.py`
Expected: PASS (new + existing pandas handler tests unchanged).
Run: `uv run python -c "import sunstone.handlers, sys; assert 'polars' not in sys.modules; print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "feat(handlers): add engine=polars knob to BuiltinFormatHandler"
```

(No CHANGELOG — internal handler plumbing.)

---

## Task 6: `sunstone.read(path, payload="polars")` dispatch knob

Threads `engine` into the tabular fallback so `ss.read(path, payload="polars")` returns a polars-payload Asset.

**Files:**
- Modify: `src/sunstone/__init__.py` (`read()` ~line 57; tabular fallback ~line 116)
- Test: `tests/test_read_dispatch.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_read_dispatch.py
import pytest
import sunstone
from sunstone.asset import AssetKind


def test_read_payload_polars(project_path) -> None:
    pl = pytest.importorskip("polars")
    asset = sunstone.read(
        str(project_path / "inputs/official_un_member_states_raw.csv"),
        payload="polars",
    )
    assert asset.kind is AssetKind.TABULAR
    assert isinstance(asset.payload, pl.DataFrame)


def test_read_payload_pandas_default(project_path) -> None:
    import pandas as pd
    asset = sunstone.read(str(project_path / "inputs/official_un_member_states_raw.csv"))
    assert isinstance(asset.payload, pd.DataFrame)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/test_read_dispatch.py`
Expected: FAIL — `read() got an unexpected keyword argument 'payload'`.

- [ ] **Step 3: Add `payload=` and thread engine**

In `src/sunstone/__init__.py`, add the parameter to `read()` (after `extras`):

```python
    payload: str = "pandas",
```

In the tabular fallback (~line 116), replace:

```python
    if asset is None:
        asset = _read_tabular_asset(path, format=format, **kw)
```
with:
```python
    if asset is None:
        engine = "polars" if payload == "polars" else "pandas"
        asset = _read_tabular_asset(path, format=format, engine=engine, **kw)
```

Update the docstring to note: *"`payload` selects the returned Asset's payload type — `\"pandas\"` (default) or `\"polars\"`; it maps 1:1 to the `engine` recorded on lineage."* (See the spec's terminology note.)

`_read_tabular_asset` already forwards `**kw` (including `engine`) into `handler.read(...)`, where `BuiltinFormatHandler.read` consumes it (Task 5). No change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_read_dispatch.py`
Expected: PASS (2).

- [ ] **Step 5: Regression — full suite**

Run: `uv run pytest --no-cov -q && uv run mypy src/`
Expected: all green; mypy clean.

- [ ] **Step 6: Commit + CHANGELOG**

Add to CHANGELOG `[Unreleased]`:
```
- Added: `sunstone.read(path, payload="polars")` returns a polars-payload Asset.
```

```bash
git add src/sunstone/__init__.py tests/test_read_dispatch.py CHANGELOG.md
git commit -m "feat: add payload=polars dispatch to sunstone.read"
```

---

## Task 7: `sunstone.polars` package skeleton + lazy-load wiring

Empty-ish package with the import guard, wired into `sunstone`'s lazy submodule table. `import sunstone` must pull neither polars nor pandas.

**Files:**
- Create: `src/sunstone/polars/__init__.py`, `core.py`, `io.py`, `metadata.py`
- Modify: `src/sunstone/__init__.py` (`_LAZY_SUBMODULES` ~line 248; TYPE_CHECKING import ~line 255)
- Test: `tests/test_polars_lazyload.py` (Create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_polars_lazyload.py
import subprocess
import sys


def _run(code: str) -> str:
    return subprocess.check_output([sys.executable, "-c", code], text=True).strip()


def test_import_sunstone_pulls_neither_engine() -> None:
    out = _run(
        "import sunstone, sys;"
        "print('polars' in sys.modules, 'pandas' in sys.modules)"
    )
    assert out == "False False"


def test_from_sunstone_import_polars_pulls_polars_only() -> None:
    import pytest
    pytest.importorskip("polars")
    out = _run(
        "from sunstone import polars; import sys;"
        "print('polars' in sys.modules, 'pandas' in sys.modules)"
    )
    assert out == "True False"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_polars_lazyload.py`
Expected: FAIL — `from sunstone import polars` raises `AttributeError` (submodule not wired).

- [ ] **Step 3: Create the package files**

`src/sunstone/polars/__init__.py`:
```python
"""Polars-compatible API for Sunstone DataFrames (eager mode, Spec 1).

Mirrors `sunstone.pandas`. A `DataFrame` here is a thin facade over an
`AssetKind.TABULAR` Asset whose payload is a `polars.DataFrame`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    import polars as _pl  # noqa: F401
except ImportError as e:  # pragma: no cover - exercised via subprocess in tests
    raise ImportError(
        "Polars support requires the [polars] extra. Install with: pip install 'sunstone-py[polars]'"
    ) from e

# Pass-through polars symbols (re-export with the explicit `X as X` form).
from polars import (
    Int64 as Int64,
    Series as Series,
    col as col,
    lit as lit,
    when as when,
)

if TYPE_CHECKING:
    from .core import DataFrame

__all__ = [
    "read_csv",
    "read_parquet",
    "read_json",
    "read_dataset",
    "DataFrame",
    "Series",
    "col",
    "lit",
    "when",
    "Int64",
]


def __getattr__(name: str) -> Any:
    """Lazy-load facade symbols (keeps the import light)."""
    if name == "DataFrame":
        from .core import DataFrame as _DataFrame

        return _DataFrame
    if name in ("read_csv", "read_parquet", "read_json", "read_dataset"):
        from . import io as _io

        return getattr(_io, name)
    raise AttributeError(f"module 'sunstone.polars' has no attribute {name!r}")
```

`src/sunstone/polars/core.py`:
```python
"""The polars DataFrame facade (skeleton — filled in Tasks 8 & 10)."""
from __future__ import annotations
```

`src/sunstone/polars/io.py`:
```python
"""Polars read/write facades (filled in Tasks 9 & 11)."""
from __future__ import annotations
```

`src/sunstone/polars/metadata.py`:
```python
"""Polars facade metadata accessors (filled in Task 8)."""
from __future__ import annotations
```

- [ ] **Step 4: Wire the lazy submodule**

In `src/sunstone/__init__.py`:
- `_LAZY_SUBMODULES` (~line 248): add `"polars"` →
  ```python
  _LAZY_SUBMODULES: frozenset[str] = frozenset({"errors", "packaging", "pandas", "polars"})
  ```
- TYPE_CHECKING import (~line 255): add `polars` →
  ```python
      from . import errors, packaging, pandas, polars  # noqa: F401
  ```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_polars_lazyload.py`
Expected: PASS (2).

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/polars/ src/sunstone/__init__.py tests/test_polars_lazyload.py
git commit -m "feat(polars): package skeleton + lazy-load wiring"
```

---

## Task 8: `pl.DataFrame` facade class (core.py + metadata.py)

Composition over an `Asset`. Construction from a polars frame, an existing Asset, or a pandas frame (converted via `pl.from_pandas`). Metadata accessors + `set_field_metadata`.

**Files:**
- Modify: `src/sunstone/polars/core.py`, `src/sunstone/polars/metadata.py`
- Test: `tests/test_polars.py` (Create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_polars.py
import pytest

pl = pytest.importorskip("polars")
from sunstone.asset import Asset, AssetKind          # noqa: E402
from sunstone.lineage import Metadata                # noqa: E402
from sunstone.polars import DataFrame                # noqa: E402


def test_construct_from_polars_frame() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2]}))
    assert df.asset.kind is AssetKind.TABULAR
    assert isinstance(df.data, pl.DataFrame)
    assert df.data.columns == ["a"]


def test_construct_from_asset() -> None:
    asset = Asset(payload=pl.DataFrame({"a": [1]}), kind=AssetKind.TABULAR, metadata=Metadata())
    df = DataFrame(asset=asset)
    assert df.asset is asset


def test_construct_from_pandas_converts() -> None:
    import pandas as pd
    df = DataFrame(pd.DataFrame({"a": [1, 2]}))
    assert isinstance(df.data, pl.DataFrame)


def test_set_field_metadata_chainable() -> None:
    df = DataFrame(pl.DataFrame({"a": [1]}))
    out = df.set_field_metadata("a", description="amount", unit="kg")
    assert out is df
    assert df.metadata.field_metadata["a"].unit == "kg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_polars.py`
Expected: FAIL — `ImportError: cannot import name 'DataFrame'` then `TypeError` (skeleton has no class).

- [ ] **Step 3: Implement `metadata.py` (mixin)**

```python
# src/sunstone/polars/metadata.py
"""Polars facade metadata accessors + set_field_metadata."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from sunstone.lineage import FieldSchema, Metadata

if TYPE_CHECKING:
    from .core import DataFrame


class MetadataMixin:
    """Property accessors + field metadata. Assumes `self.metadata: Metadata`."""

    if TYPE_CHECKING:
        @property
        def metadata(self) -> Metadata: ...

    @property
    def description(self) -> Optional[str]:
        return self.metadata.description

    @description.setter
    def description(self, value: Optional[str]) -> None:
        self.metadata.description = value

    @property
    def rdf_prefixes(self) -> Optional[Dict[str, str]]:
        return self.metadata.rdf_prefixes

    @rdf_prefixes.setter
    def rdf_prefixes(self, value: Optional[Dict[str, str]]) -> None:
        self.metadata.rdf_prefixes = value

    @property
    def custom_properties(self) -> Optional[Dict[str, Any]]:
        return self.metadata.custom_properties

    @custom_properties.setter
    def custom_properties(self, value: Optional[Dict[str, Any]]) -> None:
        self.metadata.custom_properties = value

    def set_field_metadata(
        self,
        column: str,
        *,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        source: Optional[str] = None,
        type: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> "DataFrame":
        if unit is not None:
            from sunstone.units import get_unit_mode, parse_unit_string

            if get_unit_mode() != "relaxed":
                parse_unit_string(unit)

        existing = self.metadata.field_metadata.get(column)
        if existing:
            if description is not None:
                existing.description = description
            if unit is not None:
                existing.unit = unit
            if source is not None:
                existing.source = source
            if type is not None:
                existing.type = type
            if constraints is not None:
                existing.constraints = constraints
            if custom_properties is not None:
                merged = dict(existing.custom_properties or {})
                merged.update(custom_properties)
                existing.custom_properties = merged or None
        else:
            self.metadata.field_metadata[column] = FieldSchema(
                name=column, type=type, description=description, unit=unit,
                source=source, constraints=constraints,
                custom_properties=custom_properties or None,
            )

        if source is not None:
            from sunstone.lineage import FieldDerivation

            if self.metadata.lineage.field_derivations is None:
                self.metadata.lineage.field_derivations = []
            self.metadata.lineage.field_derivations = [
                d for d in self.metadata.lineage.field_derivations if d.output_field != column
            ]
            self.metadata.lineage.field_derivations.append(
                FieldDerivation(output_field=column, source_entity=source)
            )
        return self  # type: ignore[return-value]
```

- [ ] **Step 4: Implement `core.py` (DataFrame class)**

```python
# src/sunstone/polars/core.py
"""The polars DataFrame facade: composition over an AssetKind.TABULAR Asset."""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from sunstone.lineage import Metadata
from .metadata import MetadataMixin

if TYPE_CHECKING:
    import polars as pl
    from sunstone.asset import Asset


class DataFrame(MetadataMixin):
    """Facade over an Asset whose payload is a polars DataFrame.

    `df.asset` is the Asset; `df.data is df.asset.as_polars()`;
    `df.metadata is df.asset.metadata`.
    """

    def __init__(
        self,
        data: Any = None,
        *,
        metadata: Optional[Metadata] = None,
        asset: Optional["Asset"] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        datasets_file: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        import polars as pl

        from sunstone.asset import Asset, AssetKind
        from sunstone.config import get_project_path

        if asset is not None:
            self._asset = asset
            if metadata is not None:
                self._asset.metadata = metadata
        else:
            payload = self._coerce_payload(data, pl, **kwargs)
            meta = metadata if metadata is not None else Metadata()
            self._asset = Asset(payload=payload, kind=AssetKind.TABULAR, metadata=meta)

        if strict is None:
            self.strict_mode = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower() in ("1", "true")
        else:
            self.strict_mode = strict

        if project_path is not None:
            self.metadata.lineage.project_path = str(Path(project_path).resolve())
        elif self.metadata.lineage.project_path is None:
            self.metadata.lineage.project_path = str(get_project_path())

        self._datasets_file = datasets_file

    @staticmethod
    def _coerce_payload(data: Any, pl: Any, **kwargs: Any) -> "pl.DataFrame":
        import pandas as pd

        if data is None:
            return pl.DataFrame(**kwargs) if kwargs else pl.DataFrame()
        if isinstance(data, pl.DataFrame):
            return data
        if isinstance(data, pd.DataFrame):
            return pl.from_pandas(data)
        return pl.DataFrame(data, **kwargs)

    @property
    def asset(self) -> "Asset":
        return self._asset

    @property
    def data(self) -> "pl.DataFrame":
        return self._asset.as_polars()

    @data.setter
    def data(self, value: "pl.DataFrame") -> None:
        self._asset.payload = value

    @property
    def metadata(self) -> Metadata:
        return self._asset.metadata

    @metadata.setter
    def metadata(self, value: Metadata) -> None:
        self._asset.metadata = value

    def __len__(self) -> int:
        return self.data.height

    def __repr__(self) -> str:
        return repr(self.data) + f"\n\nLineage: {len(self.metadata.lineage.sources)} source(s)"

    def __str__(self) -> str:
        return str(self.data)
```

- [ ] **Step 5: Run tests to verify they pass; line-budget + mypy**

Run: `uv run pytest --no-cov -q tests/test_polars.py`
Expected: PASS (4).
Run: `wc -l src/sunstone/polars/*.py` → confirm each < 400.
Run: `uv run mypy src/`
Expected: clean.

- [ ] **Step 6: Commit + CHANGELOG**

Add to CHANGELOG `[Unreleased]`:
```
- Added: `sunstone.polars.DataFrame` facade over a polars-backed Asset.
```

```bash
git add src/sunstone/polars/core.py src/sunstone/polars/metadata.py tests/test_polars.py CHANGELOG.md
git commit -m "feat(polars): DataFrame facade class + metadata accessors"
```

---

## Task 9: Read facades (io.py — reads)

`read_dataset` (slug) resolves via `DatasetsManager`, reads bytes once (file-content hash), parses into polars via the engine-aware handler, and builds construction-time lineage with `engine="polars"`. `read_csv`/`read_parquet`/`read_json` detect slug-vs-path and delegate.

**Files:**
- Modify: `src/sunstone/polars/io.py`
- Test: `tests/test_polars.py` (append), `tests/test_polars_lineage.py` (Create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_polars_lineage.py
import hashlib
import pytest

pl = pytest.importorskip("polars")
import sunstone.polars as spl                          # noqa: E402
from sunstone.exceptions import DatasetNotFoundError   # noqa: E402

CSV = "inputs/official_un_member_states_raw.csv"


def test_read_csv_returns_facade_with_polars_payload(project_path) -> None:
    df = spl.read_csv(CSV, project_path=project_path, strict=False)
    assert isinstance(df, spl.DataFrame)
    assert isinstance(df.data, pl.DataFrame)
    assert df.data.height > 0


def test_read_csv_lineage(project_path) -> None:
    df = spl.read_csv(CSV, project_path=project_path, strict=False)
    lin = df.metadata.lineage
    assert lin.engine == "polars"
    assert len(lin.sources) == 1
    assert lin.activity is None
    expected = "sha256:" + hashlib.sha256((project_path / CSV).read_bytes()).hexdigest()
    assert lin.data_hash == expected
    assert lin.field_derivations and len(lin.field_derivations) == len(df.data.columns)


def test_read_csv_unregistered_strict_raises(project_path) -> None:
    with pytest.raises(DatasetNotFoundError):
        spl.read_csv("inputs/nope.csv", project_path=project_path, strict=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_polars_lineage.py`
Expected: FAIL — `read_csv` not implemented (AttributeError via `io`).

- [ ] **Step 3: Implement `io.py` readers**

```python
# src/sunstone/polars/io.py
"""Polars read facades. Reads route bytes through the plugin URL handler
(for a file-content hash) and parse via the engine-aware BuiltinFormatHandler."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from sunstone.config import get_project_path
from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetNotFoundError
from sunstone.lineage import LineageMetadata, Metadata

if TYPE_CHECKING:
    from .core import DataFrame

_PathLike = Union[str, Path]


def read_dataset(
    slug: str,
    project_path: Optional[_PathLike] = None,
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    format: Optional[str] = None,
    **kwargs: Any,
) -> "DataFrame":
    from sunstone.plugins import PluginRegistry, no_url_handler_error
    from .core import DataFrame

    if project_path is None:
        project_path = get_project_path()
    manager = DatasetsManager(project_path)

    dataset = manager.find_dataset_by_slug(slug)
    if dataset is None:
        raise DatasetNotFoundError(
            f"Dataset with slug '{slug}' not found in datasets.yaml. Check that the dataset is registered."
        )

    absolute_path = manager.get_absolute_path(dataset.location)
    if not absolute_path.exists() and fetch_from_url:
        if dataset.source and dataset.source.location.data:
            absolute_path = manager.fetch_from_url(dataset)
        else:
            raise FileNotFoundError(
                f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
            )

    if format is None and dataset.format is not None:
        format = dataset.format

    location = str(absolute_path)
    registry = PluginRegistry.get(manager.project_path)
    handler = registry.find_format_reader(location, format)
    if handler is None:
        raise ValueError(f"No format handler found for {absolute_path.name!r} (format={format!r}).")
    url_handler = registry.find_url_handler(location)
    if url_handler is None:
        raise no_url_handler_error(location)

    # Read raw bytes once: hash them, then parse from the same bytes.
    import io as _io

    with url_handler.open(location, "rb") as stream:
        raw = stream.read()
    data_hash = "sha256:" + hashlib.sha256(raw).hexdigest()

    asset = handler.read(
        _io.BytesIO(raw), format=format, path=location, dialect=dataset.dialect, engine="polars", **kwargs
    )

    metadata = Metadata(
        lineage=LineageMetadata(project_path=str(manager.project_path), data_hash=data_hash, engine="polars")
    )
    metadata.lineage.add_source(dataset)
    metadata.lineage.populate_field_derivations(list(asset.payload.columns), slug)
    asset.metadata = metadata

    from sunstone.session import DatasetRead, get_session

    get_session().record_read(DatasetRead(slug=slug))

    return DataFrame(asset=asset, strict=strict, project_path=project_path)


def _read_path_or_slug(
    location: _PathLike,
    project_path: Optional[_PathLike],
    strict: Optional[bool],
    fetch_from_url: bool,
    format: Optional[str],
    **kwargs: Any,
) -> "DataFrame":
    """Resolve a path/slug to a registered dataset, then read it as polars."""
    if project_path is None:
        project_path = get_project_path()
    manager = DatasetsManager(project_path)

    loc = str(location)
    # A bare slug has no path separators and no suffix.
    is_slug = "/" not in loc and "\\" not in loc and not Path(loc).suffix
    if is_slug:
        return read_dataset(loc, project_path, strict, fetch_from_url, format, **kwargs)

    dataset = manager.find_dataset_by_location(loc) if hasattr(manager, "find_dataset_by_location") else None
    if dataset is None:
        dataset = manager.find_dataset_by_slug(Path(loc).stem)
    if dataset is None:
        raise DatasetNotFoundError(
            f"'{loc}' is not registered in datasets.yaml. Register it or read by slug."
        )
    return read_dataset(dataset.slug, project_path, strict, fetch_from_url, format, **kwargs)


def read_csv(filepath_or_buffer: _PathLike, project_path: Optional[_PathLike] = None,
             strict: Optional[bool] = None, fetch_from_url: bool = True, **kwargs: Any) -> "DataFrame":
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "csv", **kwargs)


def read_parquet(filepath_or_buffer: _PathLike, project_path: Optional[_PathLike] = None,
                 strict: Optional[bool] = None, fetch_from_url: bool = True, **kwargs: Any) -> "DataFrame":
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "parquet", **kwargs)


def read_json(filepath_or_buffer: _PathLike, project_path: Optional[_PathLike] = None,
              strict: Optional[bool] = None, fetch_from_url: bool = True, **kwargs: Any) -> "DataFrame":
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "json", **kwargs)
```

> **Note on `find_dataset_by_location`:** `read_csv` in the pandas facade resolves a path against `datasets.yaml`. The exact resolver method name on `DatasetsManager` should be confirmed during implementation (`grep "def find_dataset" src/sunstone/datasets.py`). The fallback above (`stem` → slug) covers the common `inputs/foo.csv` ↔ slug case used by the test fixture; adjust to the real resolver if a dedicated location lookup exists.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_polars_lineage.py tests/test_polars.py`
Expected: PASS. If the path→slug resolution fails for the fixture, register the CSV's slug in `tests/testdata/UNMembersProject/datasets.yaml` or read by slug in the test — confirm the fixture's actual slug with `grep slug tests/testdata/UNMembersProject/datasets.yaml`.

- [ ] **Step 5: mypy + line budget**

Run: `uv run mypy src/ && wc -l src/sunstone/polars/io.py`
Expected: clean; `io.py` < 400 lines.

- [ ] **Step 6: Commit + CHANGELOG**

Add to CHANGELOG `[Unreleased]`:
```
- Added: `sunstone.polars` readers (`read_csv`/`read_parquet`/`read_json`/`read_dataset`) with lineage tracking.
```

```bash
git add src/sunstone/polars/io.py tests/test_polars.py tests/test_polars_lineage.py CHANGELOG.md
git commit -m "feat(polars): read facades with construction-time lineage"
```

---

## Task 10: Op boundary contract (`__getattr__` in core.py)

Delegate unknown attribute access to the underlying polars frame. DataFrame-returning ops re-wrap via `Asset.derive(new_payload, derived_from=[self.asset])` (parent sources propagate; `activity` stays `None`; `engine="polars"`). Non-DataFrame returns pass through.

**Files:**
- Modify: `src/sunstone/polars/core.py`
- Test: `tests/test_polars.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_polars.py  (append)
def test_filter_returns_wrapped_with_parent_sources(project_path) -> None:
    import sunstone.polars as spl
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_path, strict=False)
    out = df.filter(pl.col(df.data.columns[0]).is_not_null())
    assert isinstance(out, spl.DataFrame)
    assert out.metadata.lineage.sources == df.metadata.lineage.sources
    assert out.metadata.lineage.activity is None
    assert out.metadata.lineage.engine == "polars"


def test_scalar_attrs_pass_through() -> None:
    df = DataFrame(pl.DataFrame({"a": [1, 2, 3]}))
    assert df.height == 3
    assert df.columns == ["a"]
    assert df.shape == (3, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/test_polars.py -k "filter or pass_through"`
Expected: FAIL — `AttributeError: 'DataFrame' object has no attribute 'filter'` (no `__getattr__` yet).

- [ ] **Step 3: Implement `__getattr__` + wrap helper**

Add to `src/sunstone/polars/core.py` `DataFrame`:

```python
    def _wrap(self, result: Any) -> Any:
        import polars as pl

        if isinstance(result, pl.DataFrame):
            child = self._asset.derive(result, derived_from=[self._asset])
            child.metadata.lineage.engine = "polars"
            return DataFrame(asset=child, strict=self.strict_mode)
        return result

    def __getattr__(self, name: str) -> Any:
        # Guard against recursion before _asset exists (construction/unpickle).
        if name == "_asset" or name.startswith("__"):
            raise AttributeError(name)
        attr = getattr(self._asset.as_polars(), name)
        if callable(attr):
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._wrap(attr(*args, **kwargs))

            return wrapper
        return self._wrap(attr)

    def __getitem__(self, key: Any) -> Any:
        return self._wrap(self._asset.as_polars()[key])
```

> **Why `derive` and not a manual copy:** `Asset.derive(payload, derived_from=[self.asset])` calls `_build_child_lineage`, which snapshots the parent's slug into `sources` (or collapses to the parent's own sources when the parent has no slug) and carries no `Activity`. That absence is the honest signal that the op is untracked (Spec 2 will populate `Activity`). Note `derive` clears `data_hash` (recomputed on write) and resets slug/name — correct for a derived frame.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_polars.py`
Expected: PASS (incl. `select`/`with_columns`/`group_by` behave the same — add one such assertion if desired).

- [ ] **Step 5: mypy + full suite**

Run: `uv run mypy src/ && uv run pytest --no-cov -q`
Expected: clean; green.

- [ ] **Step 6: Commit + CHANGELOG**

Add to CHANGELOG `[Unreleased]`:
```
- Added: polars facade chains operations, propagating source lineage (op-level Activity tracking is deferred).
```

```bash
git add src/sunstone/polars/core.py tests/test_polars.py CHANGELOG.md
git commit -m "feat(polars): op boundary re-wraps results via Asset.derive"
```

---

## Task 11: Write facades (io.py — writes + LineageWarning)

`write_csv`/`write_parquet`/`write_json` instance methods: stamp slug/name, ensure `engine="polars"`, emit a one-shot `LineageWarning` when the asset is detectably derived but has no `Activity`, then delegate to `sunstone.write(self.asset, path, format=..., engine="polars")`.

**Files:**
- Modify: `src/sunstone/polars/io.py` (writer helper), `src/sunstone/polars/core.py` (bind methods)
- Test: `tests/test_polars_lineage.py` (append)

- [ ] **Step 1: Confirm the warning type**

Run: `grep -rn "class LineageWarning" src/sunstone/` — confirm the import path (expected `sunstone.exceptions` or `sunstone.errors`). Use the real path below in place of `LINEAGE_WARNING_IMPORT`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_polars_lineage.py  (append)
import warnings


def test_write_csv_roundtrips_and_updates_lock(project_copy) -> None:
    import sunstone.polars as spl
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    df.write_csv("outputs/out.csv", slug="out-data", name="Out")
    assert (project_copy / "outputs/out.csv").exists()


def test_write_derived_emits_lineage_warning(project_copy) -> None:
    import sunstone.polars as spl
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    derived = df.head(5)  # different output slug, activity is None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        derived.write_csv("outputs/derived.csv", slug="derived-data", name="Derived")
    assert sum("Activity" in str(w.message) for w in caught) == 1


def test_write_fresh_read_no_warning(project_copy) -> None:
    import sunstone.polars as spl
    df = spl.read_csv("inputs/official_un_member_states_raw.csv", project_path=project_copy, strict=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # write under the SAME slug as the source → not "derived"
        src_slug = df.metadata.lineage.sources[0].slug
        df.write_csv("outputs/same.csv", slug=src_slug, name="Same")
    assert not any("Activity" in str(w.message) for w in caught)
```

- [ ] **Step 3: Implement the writer helper in `io.py`**

```python
# src/sunstone/polars/io.py  (append)
import warnings

from LINEAGE_WARNING_IMPORT import LineageWarning  # replace with the real path from Step 1


def _emit_derivation_warning_if_needed(asset: Any, slug: str) -> None:
    lin = asset.metadata.lineage
    source_slugs = {s.slug for s in lin.sources}
    is_derived = len(source_slugs) > 1 or (source_slugs and slug not in source_slugs)
    if is_derived and lin.activity is None:
        warnings.warn(
            f"Output '{slug}' written from a polars DataFrame whose derivation chain has no "
            "Activity records. Operation-level lineage is not yet tracked for the polars engine. See Spec 2.",
            LineageWarning,
            stacklevel=3,
        )


def _write(df: "DataFrame", path: str, *, format: str, slug: str, name: str, **kwargs: Any) -> None:
    import sunstone

    asset = df.asset
    asset.metadata.slug = slug
    asset.metadata.name = name
    asset.metadata.lineage.engine = "polars"
    _emit_derivation_warning_if_needed(asset, slug)
    sunstone.write(asset, path, format=format, engine="polars", **kwargs)
```

- [ ] **Step 4: Bind writer methods on the facade**

Add to `src/sunstone/polars/core.py` `DataFrame`:

```python
    def write_csv(self, path: str, *, slug: str, name: str, **kwargs: Any) -> None:
        from .io import _write

        _write(self, path, format="csv", slug=slug, name=name, **kwargs)

    def write_parquet(self, path: str, *, slug: str, name: str, **kwargs: Any) -> None:
        from .io import _write

        _write(self, path, format="parquet", slug=slug, name=name, **kwargs)

    def write_json(self, path: str, *, slug: str, name: str, **kwargs: Any) -> None:
        from .io import _write

        _write(self, path, format="json", slug=slug, name=name, **kwargs)
```

> **Resolving the write path:** `sunstone.write` resolves the path through the URL handler and writes via the registry's asset format handlers — `BuiltinFormatHandler.write` consumes `engine="polars"` (Task 5). If `sunstone.write` needs the path registered/relative-resolved against the project, confirm how the pandas `to_csv` resolves its output path (`grep -n "def to_csv" -A40 src/sunstone/pandas/write.py`) and route the polars writer through the same `DatasetsManager.update_output_lineage` if `datasets.lock.yaml` updates are required by the acceptance criteria. (Spec 1 requires the lock-file update; if `sunstone.write` does not already perform it, add a `manager.update_output_lineage(slug=slug, lineage=asset.metadata.lineage, data_hash=...)` call in `_write` mirroring `write.py` lines 255–284, computing the hash via `"sha256:" + hashlib.sha256(<written bytes>).hexdigest()`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/test_polars_lineage.py`
Expected: PASS (write round-trip, exactly-one warning for derived, no warning for same-slug).

- [ ] **Step 6: mypy + full suite + commit**

Run: `uv run mypy src/ && uv run pytest --no-cov -q`
Expected: clean; green.

Add to CHANGELOG `[Unreleased]`:
```
- Added: `sunstone.polars` writers (`write_csv`/`write_parquet`/`write_json`) via the central write path.
```

```bash
git add src/sunstone/polars/io.py src/sunstone/polars/core.py tests/test_polars_lineage.py CHANGELOG.md
git commit -m "feat(polars): write facades + LineageWarning for untracked derivations"
```

---

## Task 12: Docs — mark roadmap items done

**Files:**
- Modify: `docs/polars.md`, `docs/api.md`
- (No code; no tests.)

- [ ] **Step 1: Update `docs/polars.md`**

Change the four roadmap items' status from "Roadmap" to "Supported": `Asset.as_polars()`, polars-returning handlers (`engine=` knob), `sunstone.polars` facade, field-metadata bridge. Add a usage example mirroring the pandas one:

```python
from sunstone import polars as pl
import sunstone
sunstone.set_project_path(".")

df = pl.read_csv("inputs/schools.csv")          # -> sunstone.polars.DataFrame
clean = df.filter(pl.col("students") > 0)        # chained polars ops
clean.write_csv("outputs/clean.csv", slug="clean-schools", name="Clean Schools")
```

Keep the existing `payload=` vs `engine=` terminology note.

- [ ] **Step 2: Link from `docs/api.md`**

Add a `polars.md` link in the API doc's tabular/engine section (mirror the `pandas.md` link).

- [ ] **Step 3: Verify the example runs**

Run (from a scratch project with a registered `schools.csv`, or adapt to the test fixture):
`uv run python -c "from sunstone import polars as pl; print(pl.DataFrame.__module__)"`
Expected: `sunstone.polars.core`.

- [ ] **Step 4: Commit**

```bash
git add docs/polars.md docs/api.md
git commit -m "docs(polars): mark roadmap items 1-3 supported; add usage example"
```

(No CHANGELOG — docs only.)

---

## Final verification

- [ ] `uv run pytest --no-cov -q` — full suite green.
- [ ] `uv run mypy src/` — clean.
- [ ] `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/` — clean.
- [ ] Lazy-load acceptance checks:
  - `uv run python -c "import sunstone, sys; assert 'polars' not in sys.modules and 'pandas' not in sys.modules"`
  - `uv run python -c "from sunstone import polars; import sys; assert 'polars' in sys.modules and 'pandas' not in sys.modules"`
  - `uv run python -c "from sunstone import pandas; import sys; assert 'pandas' in sys.modules and 'polars' not in sys.modules"`
  - `uv run python -c "import sunstone.handlers, sys; assert 'polars' not in sys.modules"`
- [ ] `wc -l src/sunstone/polars/*.py` — every file < 400 lines.
- [ ] Spec acceptance criteria walk-through (spec §"Acceptance Criteria") — tick each against an implemented test.

---

## Self-Review notes (author)

- **Spec coverage:** Tasks 1–12 map 1:1 onto Spec 1's Order of Implementation steps 1–12. Engine-neutral substrate = Tasks 1–6; facade = Tasks 7–11; docs = Task 12.
- **Two integration points the spec under-specifies, surfaced from the real code:**
  1. `sunstone.read()` routes the tabular path through `_read_tabular_asset` (in `pandas/core.py`); the `payload`→`engine` knob threads through `**kw` into `BuiltinFormatHandler.read`, which pops `engine`. Captured in Tasks 5–6.
  2. `sunstone.read()` returns an Asset with empty `Metadata()` — it does NOT populate lineage. So the polars **read facade** (Task 9) builds construction-time lineage itself (file-content hash, `add_source`, `populate_field_derivations`, `engine="polars"`), mirroring `pandas/read.py`. The facade is "thin" only relative to format/URL/handler reuse, not lineage.
- **Unverified-at-plan-time anchors (flagged inline for the implementer to confirm with a `grep`):** the `DatasetsManager` path→dataset resolver name (Task 9), the `LineageWarning` import path (Task 11), and whether `sunstone.write` already performs the `datasets.lock.yaml` update or the polars writer must call `update_output_lineage` (Task 11). Each has a concrete fallback.
- **Type consistency:** facade exposes `asset`, `data` (→`as_polars()`), `metadata`, `strict_mode`, `set_field_metadata`, `write_csv/parquet/json`; `__getattr__`/`_wrap` use `Asset.derive(payload, derived_from=[self._asset])` consistently; `engine` is the single new lineage field used identically in Tasks 2/3/5/9/10/11.
