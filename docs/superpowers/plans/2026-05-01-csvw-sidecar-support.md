# CSVW Sidecar Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two-way CSVW interop for CSV files: read CSVW sidecars to enrich `df.metadata`, emit sidecars on write, include them in `datapackage.json` with cross-references, and hard-fail at package build when a sidecar references CSVs outside the package.

**Architecture:** Extend the existing `FormatHandler` protocol with three optional methods (`read_metadata`, `write_metadata`, `list_metadata_resources`) with no-op defaults via a base class. CSVW logic lives in a new private module `src/sunstone/_csvw.py` that wraps the third-party `csvw` library. `BuiltinFormatHandler` dispatches CSV/TSV calls to `_csvw`; non-CSV formats inherit no-ops. `DataFrame.read_csv`/`read_dataset` call `read_metadata` and merge the result into the existing `datasets.yaml > sidecar` precedence chain. `DataFrame.to_csv` gets a `csvw_metadata: bool | str | Path = True` kwarg. `packaging.push_group` enumerates per-handler sidecars and adds resources + cross-reference properties.

**Tech Stack:** Python 3.12+, `csvw>=3.7`, pandas, ruamel.yaml, `os.replace` for atomic local writes.

**Spec:** `docs/superpowers/specs/2026-05-01-csvw-sidecar-support-design.md`

**Coordination:**
- Future work tracked in [sunstone-py#56](https://github.com/sunstoneinstitute/sunstone-py/issues/56) (drive read dtypes from metadata).
- The `csvwMetadata` cross-reference RDF property is requested via [rdf-registry#6](https://github.com/sunstoneinstitute/rdf-registry/issues/6); use the URI `https://sunstone.institute/rdf/vocab#csvwMetadata` directly until that lands.

---

## Task 1: Add the `csvw` dependency and new exceptions

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sunstone/exceptions.py`
- Test: `tests/test_errors.py` (existing file)

- [ ] **Step 1: Add `csvw>=3.7` to project dependencies**

In `pyproject.toml`, find the `[project] dependencies = [ ... ]` list and add `"csvw>=3.7"` (alphabetically; the list is currently sorted).

```bash
uv add "csvw>=3.7"
```

- [ ] **Step 2: Verify install succeeded**

Run:
```bash
uv run python -c "from csvw import TableGroup; print(TableGroup)"
```
Expected: prints the class object, no errors.

- [ ] **Step 3: Write failing tests for the new exceptions**

Add to `tests/test_errors.py`:

```python
def test_csvw_sidecar_error_is_dataset_validation_error():
    from sunstone.exceptions import CSVWSidecarError, DatasetValidationError

    err = CSVWSidecarError("bad sidecar")
    assert isinstance(err, DatasetValidationError)
    assert str(err) == "bad sidecar"


def test_package_validation_error_is_dataset_validation_error():
    from sunstone.exceptions import DatasetValidationError, PackageValidationError

    err = PackageValidationError("bad package")
    assert isinstance(err, DatasetValidationError)
    assert str(err) == "bad package"
```

- [ ] **Step 4: Run the tests; verify they fail**

```bash
uv run pytest tests/test_errors.py -v -k "csvw_sidecar_error or package_validation_error"
```
Expected: ImportError / AttributeError on `CSVWSidecarError` / `PackageValidationError`.

- [ ] **Step 5: Add the exceptions**

Append to `src/sunstone/exceptions.py`:

```python
class CSVWSidecarError(DatasetValidationError):
    """A CSVW sidecar file exists but cannot be parsed or used."""

    pass


class PackageValidationError(DatasetValidationError):
    """A datapackage cannot be built due to a structural validation failure."""

    pass
```

- [ ] **Step 6: Run the tests; verify they pass**

```bash
uv run pytest tests/test_errors.py -v -k "csvw_sidecar_error or package_validation_error"
```
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/sunstone/exceptions.py tests/test_errors.py
git commit -m "feat: add csvw dependency and new exceptions for sidecar support"
```

---

## Task 2: Add `SidecarResource` dataclass and extend `FormatHandler` protocol

**Files:**
- Modify: `src/sunstone/plugins.py`
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Write failing tests for the protocol's no-op defaults**

Append to `tests/test_plugins.py`:

```python
def test_format_handler_default_read_metadata_returns_none():
    """The base format handler returns None from read_metadata by default."""
    from sunstone.handlers import BuiltinFormatHandler
    from sunstone.plugins import PluginRegistry

    handler = BuiltinFormatHandler()
    registry = PluginRegistry.get()
    url_handler = registry.find_url_handler("/tmp/example.json")
    assert handler.read_metadata("/tmp/example.json", url_handler) is None


def test_format_handler_default_write_metadata_returns_none():
    """The base format handler returns None from write_metadata by default."""
    from sunstone.handlers import BuiltinFormatHandler
    from sunstone.lineage import Metadata
    from sunstone.plugins import PluginRegistry

    handler = BuiltinFormatHandler()
    registry = PluginRegistry.get()
    url_handler = registry.find_url_handler("/tmp/example.json")
    result = handler.write_metadata("/tmp/example.json", Metadata(), url_handler)
    assert result is None


def test_format_handler_default_list_metadata_resources_returns_empty():
    """The base format handler returns [] from list_metadata_resources by default."""
    from sunstone.handlers import BuiltinFormatHandler

    handler = BuiltinFormatHandler()
    assert handler.list_metadata_resources(["/tmp/a.json"]) == []


def test_sidecar_resource_dataclass():
    """SidecarResource has the expected fields."""
    from pathlib import Path

    from sunstone.plugins import SidecarResource

    sr = SidecarResource(
        path=Path("a.csv-metadata.json"),
        covers=[Path("a.csv")],
        cross_ref_property="https://sunstone.institute/rdf/vocab#csvwMetadata",
    )
    assert sr.path == Path("a.csv-metadata.json")
    assert sr.covers == [Path("a.csv")]
    assert "csvwMetadata" in sr.cross_ref_property
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_plugins.py -v -k "default_read_metadata or default_write_metadata or default_list_metadata or sidecar_resource_dataclass"
```
Expected: AttributeError (`read_metadata` / `write_metadata` / `list_metadata_resources` / `SidecarResource` not defined).

- [ ] **Step 3: Add `SidecarResource` dataclass and extend `FormatHandler`**

In `src/sunstone/plugins.py`:

1. At the top of the file, add `from dataclasses import dataclass` and `from pathlib import Path` to existing imports if not already present (`Path` is, `dataclass` is not).
2. After the `URLHandler` Protocol (around line 50), before the `FormatHandler` Protocol, insert:

```python
@dataclass
class SidecarResource:
    """An external metadata resource (sidecar) to include in a datapackage.

    Returned by FormatHandler.list_metadata_resources() so the packaging
    layer knows which sidecar files to upload and how to cross-reference
    them from the data resources.
    """

    path: Path
    """Sidecar file path. Relative to the project root for local sidecars,
    otherwise the URL handler-resolvable path."""

    covers: list[Path]
    """Data files this sidecar describes."""

    cross_ref_property: str
    """RDF property URI to add on each covered resource entry, pointing
    back at this sidecar."""
```

3. Replace the `FormatHandler` Protocol (currently lines 53-75) with this version that adds three new methods with default implementations:

```python
@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats."""

    def supports_metadata(self) -> bool:
        """Return True if this handler can embed/extract metadata in the file format."""
        ...

    def can_read(self, path: str, format: str | None) -> bool:
        """Return True if this handler can read the given format. path is used for extension detection."""
        ...

    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame:
        """Read stream into a pandas DataFrame."""
        ...

    def can_write(self, path: str, format: str | None) -> bool:
        """Return True if this handler can write the given format. path is used for extension detection."""
        ...

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        """Write DataFrame to stream."""
        ...

    def read_metadata(
        self,
        data_path: str,
        url_handler: URLHandler,
    ) -> "Metadata | None":
        """Read external (sidecar) metadata for ``data_path``.

        Default implementation returns ``None`` — formats that embed
        metadata in the file (e.g. Parquet) do that work in ``read()``
        and need not override this.
        """
        return None

    def write_metadata(
        self,
        data_path: str,
        metadata: "Metadata",
        url_handler: URLHandler,
        *,
        target: str | None = None,
    ) -> str | None:
        """Write external metadata for ``data_path``.

        ``target=None`` writes to the format's default sibling path; a
        string targets a shared sidecar (e.g. multi-CSV csvm). Returns
        the sidecar path actually written, or ``None`` if no sidecar was
        produced.
        """
        return None

    def list_metadata_resources(
        self,
        data_paths: list[str],
    ) -> list[SidecarResource]:
        """Return external metadata resources to include in the
        datapackage.json for the given set of data files. Default: none."""
        return []
```

4. Add a forward-reference import for `Metadata` at the bottom of the existing imports block:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .lineage import Metadata
```

(Place this after the existing imports; keep `from .lineage import DatasetMetadata` as-is.)

- [ ] **Step 4: Add identical default methods to existing handlers if they conflict with the protocol**

Because `BuiltinFormatHandler` and `ParquetFormatHandler` are concrete classes (not protocol implementers), they will inherit no-op defaults *only if they extend a base class*. Since the protocol uses `Protocol` with method bodies, runtime checks via `isinstance(..., FormatHandler)` won't enforce the new methods on existing classes. Verify by running the new tests:

```bash
uv run pytest tests/test_plugins.py -v -k "default_read_metadata or default_write_metadata or default_list_metadata or sidecar_resource_dataclass"
```

If `read_metadata` / `write_metadata` / `list_metadata_resources` raise `AttributeError` on `BuiltinFormatHandler`, add explicit no-op methods on `BuiltinFormatHandler` (in `src/sunstone/handlers.py`):

```python
class BuiltinFormatHandler:
    # ... existing methods ...

    def read_metadata(self, data_path, url_handler):
        return None

    def write_metadata(self, data_path, metadata, url_handler, *, target=None):
        return None

    def list_metadata_resources(self, data_paths):
        return []
```

And the same three no-op methods on `ParquetFormatHandler` in the same file.

- [ ] **Step 5: Run tests; verify they pass**

```bash
uv run pytest tests/test_plugins.py -v -k "default_read_metadata or default_write_metadata or default_list_metadata or sidecar_resource_dataclass"
```
Expected: 4 passed.

Also run the full test suite once to confirm no regressions in unrelated tests caused by the protocol change:

```bash
uv run pytest -q
```
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/plugins.py src/sunstone/handlers.py tests/test_plugins.py
git commit -m "feat: extend FormatHandler protocol with sidecar metadata methods"
```

---

## Task 3: Create `_csvw.csvw_to_metadata` mapping

**Files:**
- Create: `src/sunstone/_csvw.py`
- Test: `tests/test_csvw.py` (new file)

- [ ] **Step 1: Write failing tests for `csvw_to_metadata`**

Create `tests/test_csvw.py` with:

```python
"""Unit tests for src/sunstone/_csvw.py — CSVW sidecar logic."""

from __future__ import annotations

import pytest


class TestCsvwToMetadata:
    def test_minimal_table_yields_minimal_metadata(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "tableSchema": {
                "columns": [
                    {"name": "x"},
                    {"name": "y"},
                ]
            },
        }
        meta = csvw_to_metadata(table)
        assert meta.description is None
        assert set(meta.field_metadata.keys()) == {"x", "y"}
        assert meta.field_metadata["x"].name == "x"

    def test_table_description_maps_to_metadata_description(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "dc:description": "monthly summary",
            "tableSchema": {"columns": [{"name": "x"}]},
        }
        meta = csvw_to_metadata(table)
        assert meta.description == "monthly summary"

    def test_column_description_and_datatype(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "tableSchema": {
                "columns": [
                    {
                        "name": "temp",
                        "datatype": "decimal",
                        "dc:description": "Mean temperature",
                    },
                ]
            },
        }
        meta = csvw_to_metadata(table)
        fs = meta.field_metadata["temp"]
        assert fs.description == "Mean temperature"
        assert fs.type == "decimal"

    def test_unknown_csvw_props_become_custom_properties(self):
        from sunstone._csvw import csvw_to_metadata

        table = {
            "url": "foo.csv",
            "ex:custom": "something",
            "tableSchema": {"columns": [{"name": "x"}]},
        }
        meta = csvw_to_metadata(table)
        assert meta.custom_properties is not None
        assert meta.custom_properties.get("ex:custom") == "something"

    def test_empty_columns_list_is_safe(self):
        from sunstone._csvw import csvw_to_metadata

        meta = csvw_to_metadata({"url": "foo.csv", "tableSchema": {"columns": []}})
        assert meta.field_metadata == {}
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_csvw.py::TestCsvwToMetadata -v
```
Expected: ModuleNotFoundError on `sunstone._csvw`.

- [ ] **Step 3: Implement `csvw_to_metadata`**

Create `src/sunstone/_csvw.py`:

```python
"""CSVW sidecar support — wraps the third-party `csvw` library and
provides the read/write helpers used by BuiltinFormatHandler.

This is a private module; no public API guarantees.
"""

from __future__ import annotations

from typing import Any

from .lineage import FieldSchema, Metadata


# Standard csvw / W3C properties handled directly. Anything else on the
# table dict that contains ":" (RDF-style) is treated as a custom property.
_TABLE_CORE_KEYS = frozenset(
    {
        "url",
        "tableSchema",
        "dialect",
        "@id",
        "@type",
        "@context",
        "tables",  # if someone passed a TableGroup-shaped dict; handled at caller
    }
)

_COLUMN_CORE_KEYS = frozenset(
    {
        "name",
        "datatype",
        "titles",
        "required",
        "@id",
        "@type",
        "default",
        "null",
        "lang",
        "ordered",
        "propertyUrl",
        "separator",
        "valueUrl",
        "virtual",
        "aboutUrl",
        "textDirection",
        "suppressOutput",
    }
)


def csvw_to_metadata(table: dict) -> Metadata:
    """Map a CSVW table description (a dict, as produced by the csvw
    library's ``Table.asdict()`` or by direct JSON load) into a sunstone
    ``Metadata`` object.

    Mapping:

    - ``dc:description`` (or ``dct:description``) → ``Metadata.description``
    - ``tableSchema.columns[*].name`` → ``FieldSchema.name``
    - ``tableSchema.columns[*].dc:description`` (or ``dct:``) → ``FieldSchema.description``
    - ``tableSchema.columns[*].datatype`` → ``FieldSchema.type`` (string form;
      not used to drive read dtypes — see issue #56)
    - any non-core RDF-shaped key (``ns:term``) on the table dict is added
      to ``Metadata.custom_properties``

    Returns an empty ``Metadata()`` when the table has no recognizable
    fields.
    """
    description = table.get("dc:description") or table.get("dct:description")

    schema = table.get("tableSchema") or {}
    columns = schema.get("columns") or []

    field_metadata: dict[str, FieldSchema] = {}
    for col in columns:
        name = col.get("name")
        if not name:
            continue
        col_desc = col.get("dc:description") or col.get("dct:description")
        datatype_raw = col.get("datatype")
        if isinstance(datatype_raw, dict):
            datatype = datatype_raw.get("base")
        else:
            datatype = datatype_raw
        field_metadata[str(name)] = FieldSchema(
            name=str(name),
            type=str(datatype) if datatype is not None else None,
            description=str(col_desc) if col_desc is not None else None,
        )

    custom: dict[str, Any] = {
        k: v for k, v in table.items() if k not in _TABLE_CORE_KEYS and ":" in k
    }

    return Metadata(
        description=description,
        field_metadata=field_metadata,
        custom_properties=custom or None,
    )
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_csvw.py::TestCsvwToMetadata -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/_csvw.py tests/test_csvw.py
git commit -m "feat: add csvw_to_metadata mapping"
```

---

## Task 4: Add `metadata_to_csvw_table` (inverse mapping)

**Files:**
- Modify: `src/sunstone/_csvw.py`
- Test: `tests/test_csvw.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_csvw.py`:

```python
class TestMetadataToCsvwTable:
    def test_minimal_metadata_yields_minimal_table(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        table = metadata_to_csvw_table(Path("foo.csv"), Metadata())
        assert table["url"] == "foo.csv"
        assert table["tableSchema"]["columns"] == []
        assert "dc:description" not in table

    def test_field_metadata_maps_to_columns(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import FieldSchema, Metadata

        meta = Metadata(
            description="weekly aggregates",
            field_metadata={
                "x": FieldSchema(name="x", type="integer", description="count"),
                "y": FieldSchema(name="y", type="decimal"),
            },
        )
        table = metadata_to_csvw_table(Path("data/foo.csv"), meta)
        assert table["url"] == "data/foo.csv"
        assert table["dc:description"] == "weekly aggregates"
        cols = {c["name"]: c for c in table["tableSchema"]["columns"]}
        assert cols["x"]["datatype"] == "integer"
        assert cols["x"]["dc:description"] == "count"
        assert cols["y"]["datatype"] == "decimal"
        assert "dc:description" not in cols["y"]

    def test_custom_properties_pass_through(self):
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        meta = Metadata(custom_properties={"ex:thing": "value"})
        table = metadata_to_csvw_table(Path("foo.csv"), meta)
        assert table["ex:thing"] == "value"

    def test_round_trip_recovers_field_descriptions_and_types(self):
        from pathlib import Path

        from sunstone._csvw import csvw_to_metadata, metadata_to_csvw_table
        from sunstone.lineage import FieldSchema, Metadata

        original = Metadata(
            description="round trip",
            field_metadata={
                "a": FieldSchema(name="a", type="integer", description="alpha"),
                "b": FieldSchema(name="b", type="string"),
            },
        )
        recovered = csvw_to_metadata(metadata_to_csvw_table(Path("rt.csv"), original))
        assert recovered.description == "round trip"
        assert recovered.field_metadata["a"].type == "integer"
        assert recovered.field_metadata["a"].description == "alpha"
        assert recovered.field_metadata["b"].type == "string"

    def test_uses_posix_url(self):
        """URL in csvw is forward-slash even on Windows."""
        from pathlib import Path

        from sunstone._csvw import metadata_to_csvw_table
        from sunstone.lineage import Metadata

        table = metadata_to_csvw_table(Path("a") / "b" / "c.csv", Metadata())
        assert table["url"] == "a/b/c.csv"
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_csvw.py::TestMetadataToCsvwTable -v
```
Expected: AttributeError (`metadata_to_csvw_table` undefined).

- [ ] **Step 3: Implement `metadata_to_csvw_table`**

Append to `src/sunstone/_csvw.py`:

```python
from pathlib import Path, PurePosixPath


def metadata_to_csvw_table(data_path: Path, metadata: Metadata) -> dict:
    """Inverse of :func:`csvw_to_metadata`. Build a single CSVW table
    description (dict) describing the CSV at ``data_path`` according to
    the given ``Metadata``.

    The returned dict is suitable for use as one entry inside a
    ``TableGroup``'s ``tables`` list, or as the body of a per-CSV
    sidecar document.

    Notes:

    - The ``url`` key is always set using POSIX-style separators (CSVW
      requires forward slashes; Windows backslashes are not portable).
    - Only fields present in ``metadata.field_metadata`` are emitted.
      Columns inferred at write time but not annotated are not added —
      caller is expected to merge inferred and explicit field metadata
      before calling this.
    """
    table: dict = {
        "url": _as_posix(data_path),
    }
    if metadata.description:
        table["dc:description"] = metadata.description

    columns: list[dict] = []
    for name, fs in metadata.field_metadata.items():
        col: dict = {"name": name}
        if fs.type is not None:
            col["datatype"] = fs.type
        if fs.description is not None:
            col["dc:description"] = fs.description
        columns.append(col)
    table["tableSchema"] = {"columns": columns}

    if metadata.custom_properties:
        for k, v in metadata.custom_properties.items():
            if k in _TABLE_CORE_KEYS:
                continue
            table[k] = v

    return table


def _as_posix(path: Path | str) -> str:
    """Return a POSIX-style path string suitable for use in CSVW ``url``
    fields (forward slashes regardless of OS)."""
    if isinstance(path, Path):
        return path.as_posix()
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_csvw.py::TestMetadataToCsvwTable -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/_csvw.py tests/test_csvw.py
git commit -m "feat: add metadata_to_csvw_table inverse mapping"
```

---

## Task 5: Implement `find_sidecar` (tier 1 + tier 2 lookup)

**Files:**
- Modify: `src/sunstone/_csvw.py`
- Test: `tests/test_csvw.py`

- [ ] **Step 1: Write failing tests for tier 1 (per-CSV, strict)**

Append to `tests/test_csvw.py`:

```python
import json
import logging


def _make_handler():
    """Return a LocalFileHandler instance for tests."""
    from sunstone.handlers import LocalFileHandler
    return LocalFileHandler()


def _write_sidecar_json(path, table_url):
    path.write_text(json.dumps({
        "@context": "http://www.w3.org/ns/csvw",
        "url": table_url,
        "tableSchema": {"columns": [{"name": "x"}]},
    }))


def _write_table_group_json(path, table_urls):
    path.write_text(json.dumps({
        "@context": "http://www.w3.org/ns/csvw",
        "tables": [
            {"url": u, "tableSchema": {"columns": [{"name": "x"}]}}
            for u in table_urls
        ],
    }))


class TestFindSidecarTier1:
    def test_no_sidecar_returns_none(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        assert find_sidecar(csv, _make_handler()) is None

    def test_canonical_csv_metadata_json_wins(self, tmp_path):
        """data.csv -> data.csv-metadata.json (W3C convention)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        path, table_dict = result
        assert path == sidecar
        assert table_dict["url"] == "data.csv"

    def test_dash_metadata_json_secondary(self, tmp_path):
        """data.csv -> data-metadata.json (alternate W3C form)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data-metadata.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_csvm_json_tier1_tertiary(self, tmp_path):
        """data.csv -> data.csvm.json (sunstone-specific)."""
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csvm.json"
        _write_sidecar_json(sidecar, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_first_tier1_match_wins(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        # Create both #1 and #2; #1 should win
        first = tmp_path / "data.csv-metadata.json"
        second = tmp_path / "data-metadata.json"
        _write_sidecar_json(first, "data.csv")
        _write_sidecar_json(second, "data.csv")

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == first

    def test_tier1_strict_malformed_json_raises(self, tmp_path):
        from sunstone._csvw import find_sidecar
        from sunstone.exceptions import CSVWSidecarError

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text("{ this is not json")

        with pytest.raises(CSVWSidecarError):
            find_sidecar(csv, _make_handler())

    def test_tier1_strict_non_csvw_raises(self, tmp_path):
        from sunstone._csvw import find_sidecar
        from sunstone.exceptions import CSVWSidecarError

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text(json.dumps({"unrelated": "content"}))

        with pytest.raises(CSVWSidecarError):
            find_sidecar(csv, _make_handler())


class TestFindSidecarTier2:
    def test_csvm_json_multi_table_match(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "csvm.json"
        _write_table_group_json(sidecar, ["data.csv", "other.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        path, table = result
        assert path == sidecar
        assert table["url"] == "data.csv"

    def test_metadata_json_multi_table_match(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "metadata.json"
        _write_table_group_json(sidecar, ["data.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == sidecar

    def test_csvm_json_no_table_for_this_csv_returns_none(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "csvm.json"
        _write_table_group_json(sidecar, ["other.csv"])

        # Authoritative for this directory; do not fall through.
        assert find_sidecar(csv, _make_handler()) is None

    def test_lenient_metadata_json_invalid_is_skipped(self, tmp_path, caplog):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        bad = tmp_path / "metadata.json"
        bad.write_text("{ this is not json")
        # csvm.json with a real match should still be found
        good = tmp_path / "csvm.json"
        _write_table_group_json(good, ["data.csv"])

        with caplog.at_level(logging.INFO, logger="sunstone._csvw"):
            result = find_sidecar(csv, _make_handler())
        assert result is not None
        # The lenient skip is not asserted to log specifically (depends
        # on lookup order: csvm.json comes BEFORE metadata.json).
        assert result[0] == good

    def test_lenient_csvm_json_invalid_falls_through_to_metadata_json(
        self, tmp_path, caplog
    ):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        bad = tmp_path / "csvm.json"
        bad.write_text("{ broken")
        good = tmp_path / "metadata.json"
        _write_table_group_json(good, ["data.csv"])

        with caplog.at_level(logging.INFO, logger="sunstone._csvw"):
            result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == good
        # The bad csvm.json should have produced an INFO log
        assert any("csvm.json" in r.message for r in caplog.records)

    def test_tier1_short_circuits_tier2(self, tmp_path):
        from sunstone._csvw import find_sidecar

        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        # Tier-1 sidecar exists; tier-2 csvm also exists
        tier1 = tmp_path / "data.csv-metadata.json"
        _write_sidecar_json(tier1, "data.csv")
        tier2 = tmp_path / "csvm.json"
        _write_table_group_json(tier2, ["data.csv"])

        result = find_sidecar(csv, _make_handler())
        assert result is not None
        assert result[0] == tier1
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_csvw.py::TestFindSidecarTier1 tests/test_csvw.py::TestFindSidecarTier2 -v
```
Expected: AttributeError on `find_sidecar`.

- [ ] **Step 3: Implement `find_sidecar`**

Append to `src/sunstone/_csvw.py` (add `import json` and `import logging` to imports at top of file, and `from .exceptions import CSVWSidecarError`):

```python
import json
import logging
from typing import Iterable

from .exceptions import CSVWSidecarError
from .plugins import URLHandler  # type: ignore[attr-defined]


logger = logging.getLogger(__name__)


# Tier-1: per-CSV strict-name candidates. Lookup is by suffix
# substitution on the data file name. The W3C CSVW convention is to
# append ``-metadata.json`` to the FULL CSV filename (so ``out.csv``
# becomes ``out.csv-metadata.json``).
_TIER1_NAME_TEMPLATES: tuple[str, ...] = (
    "{name}-metadata.json",   # canonical W3C: foo.csv -> foo.csv-metadata.json
    "{stem}-metadata.json",   # alternate:     foo.csv -> foo-metadata.json
    "{stem}.csvm.json",       # sunstone:      foo.csv -> foo.csvm.json
)

# Tier-2: multi-CSV bare-name candidates in the data file's directory.
_TIER2_NAMES: tuple[str, ...] = ("csvm.json", "metadata.json")


def _csvw_signature_ok(doc: dict) -> bool:
    """Heuristic CSVW-ness check.

    The csvw library's parser is permissive (warns on unknown fields
    rather than raising). We use a structural check instead: the
    document must declare ``@context`` referring to the CSVW namespace
    AND have either ``tableSchema`` (single table) or a non-empty
    ``tables`` list.
    """
    if not isinstance(doc, dict):
        return False
    context = doc.get("@context")
    if context is None:
        return False
    # @context can be a string, a list, or an object — flatten to a set
    # of strings for membership checking.
    if isinstance(context, str):
        ctx_strings = {context}
    elif isinstance(context, list):
        ctx_strings = {c for c in context if isinstance(c, str)}
    elif isinstance(context, dict):
        ctx_strings = {context.get("@vocab", "")}
    else:
        ctx_strings = set()
    if not any("csvw" in c for c in ctx_strings):
        return False
    return "tableSchema" in doc or bool(doc.get("tables"))


def _table_for_data_path(doc: dict, data_path: Path) -> dict | None:
    """From a parsed CSVW document (single-table or table-group), return
    the table dict whose ``url`` matches ``data_path``, or None.

    Matching is by basename and POSIX-relative path forms — handles both
    ``data.csv`` and ``subdir/data.csv`` references in a csvm."""
    target_name = data_path.name
    target_posix = _as_posix(data_path)

    # Single-table sidecar
    if "tableSchema" in doc:
        url = doc.get("url")
        if url == target_name or url == target_posix:
            return doc
        return None

    # Multi-table sidecar
    for table in doc.get("tables") or []:
        url = table.get("url")
        if url == target_name or url == target_posix:
            return table

    return None


def _open_text_via_handler(
    url_handler: URLHandler, path: Path
) -> str | None:
    """Open a file via the URLHandler in text mode and read it.

    Returns None if the file does not exist (treats FileNotFoundError as
    a miss). Re-raises other I/O errors.
    """
    try:
        with url_handler.open(str(path), "r") as f:
            return f.read()
    except FileNotFoundError:
        return None


def find_sidecar(
    data_path: Path,
    url_handler: URLHandler,
) -> tuple[Path, dict] | None:
    """Locate and parse a CSVW sidecar describing ``data_path``.

    Lookup tiers (first match wins per tier; tier 1 short-circuits tier 2):

    Tier 1 (per-CSV, strict naming — parse failures raise):
      - ``<data_path>.csv-metadata.json``
      - ``<stem>-metadata.json``
      - ``<data_path>.csvm.json``

    Tier 2 (multi-CSV, lenient naming — parse failures logged & skipped):
      - ``csvm.json``     (in the data file's directory)
      - ``metadata.json``

    Returns ``(sidecar_path, table_dict)`` where ``table_dict`` is the
    single ``csvw:Table`` description matching ``data_path``. Returns
    ``None`` if no sidecar covers this CSV.
    """
    parent = data_path.parent
    name = data_path.name
    stem = data_path.stem

    # Tier 1: strict naming
    for template in _TIER1_NAME_TEMPLATES:
        candidate = parent / template.format(name=name, stem=stem)
        text = _open_text_via_handler(url_handler, candidate)
        if text is None:
            continue
        # Strict: any failure to parse-as-CSVW raises
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            raise CSVWSidecarError(
                f"CSVW sidecar '{candidate}' is not valid JSON: {e}"
            ) from e
        if not _csvw_signature_ok(doc):
            raise CSVWSidecarError(
                f"CSVW sidecar '{candidate}' is not a valid CSVW document "
                f"(missing @context for csvw or tableSchema/tables)."
            )
        table = _table_for_data_path(doc, data_path)
        if table is None:
            raise CSVWSidecarError(
                f"CSVW sidecar '{candidate}' does not contain a table for "
                f"'{data_path.name}'."
            )
        return (candidate, table)

    # Tier 2: lenient naming
    for tier2_name in _TIER2_NAMES:
        candidate = parent / tier2_name
        text = _open_text_via_handler(url_handler, candidate)
        if text is None:
            continue
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            logger.info(
                "Sidecar candidate %s is not JSON; skipping (lenient name).",
                candidate,
            )
            continue
        if not _csvw_signature_ok(doc):
            logger.info(
                "Sidecar candidate %s is not a CSVW document; skipping (lenient name).",
                candidate,
            )
            continue
        # Found a parseable CSVW document; this file is authoritative for
        # the directory's multi-CSV metadata. Look for our table.
        table = _table_for_data_path(doc, data_path)
        if table is not None:
            return (candidate, table)
        # File was authoritative but didn't cover us — return None.
        return None

    return None
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_csvw.py::TestFindSidecarTier1 tests/test_csvw.py::TestFindSidecarTier2 -v
```
Expected: all tests pass (7 tier-1 + 6 tier-2).

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/_csvw.py tests/test_csvw.py
git commit -m "feat: add CSVW sidecar discovery (tier-1 strict + tier-2 lenient)"
```

---

## Task 6: Implement `upsert_table_in_sidecar` with atomic write

**Files:**
- Modify: `src/sunstone/_csvw.py`
- Test: `tests/test_csvw.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_csvw.py`:

```python
class TestUpsertTableInSidecar:
    def test_creates_new_sidecar_when_missing(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csv = tmp_path / "a.csv"
        sidecar = tmp_path / "a.csv-metadata.json"
        table = metadata_to_csvw_table(csv, Metadata(description="hello"))

        upsert_table_in_sidecar(sidecar, csv, table, _make_handler())

        assert sidecar.exists()
        doc = json.loads(sidecar.read_text())
        assert doc["@context"] == "http://www.w3.org/ns/csvw"
        # Single-csv sibling sidecar style: stored as a TableGroup with
        # one table to keep one consistent on-disk shape.
        assert "tables" in doc
        assert len(doc["tables"]) == 1
        assert doc["tables"][0]["url"] == "a.csv"
        assert doc["tables"][0]["dc:description"] == "hello"

    def test_appends_table_to_existing_csvm(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "shared.csvm.json"
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"

        upsert_table_in_sidecar(
            csvm, a, metadata_to_csvw_table(a, Metadata(description="A")),
            _make_handler(),
        )
        upsert_table_in_sidecar(
            csvm, b, metadata_to_csvw_table(b, Metadata(description="B")),
            _make_handler(),
        )

        doc = json.loads(csvm.read_text())
        urls = sorted(t["url"] for t in doc["tables"])
        assert urls == ["a.csv", "b.csv"]

    def test_replaces_existing_entry_for_same_csv(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "csvm.json"
        a = tmp_path / "a.csv"

        upsert_table_in_sidecar(
            csvm, a, metadata_to_csvw_table(a, Metadata(description="first")),
            _make_handler(),
        )
        upsert_table_in_sidecar(
            csvm, a, metadata_to_csvw_table(a, Metadata(description="second")),
            _make_handler(),
        )

        doc = json.loads(csvm.read_text())
        assert len(doc["tables"]) == 1
        assert doc["tables"][0]["dc:description"] == "second"

    def test_refuses_to_clobber_non_csvw_file(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.exceptions import CSVWSidecarError
        from sunstone.lineage import Metadata

        csvm = tmp_path / "important.json"
        csvm.write_text(json.dumps({"unrelated": "config"}))
        a = tmp_path / "a.csv"

        with pytest.raises(CSVWSidecarError):
            upsert_table_in_sidecar(
                csvm, a, metadata_to_csvw_table(a, Metadata()), _make_handler()
            )
        # Original file untouched
        assert json.loads(csvm.read_text()) == {"unrelated": "config"}

    def test_no_temp_files_left_on_success(self, tmp_path):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        sidecar = tmp_path / "a.csv-metadata.json"
        a = tmp_path / "a.csv"
        upsert_table_in_sidecar(
            sidecar, a, metadata_to_csvw_table(a, Metadata()), _make_handler()
        )
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_preserves_original_on_write_failure(self, tmp_path, monkeypatch):
        from sunstone._csvw import metadata_to_csvw_table, upsert_table_in_sidecar
        from sunstone.lineage import Metadata

        csvm = tmp_path / "csvm.json"
        a = tmp_path / "a.csv"

        # First write succeeds
        upsert_table_in_sidecar(
            csvm, a, metadata_to_csvw_table(a, Metadata(description="original")),
            _make_handler(),
        )
        original = csvm.read_text()

        # Force the JSON dump to fail
        import sunstone._csvw as csvw_mod
        real_dumps = csvw_mod.json.dumps

        def boom(*args, **kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(csvw_mod.json, "dumps", boom)

        with pytest.raises(RuntimeError):
            upsert_table_in_sidecar(
                csvm, a, metadata_to_csvw_table(a, Metadata(description="new")),
                _make_handler(),
            )

        # Original file untouched
        assert csvm.read_text() == original
        # No leftover temp files
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_csvw.py::TestUpsertTableInSidecar -v
```
Expected: AttributeError on `upsert_table_in_sidecar`.

- [ ] **Step 3: Implement `upsert_table_in_sidecar`**

Append to `src/sunstone/_csvw.py` (add `import os` and `from urllib.parse import urlparse` to imports if not present):

```python
import os
from urllib.parse import urlparse


def upsert_table_in_sidecar(
    sidecar_path: Path,
    data_path: Path,
    table_dict: dict,
    url_handler: URLHandler,
) -> None:
    """Read-modify-write the sidecar at ``sidecar_path`` so that it
    contains exactly one table entry for ``data_path`` (replacing any
    existing entry; preserving entries for other CSVs).

    Atomicity: for local-filesystem paths the write goes to a temporary
    file in the same directory and is then ``os.replace``'d into place
    (atomic on POSIX, atomic-enough on NTFS). For non-local paths
    (resolved via the URLHandler), atomic rename is not available — the
    file is overwritten directly. CSVW sidecars are predominantly a
    local-filesystem convention, so this is acceptable.

    Raises ``CSVWSidecarError`` if ``sidecar_path`` exists but is not a
    valid CSVW document (refuses to clobber unrelated files).
    """
    # Read existing contents (if any)
    existing_text = _open_text_via_handler(url_handler, sidecar_path)
    if existing_text is None:
        doc = {
            "@context": "http://www.w3.org/ns/csvw",
            "tables": [],
        }
    else:
        try:
            doc = json.loads(existing_text)
        except json.JSONDecodeError as e:
            raise CSVWSidecarError(
                f"Refusing to overwrite '{sidecar_path}': existing file is not "
                f"valid JSON ({e}). If you intended to overwrite, delete the "
                f"file first."
            ) from e
        if not _csvw_signature_ok(doc):
            raise CSVWSidecarError(
                f"Refusing to overwrite '{sidecar_path}': existing file is not "
                f"a valid CSVW document. If you intended to overwrite, delete "
                f"the file first."
            )

        # Normalize single-table form -> table-group form so we always
        # write the same shape on disk.
        if "tableSchema" in doc and "tables" not in doc:
            single = dict(doc)
            single.pop("@context", None)
            doc = {
                "@context": doc.get("@context", "http://www.w3.org/ns/csvw"),
                "tables": [single],
            }

    # Replace or append the entry for data_path
    target_url = _as_posix(data_path)
    target_name = data_path.name
    tables = doc.setdefault("tables", [])
    replaced = False
    for i, t in enumerate(tables):
        u = t.get("url")
        if u == target_url or u == target_name:
            tables[i] = table_dict
            replaced = True
            break
    if not replaced:
        tables.append(table_dict)

    # Serialize once before touching disk so a serialization failure
    # doesn't leave a half-written file.
    serialized = json.dumps(doc, indent=2, ensure_ascii=False)

    if _is_local_path(url_handler, sidecar_path):
        _atomic_write_text(sidecar_path, serialized)
    else:
        # Non-local: best-effort overwrite via the URL handler
        with url_handler.open(str(sidecar_path), "w") as f:
            f.write(serialized)


def _is_local_path(url_handler: URLHandler, path: Path) -> bool:
    """Heuristic: is ``path`` resolvable on the local filesystem?

    Used to decide whether to do an atomic temp+rename. We cannot rely
    on the handler instance type alone (external plugins may also handle
    local paths), so we fall back to ``urlparse(path).scheme`` and treat
    a missing scheme as local. Paths with a scheme like ``gs://`` /
    ``s3://`` are non-local.
    """
    s = str(path)
    parsed = urlparse(s)
    if parsed.scheme in ("", "file"):
        return True
    # Single-letter scheme on Windows = drive letter
    if len(parsed.scheme) == 1 and parsed.scheme.isalpha():
        return True
    return False


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via temp + os.replace.

    The temp file lives in the same directory so the rename is
    cross-device-safe. On any failure during the write, the temp file
    is removed and the original (if any) is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_csvw.py::TestUpsertTableInSidecar -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/_csvw.py tests/test_csvw.py
git commit -m "feat: add atomic upsert_table_in_sidecar for CSVW writes"
```

---

## Task 7: Implement `enumerate_sidecars_for` with Q8 validation

**Files:**
- Modify: `src/sunstone/_csvw.py`
- Test: `tests/test_csvw.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_csvw.py`:

```python
class TestEnumerateSidecarsFor:
    def test_no_sidecars_yields_empty_list(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        result = enumerate_sidecars_for([a])
        assert result == []

    def test_per_csv_sidecar_becomes_resource(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        sidecar = tmp_path / "a.csv-metadata.json"
        _write_sidecar_json(sidecar, "a.csv")

        result = enumerate_sidecars_for([a])
        assert len(result) == 1
        sr = result[0]
        assert sr.path == sidecar
        assert sr.covers == [a]
        assert "csvwMetadata" in sr.cross_ref_property

    def test_shared_csvm_covering_all_csvs_passes(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        for c in (a, b):
            c.write_text("x\n1\n")
        csvm = tmp_path / "shared.csvm.json"
        _write_table_group_json(csvm, ["a.csv", "b.csv"])

        # Note: shared.csvm.json is NOT one of the auto-discoverable
        # tier-1/tier-2 names. enumerate_sidecars_for must accept an
        # additional list of explicit sidecar paths from the registry of
        # writes. For now the auto-discovery test below covers the
        # tier-2 csvm.json path; explicit-path coverage is added in a
        # later task once the BuiltinFormatHandler can pass tracked
        # writes through.
        # Skip until then by writing tier-2 csvm.json:
        csvm2 = tmp_path / "csvm.json"
        _write_table_group_json(csvm2, ["a.csv", "b.csv"])

        result = enumerate_sidecars_for([a, b])
        # Should find csvm.json covering both
        assert any(sr.path == csvm2 for sr in result)
        sr = next(r for r in result if r.path == csvm2)
        assert set(sr.covers) == {a, b}

    def test_csvm_referencing_extra_csv_raises(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for
        from sunstone.exceptions import PackageValidationError

        a = tmp_path / "a.csv"
        a.write_text("x\n1\n")
        # csvm references a.csv AND a phantom outsider.csv
        csvm = tmp_path / "csvm.json"
        _write_table_group_json(csvm, ["a.csv", "outsider.csv"])

        with pytest.raises(PackageValidationError) as exc_info:
            enumerate_sidecars_for([a])
        assert "outsider.csv" in str(exc_info.value)
        assert str(csvm.name) in str(exc_info.value) or "csvm.json" in str(exc_info.value)

    def test_per_csv_sidecar_only_covers_one_csv(self, tmp_path):
        from sunstone._csvw import enumerate_sidecars_for

        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        for c in (a, b):
            c.write_text("x\n1\n")
        sidecar_a = tmp_path / "a.csv-metadata.json"
        _write_sidecar_json(sidecar_a, "a.csv")

        result = enumerate_sidecars_for([a, b])
        assert len(result) == 1
        assert result[0].covers == [a]
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_csvw.py::TestEnumerateSidecarsFor -v
```
Expected: AttributeError on `enumerate_sidecars_for`.

- [ ] **Step 3: Implement `enumerate_sidecars_for`**

Append to `src/sunstone/_csvw.py`:

```python
from .plugins import SidecarResource


# RDF property URI used to point a CSV resource at its CSVW sidecar in
# datapackage.json. Tracked in rdf-registry#6 for promotion to a
# registry-managed term.
CSVW_METADATA_PROPERTY = "https://sunstone.institute/rdf/vocab#csvwMetadata"


def _candidate_sidecar_paths(data_path: Path) -> list[Path]:
    """All on-disk candidate sidecar paths for ``data_path``, in
    discovery order: tier-1 (per-CSV) then tier-2 (multi-CSV)."""
    parent = data_path.parent
    name = data_path.name
    stem = data_path.stem
    candidates = [
        parent / template.format(name=name, stem=stem)
        for template in _TIER1_NAME_TEMPLATES
    ]
    candidates.extend(parent / n for n in _TIER2_NAMES)
    return candidates


def _read_sidecar_doc_lenient(path: Path) -> dict | None:
    """Read and parse a sidecar; return the doc dict if it's valid CSVW,
    else None. Used for enumeration where we ignore non-CSVW files."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not _csvw_signature_ok(doc):
        return None
    return doc


def _sidecar_referenced_csv_paths(sidecar_path: Path, doc: dict) -> set[Path]:
    """Return the set of CSV paths a sidecar references, resolved
    relative to the sidecar's directory."""
    parent = sidecar_path.parent
    refs: set[Path] = set()

    if "tableSchema" in doc:
        url = doc.get("url")
        if url:
            refs.add((parent / url).resolve())
    for table in doc.get("tables") or []:
        url = table.get("url")
        if url:
            refs.add((parent / url).resolve())
    return refs


def enumerate_sidecars_for(
    data_paths: list[Path],
    *,
    extra_sidecar_paths: Iterable[Path] = (),
) -> list[SidecarResource]:
    """Enumerate all CSVW sidecars covering any CSV in ``data_paths``.

    Discovery: for each data file, scans tier-1 and tier-2 candidate
    paths in its directory. Additionally, ``extra_sidecar_paths`` lets
    callers (e.g. the BuiltinFormatHandler) inject sidecars they know
    were written this run (for example, a user-specified shared csvm at
    a non-conventional name).

    Validation (Q8 — hard fail): every discovered sidecar must reference
    only CSVs in ``data_paths``. Any extra reference raises
    ``PackageValidationError``.

    TODO: optional auto-filtered csvm copies per package as an
    alternative to hard-fail. Disabled for now per explicit user
    choice. File a follow-up issue if/when this is needed.

    Returns a list of ``SidecarResource`` (one per unique sidecar file),
    each with the set of covered CSVs from ``data_paths`` and the
    cross-reference RDF property to attach to those CSVs in the
    datapackage.json.
    """
    from .exceptions import PackageValidationError

    data_path_set = {p.resolve() for p in data_paths}
    sidecar_to_covers: dict[Path, set[Path]] = {}

    def _consider(sidecar_path: Path, doc: dict) -> None:
        # Record which package CSVs this sidecar covers
        refs = _sidecar_referenced_csv_paths(sidecar_path, doc)
        covered = refs & data_path_set
        if not covered:
            return  # sidecar exists but doesn't cover any package CSV
        # Validate: refs must be a subset of the package
        extras = refs - data_path_set
        if extras:
            extra_names = sorted(p.name for p in extras)
            raise PackageValidationError(
                f"Sidecar '{sidecar_path}' references CSVs not in this "
                f"package: {', '.join(extra_names)}. Either remove the entry "
                f"from the sidecar, include those CSVs in the package, or "
                f"use a different sidecar for this package."
            )
        sidecar_to_covers.setdefault(sidecar_path.resolve(), set()).update(covered)

    seen_sidecars: set[Path] = set()

    for data_path in data_paths:
        for candidate in _candidate_sidecar_paths(data_path):
            r = candidate.resolve()
            if r in seen_sidecars:
                continue
            doc = _read_sidecar_doc_lenient(candidate)
            if doc is None:
                continue
            seen_sidecars.add(r)
            _consider(candidate, doc)

    for extra in extra_sidecar_paths:
        r = extra.resolve()
        if r in seen_sidecars:
            continue
        doc = _read_sidecar_doc_lenient(extra)
        if doc is None:
            # Caller said this exists but it isn't valid CSVW now —
            # surface as a structural failure so the package build
            # doesn't silently drop it.
            raise PackageValidationError(
                f"Expected CSVW sidecar '{extra}' is missing or not valid "
                f"CSVW at package-build time."
            )
        seen_sidecars.add(r)
        _consider(extra, doc)

    return [
        SidecarResource(
            path=path,
            covers=sorted(covers, key=lambda p: p.as_posix()),
            cross_ref_property=CSVW_METADATA_PROPERTY,
        )
        for path, covers in sorted(
            sidecar_to_covers.items(), key=lambda kv: kv[0].as_posix()
        )
    ]
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_csvw.py::TestEnumerateSidecarsFor -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/_csvw.py tests/test_csvw.py
git commit -m "feat: enumerate_sidecars_for with package-coverage validation"
```

---

## Task 8: Wire `BuiltinFormatHandler` to `_csvw`

**Files:**
- Modify: `src/sunstone/handlers.py`
- Test: `tests/test_handlers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_handlers.py`:

```python
def test_builtin_handler_read_metadata_finds_csv_sidecar(tmp_path):
    """BuiltinFormatHandler.read_metadata returns Metadata when a CSV sidecar exists."""
    import json

    from sunstone.handlers import BuiltinFormatHandler, LocalFileHandler

    csv = tmp_path / "data.csv"
    csv.write_text("x\n1\n")
    sidecar = tmp_path / "data.csv-metadata.json"
    sidecar.write_text(json.dumps({
        "@context": "http://www.w3.org/ns/csvw",
        "url": "data.csv",
        "dc:description": "from sidecar",
        "tableSchema": {
            "columns": [{"name": "x", "datatype": "integer"}],
        },
    }))

    handler = BuiltinFormatHandler()
    result = handler.read_metadata(str(csv), LocalFileHandler())
    assert result is not None
    assert result.description == "from sidecar"
    assert result.field_metadata["x"].type == "integer"


def test_builtin_handler_read_metadata_returns_none_for_non_csv(tmp_path):
    """Non-CSV files (json, xlsx) get no sidecar lookup."""
    from sunstone.handlers import BuiltinFormatHandler, LocalFileHandler

    json_file = tmp_path / "data.json"
    json_file.write_text("{}")
    handler = BuiltinFormatHandler()
    assert handler.read_metadata(str(json_file), LocalFileHandler()) is None


def test_builtin_handler_write_metadata_writes_sibling_sidecar(tmp_path):
    """Default write_metadata produces <csv>.csv-metadata.json next to the data."""
    import json

    from sunstone.handlers import BuiltinFormatHandler, LocalFileHandler
    from sunstone.lineage import FieldSchema, Metadata

    csv = tmp_path / "out.csv"
    csv.write_text("x,y\n1,2\n")
    meta = Metadata(
        description="output",
        field_metadata={"x": FieldSchema(name="x", type="integer")},
    )
    handler = BuiltinFormatHandler()
    written = handler.write_metadata(str(csv), meta, LocalFileHandler())

    expected = csv.parent / "out.csv-metadata.json"
    assert written == str(expected)
    assert expected.exists()
    doc = json.loads(expected.read_text())
    assert doc["tables"][0]["url"] == "out.csv"
    assert doc["tables"][0]["dc:description"] == "output"


def test_builtin_handler_write_metadata_to_explicit_path(tmp_path):
    """An explicit ``target`` writes to that path instead of sibling."""
    import json

    from sunstone.handlers import BuiltinFormatHandler, LocalFileHandler
    from sunstone.lineage import Metadata

    csv = tmp_path / "out.csv"
    csv.write_text("x\n1\n")
    explicit = tmp_path / "shared.csvm.json"

    handler = BuiltinFormatHandler()
    written = handler.write_metadata(
        str(csv), Metadata(), LocalFileHandler(), target=str(explicit)
    )
    assert written == str(explicit)
    doc = json.loads(explicit.read_text())
    assert doc["tables"][0]["url"] == "out.csv"


def test_builtin_handler_list_metadata_resources_for_csvs(tmp_path):
    """list_metadata_resources discovers per-CSV sidecars."""
    import json

    from sunstone.handlers import BuiltinFormatHandler

    csv = tmp_path / "a.csv"
    csv.write_text("x\n1\n")
    sidecar = tmp_path / "a.csv-metadata.json"
    sidecar.write_text(json.dumps({
        "@context": "http://www.w3.org/ns/csvw",
        "url": "a.csv",
        "tableSchema": {"columns": [{"name": "x"}]},
    }))

    handler = BuiltinFormatHandler()
    resources = handler.list_metadata_resources([str(csv)])
    assert len(resources) == 1
    assert resources[0].path == sidecar
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_handlers.py -v -k "read_metadata or write_metadata or list_metadata_resources"
```
Expected: tests fail (methods are no-ops returning None / []).

- [ ] **Step 3: Implement the dispatch on `BuiltinFormatHandler`**

Replace the no-op methods on `BuiltinFormatHandler` (in `src/sunstone/handlers.py`) added in Task 2 with real dispatch:

```python
class BuiltinFormatHandler:
    # ... existing methods (supports_metadata, can_read, read, can_write, write, _resolve_format) ...

    @staticmethod
    def _ext(data_path: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(data_path)
        path_str = parsed.path if parsed.scheme else data_path
        return PurePosixPath(path_str).suffix.lower()

    def read_metadata(self, data_path, url_handler):
        if self._ext(data_path) not in (".csv", ".tsv"):
            return None
        from . import _csvw

        result = _csvw.find_sidecar(Path(data_path), url_handler)
        if result is None:
            return None
        _sidecar_path, table = result
        return _csvw.csvw_to_metadata(table)

    def write_metadata(self, data_path, metadata, url_handler, *, target=None):
        if self._ext(data_path) not in (".csv", ".tsv"):
            return None
        from . import _csvw

        sidecar_path = (
            Path(target) if target is not None
            else Path(str(data_path) + "-metadata.json")
        )
        table = _csvw.metadata_to_csvw_table(Path(data_path), metadata)
        _csvw.upsert_table_in_sidecar(
            sidecar_path, Path(data_path), table, url_handler
        )
        return str(sidecar_path)

    def list_metadata_resources(self, data_paths):
        from . import _csvw

        csv_paths = [
            Path(p) for p in data_paths if self._ext(p) in (".csv", ".tsv")
        ]
        if not csv_paths:
            return []
        return _csvw.enumerate_sidecars_for(csv_paths)
```

(Keep `Path` and `PurePosixPath` imports already in the file.)

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_handlers.py -v -k "read_metadata or write_metadata or list_metadata_resources"
```
Expected: 5 passed.

Run full suite to confirm no regressions:
```bash
uv run pytest -q
```
Expected: all previously-passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "feat: BuiltinFormatHandler routes CSV/TSV metadata to _csvw"
```

---

## Task 9: Integrate sidecar reads into `DataFrame.read_csv`

**Files:**
- Modify: `src/sunstone/dataframe.py:368-481` (`read_csv` method)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_dataframe.py`:

```python
class TestReadCsvSidecarIntegration:
    def test_sidecar_metadata_fills_gaps_in_datasets_yaml(self, tmp_path):
        """When datasets.yaml has no field metadata, sidecar populates it."""
        import json

        from sunstone import pandas as pd

        # Set up a project with datasets.yaml that registers a CSV with
        # only the bare minimum (no field schemas).
        (tmp_path / "datasets.yaml").write_text(
            "inputs:\n"
            "  - name: Sidecar Test\n"
            "    slug: sidecar-test\n"
            "    location: data.csv\n"
        )
        csv = tmp_path / "data.csv"
        csv.write_text("x,y\n1,2\n3,4\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text(json.dumps({
            "@context": "http://www.w3.org/ns/csvw",
            "url": "data.csv",
            "dc:description": "from sidecar",
            "tableSchema": {
                "columns": [
                    {"name": "x", "datatype": "integer", "dc:description": "ex axis"},
                    {"name": "y", "datatype": "integer"},
                ]
            },
        }))

        df = pd.read_csv("data.csv", project_path=tmp_path)
        # datasets.yaml had no description — sidecar fills it
        assert df.metadata.description == "from sidecar"
        # datasets.yaml had no field metadata — sidecar fills both
        assert df.metadata.field_metadata["x"].description == "ex axis"
        assert df.metadata.field_metadata["x"].type == "integer"
        assert df.metadata.field_metadata["y"].type == "integer"

    def test_datasets_yaml_wins_on_conflict(self, tmp_path):
        """When both sources define the same field, datasets.yaml wins."""
        import json

        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text(
            "inputs:\n"
            "  - name: Conflict Test\n"
            "    slug: conflict-test\n"
            "    location: data.csv\n"
            "    description: from yaml\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
            "        description: yaml says x\n"
        )
        csv = tmp_path / "data.csv"
        csv.write_text("x\n1\n")
        sidecar = tmp_path / "data.csv-metadata.json"
        sidecar.write_text(json.dumps({
            "@context": "http://www.w3.org/ns/csvw",
            "url": "data.csv",
            "dc:description": "sidecar says hello",
            "tableSchema": {
                "columns": [
                    {"name": "x", "dc:description": "sidecar says x"},
                ]
            },
        }))

        df = pd.read_csv("data.csv", project_path=tmp_path)
        assert df.metadata.description == "from yaml"
        assert df.metadata.field_metadata["x"].description == "yaml says x"
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_dataframe.py::TestReadCsvSidecarIntegration -v
```
Expected: assertion failures because sidecar data is not yet merged.

- [ ] **Step 3: Inject sidecar metadata into the read flow**

In `src/sunstone/dataframe.py` modify `read_csv` (currently lines 368-481). After the `with url_handler.open(location, "rb") as stream:` block where `df = format_handler.read(...)` runs, AND before the `# Create lineage metadata` block, add:

```python
        # Read external sidecar metadata (CSVW for CSV/TSV, no-op for others)
        sidecar_metadata = None
        try:
            sidecar_metadata = format_handler.read_metadata(location, url_handler)
        except AttributeError:
            # Legacy plugin handler without read_metadata; treat as no-op
            sidecar_metadata = None
```

Then immediately after the `metadata = Metadata(lineage=LineageMetadata(...))` and before `metadata.lineage.add_source(dataset)`, merge the sidecar:

```python
        if sidecar_metadata is not None:
            # datasets.yaml fields will be populated below by add_source +
            # populate_field_derivations. Sidecar fills gaps in description,
            # field-level descriptions/types, RDF prefixes, and custom
            # properties. datasets.yaml-driven values take precedence and are
            # applied AFTER this merge by add_source/populate_field_derivations.
            if metadata.description is None and sidecar_metadata.description is not None:
                metadata.description = sidecar_metadata.description
            for col, fs in sidecar_metadata.field_metadata.items():
                metadata.field_metadata.setdefault(col, fs)
            if sidecar_metadata.rdf_prefixes:
                metadata.rdf_prefixes = {
                    **(sidecar_metadata.rdf_prefixes),
                    **(metadata.rdf_prefixes or {}),
                }
            if sidecar_metadata.custom_properties:
                metadata.custom_properties = {
                    **(sidecar_metadata.custom_properties),
                    **(metadata.custom_properties or {}),
                }
```

Note: the precedence rule is "datasets.yaml > sidecar". Because `add_source` runs *after* the sidecar merge above and pulls field metadata from `dataset.fields` (the parsed datasets.yaml), datasets.yaml wins for any field schema it defines. The `setdefault` calls ensure the sidecar only fills gaps, not overrides.

- [ ] **Step 4: Verify the precedence by inspecting `_apply_dataset_to_metadata` (or equivalent)**

Open `src/sunstone/dataframe.py` and find where the dataset's `fields` are merged into `metadata.field_metadata`. If it overwrites unconditionally (datasets.yaml wins), the precedence is correct as-is. If it uses `setdefault` (sidecar would win), swap to overwrite for `field_metadata` keys explicitly listed in `dataset.fields`.

The relevant code lives near `metadata.lineage.add_source(dataset)` and the existing Parquet-embedded merge at lines 340-357. Pattern to follow:

```python
# After sidecar merge (gap-fill) but before applying datasets.yaml fields:
if dataset.fields:
    for fs in dataset.fields:
        metadata.field_metadata[fs.name] = fs  # datasets.yaml wins
```

- [ ] **Step 5: Apply the same merge in `read_dataset` (sister method)**

The `read_dataset` classmethod (used when reading by slug) handles its own metadata merge. Find the corresponding spot (around `dataframe.py:340-365`) and add the same sidecar-gap-fill merge there. The sidecar lookup is identical:

```python
        sidecar_metadata = None
        try:
            sidecar_metadata = format_handler.read_metadata(
                str(absolute_path), url_handler
            )
        except AttributeError:
            sidecar_metadata = None

        if sidecar_metadata is not None:
            if metadata.description is None and sidecar_metadata.description is not None:
                metadata.description = sidecar_metadata.description
            for col, fs in sidecar_metadata.field_metadata.items():
                metadata.field_metadata.setdefault(col, fs)
            if sidecar_metadata.rdf_prefixes:
                metadata.rdf_prefixes = {
                    **sidecar_metadata.rdf_prefixes,
                    **(metadata.rdf_prefixes or {}),
                }
            if sidecar_metadata.custom_properties:
                metadata.custom_properties = {
                    **sidecar_metadata.custom_properties,
                    **(metadata.custom_properties or {}),
                }
```

(Place this BEFORE the existing `embedded_metadata` merge block at lines 340-357 so the order is: datasets.yaml > Parquet-embedded > CSVW sidecar — this is consistent with treating embedded as more authoritative than external sidecar.)

- [ ] **Step 6: Run tests; verify they pass**

```bash
uv run pytest tests/test_dataframe.py::TestReadCsvSidecarIntegration -v
uv run pytest -q
```
Expected: new tests pass; full suite still green.

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: merge CSVW sidecar metadata into read_csv and read_dataset"
```

---

## Task 10: Add `csvw_metadata` kwarg to `DataFrame.to_csv`

**Files:**
- Modify: `src/sunstone/dataframe.py:606-731` (`to_csv` method)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_dataframe.py`:

```python
class TestToCsvSidecar:
    def test_default_writes_sibling_sidecar(self, tmp_path):
        """W3C convention: out.csv -> out.csv-metadata.json."""
        import json

        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text("outputs: []\n")
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]}, project_path=tmp_path)
        df.metadata.description = "default sidecar test"

        out = tmp_path / "out.csv"
        df.to_csv(str(out), slug="default-sidecar", name="Default Sidecar")

        sidecar = tmp_path / "out.csv-metadata.json"
        assert sidecar.exists(), f"Expected {sidecar}, found: {list(tmp_path.iterdir())}"
        doc = json.loads(sidecar.read_text())
        assert doc["tables"][0]["url"] == "out.csv"
        assert doc["tables"][0]["dc:description"] == "default sidecar test"

    def test_csvw_metadata_false_skips_sidecar(self, tmp_path):
        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text("outputs: []\n")
        df = pd.DataFrame({"x": [1]}, project_path=tmp_path)

        out = tmp_path / "out.csv"
        df.to_csv(str(out), slug="no-sidecar", name="No Sidecar", csvw_metadata=False)

        # No sidecar of any tier-1 name
        for suffix in (".csv-metadata.json", "-metadata.json", ".csvm.json"):
            assert not (out.parent / (out.stem + suffix)).exists()
            assert not (out.parent / (out.name + suffix)).exists()

    def test_csvw_metadata_explicit_path(self, tmp_path):
        import json

        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text("outputs: []\n")
        df = pd.DataFrame({"x": [1]}, project_path=tmp_path)

        explicit = tmp_path / "explicit.csvm.json"
        out = tmp_path / "out.csv"
        df.to_csv(
            str(out),
            slug="explicit",
            name="Explicit",
            csvw_metadata=str(explicit),
        )

        assert explicit.exists()
        doc = json.loads(explicit.read_text())
        urls = [t["url"] for t in doc["tables"]]
        assert "out.csv" in urls or str(out) in urls

    def test_shared_csvm_accumulates_across_calls(self, tmp_path):
        import json

        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text("outputs: []\n")
        df_a = pd.DataFrame({"x": [1]}, project_path=tmp_path)
        df_b = pd.DataFrame({"y": [2]}, project_path=tmp_path)

        shared = tmp_path / "shared.csvm.json"
        df_a.to_csv(str(tmp_path / "a.csv"), slug="a", name="A", csvw_metadata=str(shared))
        df_b.to_csv(str(tmp_path / "b.csv"), slug="b", name="B", csvw_metadata=str(shared))

        doc = json.loads(shared.read_text())
        urls = sorted(t["url"] for t in doc["tables"])
        # Match by basename to be flexible about absolute vs relative urls
        assert "a.csv" in urls or any(u.endswith("a.csv") for u in urls)
        assert "b.csv" in urls or any(u.endswith("b.csv") for u in urls)

    def test_csvw_metadata_kwarg_not_passed_to_pandas(self, tmp_path):
        """Smoke: csvw_metadata is filtered out before pandas.to_csv sees it."""
        from sunstone import pandas as pd

        (tmp_path / "datasets.yaml").write_text("outputs: []\n")
        df = pd.DataFrame({"x": [1]}, project_path=tmp_path)
        # If the kwarg leaked, pandas would raise TypeError
        df.to_csv(str(tmp_path / "out.csv"), slug="x", name="X", csvw_metadata=False)
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_dataframe.py::TestToCsvSidecar -v
```
Expected: failures (kwarg unrecognized; sidecar not produced).

- [ ] **Step 3: Modify `to_csv` signature and add the post-write sidecar call**

In `src/sunstone/dataframe.py`:

1. Modify the `_SUNSTONE_KWARGS` set near line 604 to add `"csvw_metadata"`:

```python
    _SUNSTONE_KWARGS = {"publish", "transformation_params", "csvw_metadata"}
```

2. Modify `to_csv`'s signature (line 606) to accept the new kwarg:

```python
    def to_csv(
        self,
        path_or_buf: Union[str, Path],
        slug: Optional[str] = None,
        name: Optional[str] = None,
        publish: bool = False,
        transformation_params: Optional[dict] = None,
        track: bool = True,
        csvw_metadata: Union[bool, str, Path] = True,
        **kwargs: Any,
    ) -> None:
```

3. After the data-write block (existing code that calls `format_writer.write` or `self.data.to_csv`), AND after `data_hash = compute_dataframe_hash(self.data)` and before `manager.update_output_lineage(...)`, add the sidecar emission:

```python
        # CSVW sidecar emission (Q5)
        if csvw_metadata is not False:
            target: Optional[str]
            if csvw_metadata is True:
                target = None  # use sibling default
            else:
                # str or Path
                target = str(csvw_metadata)
                # Path-traversal safety for explicit paths
                from .packaging import _validate_path_containment, PathTraversalError
                try:
                    _validate_path_containment(
                        target,
                        manager.project_path,
                        context="csvw sidecar path",
                    )
                except PathTraversalError:
                    raise

            try:
                format_writer.write_metadata(
                    str(absolute_path),
                    self.metadata,
                    url_handler,
                    target=target,
                )
            except AttributeError:
                # Legacy handler without write_metadata; silently skip
                pass
```

- [ ] **Step 4: Run tests; verify they pass**

```bash
uv run pytest tests/test_dataframe.py::TestToCsvSidecar -v
uv run pytest -q
```
Expected: new tests pass; full suite still green.

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: csvw_metadata kwarg on to_csv emits CSVW sidecar"
```

---

## Task 11: Wire sidecar resources into `packaging.push_group`

**Files:**
- Modify: `src/sunstone/packaging.py`
- Modify: `src/sunstone/cli.py:1124-1300` (`build_resource_dict` and callers)
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_packaging.py`:

```python
class TestPushGroupCsvwSidecars:
    def _make_push_args(self, manager, datasets, project_slug):
        """Helper: build the kwargs push_group needs."""
        from sunstone.cli import build_resource_dict
        from sunstone.lineage import PublishConfig

        return dict(
            datasets=datasets,
            manager=manager,
            project_slug=project_slug,
            publish_config=PublishConfig(enabled=True, to="file:///tmp/test"),
            build_resource_dict_fn=build_resource_dict,
            package_metadata_fn=lambda: None,
            rdf_prefixes={},
            top_level_props={},
            methodology_files=[],
            allow_outside_project=True,
        )

    def test_per_csv_sidecar_appears_in_resources_with_cross_ref(
        self, tmp_path, monkeypatch
    ):
        """A per-CSV sidecar gets added as a resource and the CSV gets the cross-ref."""
        import json
        from pathlib import Path

        from sunstone.datasets import DatasetsManager
        from sunstone.packaging import push_group

        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: A\n"
            "    slug: a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
        )
        (tmp_path / "a.csv").write_text("x\n1\n")
        sidecar = tmp_path / "a.csv-metadata.json"
        sidecar.write_text(json.dumps({
            "@context": "http://www.w3.org/ns/csvw",
            "url": "a.csv",
            "tableSchema": {"columns": [{"name": "x"}]},
        }))

        manager = DatasetsManager(tmp_path)
        datasets = manager.get_all_outputs()

        # Capture writes via a fake URLHandler
        written: dict[str, bytes] = {}

        class FakeHandler:
            def can_handle(self, url):
                return url.startswith("file://")

            def open(self, url, mode):
                from io import BytesIO, StringIO

                if "w" in mode:
                    if "b" in mode:
                        buf = BytesIO()
                    else:
                        buf = StringIO()

                    class _Writer:
                        def __enter__(self_inner):
                            return buf

                        def __exit__(self_inner, *exc):
                            written[url] = (
                                buf.getvalue().encode()
                                if isinstance(buf.getvalue(), str)
                                else buf.getvalue()
                            )
                            return False
                    return _Writer()
                raise NotImplementedError

        from sunstone.plugins import PluginRegistry
        registry = PluginRegistry.get(tmp_path)
        registry._url_handlers.insert(0, FakeHandler())

        try:
            push_group(
                dest_url="file:///tmp/test",
                **self._make_push_args(manager, datasets, "test"),
            )
        finally:
            registry._url_handlers.pop(0)

        # datapackage.json was written
        dp_url = "file:///tmp/test/datapackage.json"
        assert dp_url in written
        dp = json.loads(written[dp_url])

        # Sidecar appears as a resource
        sidecar_resources = [
            r for r in dp["resources"] if r.get("path") == "a.csv-metadata.json"
        ]
        assert len(sidecar_resources) == 1

        # CSV resource has the cross-reference property
        csv_resources = [r for r in dp["resources"] if r.get("path") == "a.csv"]
        assert len(csv_resources) == 1
        assert (
            "https://sunstone.institute/rdf/vocab#csvwMetadata"
            in csv_resources[0]
        )
        assert (
            csv_resources[0][
                "https://sunstone.institute/rdf/vocab#csvwMetadata"
            ]
            == "a.csv-metadata.json"
        )

    def test_csvm_referencing_outsider_fails_build(self, tmp_path):
        """csvm covering a CSV not in the package raises PackageValidationError."""
        import json

        from sunstone.datasets import DatasetsManager
        from sunstone.exceptions import PackageValidationError
        from sunstone.packaging import push_group

        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: A\n"
            "    slug: a\n"
            "    location: a.csv\n"
            "    fields:\n"
            "      - name: x\n"
            "        type: integer\n"
        )
        (tmp_path / "a.csv").write_text("x\n1\n")
        # csvm.json references a.csv AND outsider.csv
        (tmp_path / "csvm.json").write_text(json.dumps({
            "@context": "http://www.w3.org/ns/csvw",
            "tables": [
                {"url": "a.csv", "tableSchema": {"columns": [{"name": "x"}]}},
                {"url": "outsider.csv", "tableSchema": {"columns": [{"name": "y"}]}},
            ],
        }))

        manager = DatasetsManager(tmp_path)
        datasets = manager.get_all_outputs()

        with pytest.raises(PackageValidationError) as exc_info:
            push_group(
                dest_url="file:///tmp/test",
                **self._make_push_args(manager, datasets, "test"),
            )
        assert "outsider.csv" in str(exc_info.value)
```

- [ ] **Step 2: Run tests; verify they fail**

```bash
uv run pytest tests/test_packaging.py::TestPushGroupCsvwSidecars -v
```
Expected: failures (sidecar resources not yet added; outsider.csv not validated).

- [ ] **Step 3: Modify `push_group` to enumerate and emit sidecars**

In `src/sunstone/packaging.py`, inside `push_group`, after the existing `for ds in datasets:` loop that builds `resources` and `data_files` (around line 178-192), and before the `if not resources: return []` check, add:

```python
    # Sidecar resources (CSVW for CSV/TSV, no-op for other formats)
    sidecar_resource_files: list[tuple[Path, str, str]] = []
    cross_refs_to_apply: dict[str, dict[str, str]] = {}  # csv resource_path -> {prop: value}
    handlers_seen: set[int] = set()

    # Group data paths by their format handler
    handler_to_paths: dict[FormatHandler, list[Path]] = {}
    for ds in datasets:
        data_path = manager.get_absolute_path(ds.location)
        handler = registry.find_format_writer(str(data_path), None)
        if handler is None:
            continue
        handler_to_paths.setdefault(handler, []).append(data_path)

    for handler, paths in handler_to_paths.items():
        try:
            sidecar_resources = handler.list_metadata_resources([str(p) for p in paths])
        except AttributeError:
            sidecar_resources = []

        for sr in sidecar_resources:
            sidecar_abs = sr.path if sr.path.is_absolute() else (project_root / sr.path)
            try:
                sidecar_rel = sidecar_abs.relative_to(project_root).as_posix()
            except ValueError:
                if not allow_outside_project:
                    raise PathTraversalError(
                        f"Refusing to publish sidecar that resolves outside the project root: {sidecar_abs}"
                    )
                sidecar_rel = sidecar_abs.name  # flatten outside-project sidecars

            # LFS pointer guard
            if is_lfs_pointer(sidecar_abs):
                raise ValueError(
                    f"Sidecar file is a Git LFS pointer, not actual content: {sidecar_rel}. "
                    f"Run 'git lfs pull' to download the actual files before pushing."
                )

            # Compute remote path
            if publish_config.flatten:
                sidecar_remote = base_dir + sidecar_abs.name
                sidecar_resource_path = sidecar_abs.name
            else:
                sidecar_remote = base_dir + sidecar_rel
                sidecar_resource_path = sidecar_rel

            # Append as a separate resource
            resources.append({"path": sidecar_resource_path})
            sidecar_resource_files.append(
                (sidecar_abs, sidecar_remote, sidecar_resource_path)
            )

            # Record cross-ref for each covered CSV
            for covered in sr.covers:
                covered_abs = covered.resolve()
                # Find the matching CSV resource in `data_files` and record the property
                for _local, _remote, csv_resource_path in data_files:
                    csv_abs = (project_root / csv_resource_path).resolve()
                    if csv_abs == covered_abs:
                        cross_refs_to_apply.setdefault(
                            csv_resource_path, {}
                        )[sr.cross_ref_property] = sidecar_resource_path
                        break

    # Apply cross-refs to the resource dicts
    for resource_dict in resources:
        rp = resource_dict.get("path")
        if rp in cross_refs_to_apply:
            resource_dict.update(cross_refs_to_apply[rp])
```

(Place this block immediately after the existing per-dataset loop and before the `if not resources: return []` check.)

Then, after the existing data-files upload loop and before the methodology-files upload loop, add the sidecar upload loop:

```python
    # Upload sidecar files
    for abs_path, remote_path, resource_path in sidecar_resource_files:
        sidecar_url = f"{parsed.scheme}://{parsed.netloc}/{remote_path}"
        with open(abs_path, "rb") as src, handler.open(sidecar_url, "wb") as dst:
            while True:
                chunk = src.read(8192)
                if not chunk:
                    break
                dst.write(chunk)
        uploaded.append(resource_path)
```

- [ ] **Step 4: Add `FormatHandler` to packaging imports**

At the top of `src/sunstone/packaging.py`, add:

```python
from .plugins import FormatHandler  # noqa: F401  (used for type hints in inline dict)
```

- [ ] **Step 5: Run tests; verify they pass**

```bash
uv run pytest tests/test_packaging.py::TestPushGroupCsvwSidecars -v
uv run pytest -q
```
Expected: new tests pass; full suite still green.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/packaging.py tests/test_packaging.py
git commit -m "feat: include CSVW sidecars and cross-refs in datapackage.json"
```

---

## Task 12: End-to-end round-trip integration test

**Files:**
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write the round-trip test**

Append to `tests/test_dataframe.py`:

```python
class TestCsvwRoundTrip:
    def test_to_csv_then_read_csv_recovers_field_metadata(self, tmp_path):
        """Write a DataFrame with field metadata to CSV; read it back via
        pandas.read_csv; verify the field metadata flows through the
        sidecar (no datasets.yaml field schemas defined)."""
        from sunstone import pandas as pd
        from sunstone.lineage import FieldSchema

        # Project with a registered output but no field schemas
        (tmp_path / "datasets.yaml").write_text(
            "outputs:\n"
            "  - name: RT\n"
            "    slug: rt\n"
            "    location: out.csv\n"
        )

        df = pd.DataFrame(
            {"x": [1, 2, 3], "y": [10.5, 20.5, 30.5]},
            project_path=tmp_path,
        )
        df.metadata.description = "round-trip test"
        df.set_field_metadata("x", FieldSchema(name="x", type="integer", description="counts"))
        df.set_field_metadata("y", FieldSchema(name="y", type="decimal", description="values"))

        df.to_csv(str(tmp_path / "out.csv"), slug="rt", name="RT")

        # Move datasets.yaml to a fresh state with NO field schemas — the
        # sidecar should be the sole source of truth for the round-trip.
        (tmp_path / "datasets.yaml").write_text(
            "inputs:\n"
            "  - name: RT\n"
            "    slug: rt\n"
            "    location: out.csv\n"
        )

        df2 = pd.read_csv("out.csv", project_path=tmp_path)
        assert df2.metadata.description == "round-trip test"
        assert df2.metadata.field_metadata["x"].description == "counts"
        assert df2.metadata.field_metadata["x"].type == "integer"
        assert df2.metadata.field_metadata["y"].description == "values"
```

- [ ] **Step 2: Run the test; verify it passes**

```bash
uv run pytest tests/test_dataframe.py::TestCsvwRoundTrip -v
```
Expected: 1 passed.

If it fails because the sidecar path is `out.csv.csv-metadata.json` rather than `out.csv-metadata.json`, that's the convention the spec defines (canonical W3C: `<name>.csv-metadata.json` where `<name>` is the full filename including `.csv`). Update the test accordingly if needed; do NOT change the convention.

- [ ] **Step 3: Commit**

```bash
git add tests/test_dataframe.py
git commit -m "test: end-to-end CSVW sidecar round-trip via pandas API"
```

---

## Task 13: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add entry under `[Unreleased]`**

In `CHANGELOG.md`, find the `## [Unreleased]` section (create it at the top below the file header if missing) and add:

```markdown
- Added: CSVW sidecar support for CSV reads and writes. `DataFrame.read_csv`
  and `read_dataset` now discover CSVW JSON-LD sidecars (`*.csv-metadata.json`,
  `*-metadata.json`, `*.csvm.json`, plus shared `csvm.json` / `metadata.json`)
  and merge them into `df.metadata` (datasets.yaml wins, sidecar fills gaps).
- Added: `csvw_metadata: bool | str | Path = True` kwarg on `DataFrame.to_csv`
  to control sidecar emission (default: write a sibling `*.csv-metadata.json`).
- Added: CSVW sidecars are included in `datapackage.json` as additional
  resources, with a `https://sunstone.institute/rdf/vocab#csvwMetadata`
  cross-reference property on each covered CSV resource.
- Added: `FormatHandler` protocol gains `read_metadata`, `write_metadata`,
  and `list_metadata_resources` methods (no-op defaults; non-breaking).
- Added: `CSVWSidecarError` and `PackageValidationError` exceptions.
- Added: `csvw>=3.7` runtime dependency.
```

- [ ] **Step 2: Verify the file parses cleanly (no formatting errors)**

```bash
uv run pytest -q
```
Expected: no test depends on CHANGELOG; just ensures we didn't break anything else with this commit.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for CSVW sidecar support"
```

---

## Final verification

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -q
```
Expected: all tests pass (previous baseline was 960; this PR adds ~30+ new tests).

- [ ] **Step 2: Check coverage**

```bash
uv run pytest --cov=src/sunstone --cov-report=term-missing -q
```
Expected: `src/sunstone/_csvw.py` ≥ 95% line coverage; overall ≥ 93%.

- [ ] **Step 3: Run pre-commit hooks against the full diff**

```bash
git log main..HEAD --oneline
uv run pre-commit run --files $(git diff --name-only main..HEAD)
```
Expected: all hooks pass (ruff, mypy, etc.).

- [ ] **Step 4: Verify the worktree is clean**

```bash
git status
```
Expected: nothing to commit, working tree clean.

---

## Notes for the implementer

- **`DataFrame` API:** `pd.DataFrame(...)` in `from sunstone import pandas as pd` returns a Sunstone `DataFrame` with metadata. If `pd.DataFrame(data, project_path=...)` doesn't directly accept `project_path`, look at how existing tests construct Sunstone DataFrames (most likely via `pd.read_csv` or by using the `DataFrame` class from `sunstone.dataframe` directly). Adjust test fixtures accordingly.
- **Sidecar default name:** for an input file named `out.csv`, the W3C convention sidecar is `out.csv-metadata.json` (the suffix `-metadata.json` is appended to the FULL CSV filename including the `.csv` extension). The internal templates live in `_csvw._TIER1_NAME_TEMPLATES`; do not introduce inconsistent forms in tests.
- **Path containment for sidecars:** `_validate_path_containment` exists in `packaging.py`. Reuse it; do not duplicate.
- **Refrain from premature optimization:** Task 11's sidecar discovery rescans the filesystem per `push_group` call. That's fine — package builds are not in a hot path.
- **No state on `BuiltinFormatHandler`:** The plan deliberately does NOT add a `CSVMRegistry` instance to the handler. The on-disk csvm files are the single source of truth; `upsert_table_in_sidecar` reads-then-writes on each call. This keeps the handler stateless and the cross-run semantics correct without extra plumbing.
- **`csvw` library quirks:** the library's parser warns on unknown properties rather than raising. We use a structural signature check (`@context` referencing csvw + `tableSchema` or `tables`) instead of relying on the library to validate.
