# Geo Phase 1: Field-Type Registry + Format-Driven Resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a plugin-extensible field (column) value-type registry and make `datasets.yaml` `format` drive handler resolution — the core seam geo (Phase 2) builds on, with no geospatial dependency.

**Architecture:** A new `FieldTypeRegistry` holds `FieldTypeDescriptor`s (built-in Frictionless scalar types pre-registered; plugins add structured types like `geometry` later). `PluginRegistry` discovers a plugin's `field_types()` during registration. `DatasetMetadata` gains a `format` field; `read_dataset` threads it into `find_format_reader` so a pinned `format` overrides extension detection.

**Tech Stack:** Python 3.11+, dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-16-geojson-topojson-vector-support-design.md` (D2, D4).

---

### Task 1: Add `format` to `DatasetMetadata` and parse it

**Files:**
- Modify: `src/sunstone/lineage.py` (the `DatasetMetadata` dataclass, ~line 371 after `resource_type`)
- Modify: `src/sunstone/datasets.py` (`_parse_dataset`, the `return DatasetMetadata(...)` block ~line 693)
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write the failing test**

```python
def test_dataset_format_field_parsed(tmp_path):
    from sunstone.datasets import DatasetsManager
    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n"
        "  - name: World Borders\n"
        "    slug: world-borders\n"
        "    location: inputs/world.json\n"
        "    format: geojson\n"
    )
    mgr = DatasetsManager(tmp_path)
    ds = mgr.find_dataset_by_slug("world-borders")
    assert ds is not None
    assert ds.format == "geojson"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_datasets.py::test_dataset_format_field_parsed -v --no-cov`
Expected: FAIL — `AttributeError: 'DatasetMetadata' object has no attribute 'format'`

- [ ] **Step 3: Add the field to `DatasetMetadata`**

In `src/sunstone/lineage.py`, immediately after the `resource_type` field:

```python
    format: Optional[str] = None
    """Serialization format (e.g. 'geojson', 'topojson', 'csv'). Drives handler
    resolution when set; otherwise the file extension is used."""
```

- [ ] **Step 4: Parse it in `_parse_dataset`**

In `src/sunstone/datasets.py`, in the `return DatasetMetadata(...)` call, add after `resource_type=dataset_data.get("type"),`:

```python
            format=dataset_data.get("format"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_datasets.py::test_dataset_format_field_parsed -v --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py tests/test_datasets.py
git commit -m "feat: add format field to dataset metadata"
```

---

### Task 2: Field-type registry and descriptor

**Files:**
- Create: `src/sunstone/field_types.py`
- Test: `tests/test_field_types.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sunstone.field_types import (
    FieldTypeDescriptor, FieldTypeRegistry, validate_field_value, FieldTypeValidationError,
)


def test_builtin_scalar_types_present():
    reg = FieldTypeRegistry()
    for name in ("string", "integer", "number", "boolean", "date", "datetime", "any"):
        assert reg.get(name) is not None


def test_register_and_get_custom_type():
    reg = FieldTypeRegistry()
    desc = FieldTypeDescriptor(name="geometry", validate=lambda v: hasattr(v, "geom_type"))
    reg.register(desc)
    assert reg.get("geometry") is desc
    assert "geometry" in reg.known()


def test_validate_is_mode_gated():
    reg = FieldTypeRegistry()
    reg.register(FieldTypeDescriptor(name="geometry", validate=lambda v: v == "ok"))
    # lenient: bad value does not raise
    validate_field_value(reg, "geometry", "bad", strict=False)
    # strict: bad value raises
    with pytest.raises(FieldTypeValidationError):
        validate_field_value(reg, "geometry", "bad", strict=True)
    # unknown type or no validator: no-op even in strict mode
    validate_field_value(reg, "string", "anything", strict=True)
    validate_field_value(reg, "not-registered", "anything", strict=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_field_types.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sunstone.field_types'`

- [ ] **Step 3: Write the implementation**

Create `src/sunstone/field_types.py`:

```python
"""Registry of field (column) value-types for dataset schemas.

Built-in scalar types mirror the Frictionless Table Schema vocabulary. Plugins
extend this with structured/domain types (e.g. ``geometry``) via
``FieldTypeDescriptor`` — see ``PluginRegistry`` classification. This is the
extensibility seam for non-scalar columns; geometry is the first consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


class FieldTypeValidationError(ValueError):
    """A field value failed its registered type contract in strict mode."""


@dataclass(frozen=True)
class FieldTypeDescriptor:
    """Describes a field (column) value-type.

    ``validate`` is an optional cell-level contract: it returns True for a
    valid value. ``None`` means "no contract" (always accepted).
    """

    name: str
    validate: Optional[Callable[[Any], bool]] = None
    description: Optional[str] = None


# Frictionless Table Schema scalar types (plus "any").
_BUILTIN_SCALAR_TYPES: tuple[str, ...] = (
    "string", "number", "integer", "boolean", "object", "array",
    "date", "datetime", "time", "year", "yearmonth", "duration", "any",
)


class FieldTypeRegistry:
    """Holds known field value-types, keyed by name."""

    def __init__(self) -> None:
        self._types: dict[str, FieldTypeDescriptor] = {
            name: FieldTypeDescriptor(name=name) for name in _BUILTIN_SCALAR_TYPES
        }

    def register(self, descriptor: FieldTypeDescriptor) -> None:
        self._types[descriptor.name] = descriptor

    def get(self, name: str) -> Optional[FieldTypeDescriptor]:
        return self._types.get(name)

    def known(self) -> tuple[str, ...]:
        return tuple(self._types)


def validate_field_value(
    registry: FieldTypeRegistry, type_name: str, value: Any, *, strict: bool
) -> None:
    """Validate ``value`` against the contract for ``type_name``.

    No-op when the type is unknown or has no contract. In strict mode a failed
    contract raises ``FieldTypeValidationError``; in lenient mode it is ignored.
    """
    descriptor = registry.get(type_name)
    if descriptor is None or descriptor.validate is None:
        return
    if not descriptor.validate(value) and strict:
        raise FieldTypeValidationError(
            f"Value {value!r} is not valid for field type {type_name!r}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_field_types.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/field_types.py tests/test_field_types.py
git commit -m "feat: field-type registry for column value-types"
```

---

### Task 3: Discover `field_types()` from plugins; expose a shared registry

**Files:**
- Modify: `src/sunstone/plugins.py` (`PluginRegistry.__init__`, `_register`, and `_register_builtins`)
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Write the failing test**

```python
def test_plugin_field_types_are_registered():
    from sunstone.field_types import FieldTypeDescriptor
    from sunstone.plugins import PluginRegistry

    class FakeGeoPlugin:
        def field_types(self):
            return (FieldTypeDescriptor(name="geometry", validate=lambda v: True),)

    reg = PluginRegistry()
    reg._register("fake-geo", FakeGeoPlugin())
    assert reg.field_types.get("geometry") is not None
    # built-ins still present
    assert reg.field_types.get("string") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py::test_plugin_field_types_are_registered -v --no-cov`
Expected: FAIL — `AttributeError: 'PluginRegistry' object has no attribute 'field_types'`

- [ ] **Step 3: Add the registry instance**

In `src/sunstone/plugins.py`, in `PluginRegistry.__init__` next to `self._format_handlers: list[FormatHandler] = []`:

```python
        from .field_types import FieldTypeRegistry

        self.field_types = FieldTypeRegistry()
```

- [ ] **Step 4: Classify `field_types()` during registration**

In `PluginRegistry._register`, after the existing classification branches (before the final `return`/`registered` handling), add:

```python
        if hasattr(plugin, "field_types") and callable(plugin.field_types):
            for descriptor in plugin.field_types():
                self.field_types.register(descriptor)
            registered = True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_plugins.py::test_plugin_field_types_are_registered -v --no-cov`
Expected: PASS

- [ ] **Step 6: Run the full plugins suite (regression)**

Run: `uv run pytest tests/test_plugins.py -v --no-cov`
Expected: PASS (all existing tests still green)

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat: discover plugin field types in registry"
```

---

### Task 4: `read_dataset` honors a pinned `format`

**Files:**
- Modify: `src/sunstone/dataframe.py` (`read_dataset`, ~lines 424-446)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write the failing test**

```python
def test_pinned_format_overrides_extension(tmp_path):
    """A .json file pinned as format: geojson must NOT be read as tabular JSON.

    With no geojson handler installed (Phase 1), resolution must fail loudly
    instead of silently mis-parsing via read_json.
    """
    import pytest
    from sunstone.dataframe import DataFrame

    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n"
        "  - name: World\n"
        "    slug: world\n"
        "    location: world.json\n"
        "    format: geojson\n"
    )
    (tmp_path / "world.json").write_text('{"type":"FeatureCollection","features":[]}')

    with pytest.raises(ValueError, match="geojson"):
        DataFrame.read_dataset("world", project_path=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dataframe.py::test_pinned_format_overrides_extension -v --no-cov`
Expected: FAIL — no error raised (the file is silently read by `read_json` as a tabular frame).

- [ ] **Step 3: Thread `dataset.format` into resolution**

In `src/sunstone/dataframe.py` `read_dataset`, after `dataset` is fetched and before resolving the handler (just before `format_handler = registry.find_format_reader(location, format)`), add:

```python
        # A pinned format in datasets.yaml overrides extension detection.
        if format is None and dataset.format is not None:
            format = dataset.format
```

- [ ] **Step 4: Sharpen the not-found error**

Replace the existing `raise ValueError(...)` for the missing-handler case with a message that names the format and hints at extras:

```python
        if format_handler is None:
            extension = absolute_path.suffix.lower()
            detail = f"format={format!r}" if format else f"extension={extension!r}"
            raise ValueError(
                f"No format handler found for '{absolute_path.name}' ({detail}). "
                "Install the matching extra (e.g. `pip install sunstone-py[geo]` for "
                "geojson/topojson) or check the file extension."
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_dataframe.py::test_pinned_format_overrides_extension -v --no-cov`
Expected: PASS

- [ ] **Step 6: Regression — plain reads still work**

Run: `uv run pytest tests/test_dataframe.py tests/test_datasets.py -v --no-cov`
Expected: PASS (a `.json` dataset with no pinned `format` still reads as tabular JSON.)

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_dataframe.py
git commit -m "feat: pinned datasets.yaml format overrides extension detection"
```

---

### Task 5: Full-suite regression + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest --no-cov`
Expected: PASS (entire suite green)

- [ ] **Step 2: Add a CHANGELOG entry**

Under the `[Unreleased]` section of `CHANGELOG.md`, add:

```
- Added: Extensible field value-types (registry) for structured columns.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for field-type registry"
```

---

## Self-review notes

- Spec coverage: D2 (field-type registry + plugin discovery) → Tasks 2–3. D4 (`format` field + format-driven resolution) → Tasks 1, 4. Thin `type` needs no change (it already exists as `resource_type` and is not used for resolution).
- The `validate_field_value` helper is wired into actual read/write validation in Phase 2 (where the `geometry` field type provides a real contract); Phase 1 ships the seam and its unit tests.
- No new dependencies; no `AssetKind` change in Phase 1.
