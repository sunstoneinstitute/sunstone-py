# DataFrame Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified `Metadata` container to `DataFrame` that carries dataset-level and field-level metadata through transformations to write time.

**Architecture:** New `Metadata` dataclass wraps existing `LineageMetadata` plus description, RDF, custom properties, and field metadata. DataFrame gets `.metadata` attribute with deprecation shim for `.lineage`. All internal code migrated; existing tests updated.

**Tech Stack:** Python dataclasses, pytest, sunstone-py internals

---

### Task 1: Add `Metadata` dataclass to `lineage.py`

**Files:**
- Modify: `src/sunstone/lineage.py:55-76` (make `FieldSchema.type` Optional)
- Modify: `src/sunstone/lineage.py` (add `Metadata` class after `LineageMetadata`)
- Modify: `src/sunstone/datasets.py:35-46` (handle `None` type in `_field_schema_to_dict`)
- Test: `tests/test_metadata.py` (new file)

- [ ] **Step 1: Write failing tests for Metadata and FieldSchema.type**

Create `tests/test_metadata.py`:

```python
"""Tests for the Metadata container."""

import pytest
from sunstone.lineage import FieldSchema, LineageMetadata, Metadata


class TestMetadataConstruction:
    """Tests for Metadata dataclass creation and field access."""

    def test_default_metadata(self):
        """Default Metadata has empty lineage and no other fields set."""
        m = Metadata()
        assert isinstance(m.lineage, LineageMetadata)
        assert m.description is None
        assert m.slug is None
        assert m.name is None
        assert m.rdf_prefixes is None
        assert m.custom_properties is None
        assert m.field_metadata == {}

    def test_metadata_with_all_fields(self):
        """Metadata accepts all fields at construction."""
        lineage = LineageMetadata()
        m = Metadata(
            lineage=lineage,
            description="Test dataset",
            slug="test-data",
            name="Test Data",
            rdf_prefixes={"schema": "https://schema.org/"},
            custom_properties={"schema:about": "Testing"},
            field_metadata={
                "col_a": FieldSchema(name="col_a", type="string", description="Column A"),
            },
        )
        assert m.description == "Test dataset"
        assert m.slug == "test-data"
        assert m.name == "Test Data"
        assert m.rdf_prefixes == {"schema": "https://schema.org/"}
        assert m.custom_properties == {"schema:about": "Testing"}
        assert "col_a" in m.field_metadata
        assert m.field_metadata["col_a"].description == "Column A"

    def test_metadata_field_metadata_independence(self):
        """Each Metadata instance has its own field_metadata dict."""
        m1 = Metadata()
        m2 = Metadata()
        m1.field_metadata["x"] = FieldSchema(name="x", type="string")
        assert "x" not in m2.field_metadata


class TestFieldSchemaOptionalType:
    """Tests for FieldSchema with optional type."""

    def test_field_schema_with_type(self):
        """FieldSchema works normally with an explicit type."""
        fs = FieldSchema(name="col", type="integer")
        assert fs.type == "integer"

    def test_field_schema_without_type(self):
        """FieldSchema accepts None type for deferred inference."""
        fs = FieldSchema(name="col", type=None, description="A column", unit="kg")
        assert fs.type is None
        assert fs.description == "A column"
        assert fs.unit == "kg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: FAIL — `Metadata` not importable, `FieldSchema(type=None)` rejected by type checker at runtime (type is `str` not `Optional[str]`)

- [ ] **Step 3: Make `FieldSchema.type` Optional**

In `src/sunstone/lineage.py`, change line 62:

```python
    type: Optional[str] = None
    """Data type (string, number, integer, boolean, date, datetime, array, object). None means infer at write time."""
```

In `src/sunstone/datasets.py`, update `_field_schema_to_dict` to handle `None` type:

```python
def _field_schema_to_dict(field: FieldSchema) -> dict:
    """Convert a FieldSchema to a dict for YAML serialization, omitting None values."""
    d: dict = {"name": field.name}
    if field.type is not None:
        d["type"] = field.type
    if field.constraints:
        d["constraints"] = field.constraints
    if field.description:
        d["description"] = field.description
    if field.unit:
        d["unit"] = field.unit
    if field.source:
        d["source"] = field.source
    return d
```

- [ ] **Step 4: Add `Metadata` dataclass**

In `src/sunstone/lineage.py`, add after the `LineageMetadata` class (after line ~293):

```python
@dataclass
class Metadata:
    """Unified metadata container for data objects.

    Holds lineage, dataset identity, description, RDF prefixes,
    custom properties, and per-field metadata. Not DataFrame-specific —
    can be reused for other data containers.
    """

    lineage: LineageMetadata = field(default_factory=LineageMetadata)
    """Lineage metadata tracking data provenance."""

    description: Optional[str] = None
    """Human-readable description of the dataset."""

    rdf_prefixes: Optional[Dict[str, str]] = None
    """RDF namespace prefixes for custom properties."""

    custom_properties: Optional[Dict[str, Any]] = None
    """Custom properties including RDF triples."""

    field_metadata: Dict[str, "FieldSchema"] = field(default_factory=dict)
    """Per-column metadata, keyed by column name."""

    slug: Optional[str] = None
    """Dataset slug (kebab-case identifier), used at write time."""

    name: Optional[str] = None
    """Human-readable dataset name, used at write time."""
```

- [ ] **Step 5: Export `Metadata` from `__init__.py`**

In `src/sunstone/__init__.py`, add `Metadata` to the import from `.lineage` and to `__all__`:

```python
from .lineage import (
    Contributor,
    DatasetMetadata,
    FieldSchema,
    LineageMetadata,
    Metadata,
    PackageMetadata,
    Source,
    SourceLocation,
)
```

Add `"Metadata"` to `__all__` in the `# Lineage classes` section.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS — all 5 tests green

- [ ] **Step 7: Run full test suite to check nothing broke**

Run: `uv run pytest -v`
Expected: All existing tests still pass (FieldSchema.type change is backwards compatible since all existing callers pass a type string)

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/lineage.py src/sunstone/datasets.py src/sunstone/__init__.py tests/test_metadata.py
git commit -m "Add Metadata container and make FieldSchema.type optional"
```

---

### Task 2: Integrate `Metadata` into `DataFrame.__init__` with deprecation shim

**Files:**
- Modify: `src/sunstone/dataframe.py:31-80` (`__init__` and `_get_datasets_manager`)
- Test: `tests/test_metadata.py` (add tests)

- [ ] **Step 1: Write failing tests for DataFrame metadata integration**

Add to `tests/test_metadata.py`:

```python
import warnings
import pandas as pd
import sunstone
from sunstone.lineage import LineageMetadata, Metadata


class TestDataFrameMetadataIntegration:
    """Tests for DataFrame .metadata attribute and .lineage deprecation."""

    def test_default_metadata_on_new_dataframe(self):
        """New DataFrame gets an empty Metadata container."""
        df = sunstone.DataFrame({"a": [1, 2, 3]})
        assert isinstance(df.metadata, Metadata)
        assert isinstance(df.metadata.lineage, LineageMetadata)

    def test_metadata_parameter(self):
        """DataFrame accepts a metadata parameter."""
        meta = Metadata(description="test", slug="test-slug")
        df = sunstone.DataFrame({"a": [1]}, metadata=meta)
        assert df.metadata.description == "test"
        assert df.metadata.slug == "test-slug"

    def test_lineage_parameter_wraps_in_metadata(self):
        """Passing lineage= wraps it in a Metadata container (backwards compat)."""
        lineage = LineageMetadata()
        df = sunstone.DataFrame({"a": [1]}, lineage=lineage)
        assert isinstance(df.metadata, Metadata)
        assert df.metadata.lineage is lineage

    def test_lineage_property_deprecation_warning(self):
        """Accessing df.lineage emits DeprecationWarning."""
        df = sunstone.DataFrame({"a": [1]})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = df.lineage
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_lineage_setter_deprecation_warning(self):
        """Setting df.lineage emits DeprecationWarning."""
        df = sunstone.DataFrame({"a": [1]})
        new_lineage = LineageMetadata()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df.lineage = new_lineage
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
        assert df.metadata.lineage is new_lineage

    def test_lineage_property_delegates_to_metadata(self):
        """df.lineage returns the same object as df.metadata.lineage."""
        df = sunstone.DataFrame({"a": [1]})
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert df.lineage is df.metadata.lineage
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py::TestDataFrameMetadataIntegration -v`
Expected: FAIL — DataFrame has no `metadata` attribute, `.lineage` is not a property

- [ ] **Step 3: Update `DataFrame.__init__` and add deprecation shim**

In `src/sunstone/dataframe.py`, add import at top:

```python
import warnings
from .lineage import FieldSchema, LineageMetadata, Metadata, compute_dataframe_hash
```

Replace the `__init__` body (lines ~58-80) — change the lineage handling:

```python
    def __init__(
        self,
        data: Any = None,
        lineage: Optional[LineageMetadata] = None,
        metadata: Optional[Metadata] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ):
        # Convert data to pandas DataFrame if it isn't already
        if data is None:
            self.data = pd.DataFrame(**kwargs)
        elif isinstance(data, pd.DataFrame):
            self.data = data
        else:
            self.data = pd.DataFrame(data, **kwargs)

        # Unified metadata container
        if metadata is not None:
            self.metadata = metadata
        elif lineage is not None:
            self.metadata = Metadata(lineage=lineage)
        else:
            self.metadata = Metadata()

        # Determine strict mode
        if strict is None:
            env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
            self.strict_mode = env_strict in ("1", "true")
        else:
            self.strict_mode = strict

        # Set project path
        if project_path is not None:
            self.metadata.lineage.project_path = str(Path(project_path).resolve())
        elif self.metadata.lineage.project_path is None:
            self.metadata.lineage.project_path = str(Path.cwd())
```

Add the deprecation property after `__init__`:

```python
    @property
    def lineage(self) -> LineageMetadata:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.metadata.lineage

    @lineage.setter
    def lineage(self, value: LineageMetadata) -> None:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        self.metadata.lineage = value
```

Update `_get_datasets_manager` to use `self.metadata.lineage`:

```python
    def _get_datasets_manager(self) -> DatasetsManager:
        """Get a DatasetsManager for the current project."""
        if self.metadata.lineage.project_path is None:
            raise ValueError("Project path not set")
        return DatasetsManager(self.metadata.lineage.project_path)
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: Existing tests that access `df.lineage` will emit deprecation warnings but still pass. No failures.

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_metadata.py
git commit -m "Integrate Metadata container into DataFrame with lineage deprecation shim"
```

---

### Task 3: Add convenience properties and `set_field_metadata()`

**Files:**
- Modify: `src/sunstone/dataframe.py` (add properties and method)
- Test: `tests/test_metadata.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_metadata.py`:

```python
from sunstone.lineage import FieldSchema


class TestConvenienceProperties:
    """Tests for df.description, df.rdf_prefixes, df.custom_properties."""

    def test_description_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.description is None
        df.description = "test description"
        assert df.description == "test description"
        assert df.metadata.description == "test description"

    def test_rdf_prefixes_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.rdf_prefixes is None
        df.rdf_prefixes = {"schema": "https://schema.org/"}
        assert df.rdf_prefixes == {"schema": "https://schema.org/"}
        assert df.metadata.rdf_prefixes == {"schema": "https://schema.org/"}

    def test_custom_properties_property(self):
        df = sunstone.DataFrame({"a": [1]})
        assert df.custom_properties is None
        df.custom_properties = {"schema:about": "Test"}
        assert df.custom_properties == {"schema:about": "Test"}
        assert df.metadata.custom_properties == {"schema:about": "Test"}


class TestSetFieldMetadata:
    """Tests for DataFrame.set_field_metadata()."""

    def test_set_field_metadata_creates_entry(self):
        """Setting metadata for a new column creates a FieldSchema."""
        df = sunstone.DataFrame({"enrollment": [100, 200]})
        df.set_field_metadata("enrollment", description="Total students", unit="students")
        fm = df.metadata.field_metadata["enrollment"]
        assert fm.name == "enrollment"
        assert fm.description == "Total students"
        assert fm.unit == "students"
        assert fm.type is None  # not set, will be inferred at write time

    def test_set_field_metadata_updates_existing(self):
        """Setting metadata again updates rather than replaces."""
        df = sunstone.DataFrame({"col": [1]})
        df.set_field_metadata("col", description="First")
        df.set_field_metadata("col", unit="kg")
        fm = df.metadata.field_metadata["col"]
        assert fm.description == "First"  # preserved
        assert fm.unit == "kg"  # added

    def test_set_field_metadata_chaining(self):
        """set_field_metadata returns self for chaining."""
        df = sunstone.DataFrame({"a": [1], "b": [2]})
        result = df.set_field_metadata("a", unit="m").set_field_metadata("b", unit="kg")
        assert result is df
        assert df.metadata.field_metadata["a"].unit == "m"
        assert df.metadata.field_metadata["b"].unit == "kg"

    def test_set_field_metadata_with_explicit_type(self):
        """Explicit type is stored and used instead of inference."""
        df = sunstone.DataFrame({"col": [1]})
        df.set_field_metadata("col", type="integer", description="Count")
        fm = df.metadata.field_metadata["col"]
        assert fm.type == "integer"

    def test_set_field_metadata_with_constraints(self):
        """Constraints can be set."""
        df = sunstone.DataFrame({"status": ["active"]})
        df.set_field_metadata("status", constraints={"enum": ["active", "inactive"]})
        fm = df.metadata.field_metadata["status"]
        assert fm.constraints == {"enum": ["active", "inactive"]}

    def test_set_field_metadata_with_source(self):
        """Source slug can be set."""
        df = sunstone.DataFrame({"val": [1]})
        df.set_field_metadata("val", source="input-data")
        assert df.metadata.field_metadata["val"].source == "input-data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py::TestConvenienceProperties tests/test_metadata.py::TestSetFieldMetadata -v`
Expected: FAIL — properties and method don't exist

- [ ] **Step 3: Add convenience properties to DataFrame**

In `src/sunstone/dataframe.py`, add after the `lineage` deprecation property:

```python
    @property
    def description(self) -> Optional[str]:
        """Dataset description. Delegates to metadata.description."""
        return self.metadata.description

    @description.setter
    def description(self, value: Optional[str]) -> None:
        self.metadata.description = value

    @property
    def rdf_prefixes(self) -> Optional[Dict[str, str]]:
        """RDF namespace prefixes. Delegates to metadata.rdf_prefixes."""
        return self.metadata.rdf_prefixes

    @rdf_prefixes.setter
    def rdf_prefixes(self, value: Optional[Dict[str, str]]) -> None:
        self.metadata.rdf_prefixes = value

    @property
    def custom_properties(self) -> Optional[Dict[str, Any]]:
        """Custom properties. Delegates to metadata.custom_properties."""
        return self.metadata.custom_properties

    @custom_properties.setter
    def custom_properties(self, value: Optional[Dict[str, Any]]) -> None:
        self.metadata.custom_properties = value
```

Add the required import for `Dict` if not already present (it is — `from typing import Any, List, Optional, Union` plus `Dict` is used via `lineage` imports).

- [ ] **Step 4: Add `set_field_metadata()` method**

In `src/sunstone/dataframe.py`, add after the convenience properties:

```python
    def set_field_metadata(
        self,
        column: str,
        *,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        source: Optional[str] = None,
        type: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> "DataFrame":
        """Set metadata for a column. Returns self for chaining.

        Args:
            column: Column name to annotate.
            description: Human-readable description of the field.
            unit: Unit of measure (e.g., 'kg', 'students').
            source: Slug of the input dataset this field comes from.
            type: Data type override. If None, inferred from dtype at write time.
            constraints: Optional constraints (e.g., enum values).

        Returns:
            self, for method chaining.
        """
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
        else:
            self.metadata.field_metadata[column] = FieldSchema(
                name=column,
                type=type,
                description=description,
                unit=unit,
                source=source,
                constraints=constraints,
            )
        return self
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_metadata.py
git commit -m "Add convenience properties and set_field_metadata() to DataFrame"
```

---

### Task 4: Metadata propagation through operations

**Files:**
- Modify: `src/sunstone/dataframe.py` (`_wrap_result`, `merge`, `join`, `concat`, `__repr__`)
- Test: `tests/test_metadata.py` (add tests)

- [ ] **Step 1: Write failing tests for metadata propagation**

Add to `tests/test_metadata.py`:

```python
class TestMetadataPropagation:
    """Tests for metadata flowing through pandas operations."""

    def _make_df(self):
        """Create a DataFrame with metadata set."""
        df = sunstone.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        df.metadata.description = "test data"
        df.metadata.slug = "test-slug"
        df.metadata.name = "Test Data"
        df.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        df.metadata.custom_properties = {"schema:about": "Test"}
        df.set_field_metadata("a", description="Column A", unit="m")
        df.set_field_metadata("b", description="Column B", unit="kg")
        return df

    def test_filter_preserves_metadata(self):
        """Boolean indexing preserves all metadata."""
        df = self._make_df()
        result = df[df["a"] > 1]
        assert result.metadata.description == "test data"
        assert result.metadata.slug == "test-slug"
        assert result.metadata.rdf_prefixes == {"schema": "https://schema.org/"}
        assert "a" in result.metadata.field_metadata
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_column_selection_drops_removed_field_metadata(self):
        """Selecting a subset of columns drops field metadata for removed columns."""
        df = self._make_df()
        result = df[["a"]]
        assert "a" in result.metadata.field_metadata
        assert "b" not in result.metadata.field_metadata
        # Dataset-level metadata still present
        assert result.metadata.description == "test data"

    def test_head_preserves_metadata(self):
        """head() preserves metadata."""
        df = self._make_df()
        result = df.head(2)
        assert result.metadata.description == "test data"
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_merge_uses_left_metadata(self):
        """Merge uses left DataFrame's metadata as base."""
        left = sunstone.DataFrame({"key": [1], "val_l": [10]})
        left.metadata.description = "left data"
        left.set_field_metadata("val_l", unit="m")

        right = sunstone.DataFrame({"key": [1], "val_r": [20]})
        right.set_field_metadata("val_r", unit="kg")

        result = left.merge(right, on="key")
        assert result.metadata.description == "left data"
        assert result.metadata.field_metadata["val_l"].unit == "m"
        # Right field metadata is NOT carried (left is the base)
        assert "val_r" not in result.metadata.field_metadata

    def test_concat_uses_first_metadata(self):
        """Concat uses first DataFrame's metadata as base."""
        df1 = sunstone.DataFrame({"a": [1]})
        df1.metadata.description = "first"
        df1.set_field_metadata("a", unit="m")

        df2 = sunstone.DataFrame({"a": [2]})
        df2.metadata.description = "second"

        result = df1.concat([df2])
        assert result.metadata.description == "first"
        assert result.metadata.field_metadata["a"].unit == "m"

    def test_join_uses_left_metadata(self):
        """Join uses left DataFrame's metadata as base."""
        left = sunstone.DataFrame({"val": [1]}, index=[0])
        left.metadata.description = "left"

        right = sunstone.DataFrame({"other": [2]}, index=[0])

        # Need to set index properly for join
        result = left.join(right)
        assert result.metadata.description == "left"

    def test_metadata_is_independent_after_operation(self):
        """Modifying metadata on result doesn't affect original."""
        df = self._make_df()
        result = df.head(2)
        result.metadata.description = "modified"
        assert df.metadata.description == "test data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py::TestMetadataPropagation -v`
Expected: FAIL — `_wrap_result` doesn't copy metadata fields

- [ ] **Step 3: Update `_wrap_result()` to propagate metadata**

In `src/sunstone/dataframe.py`, replace the `_wrap_result` method:

```python
    def _wrap_result(self, result: Any) -> Any:
        """Wrap a pandas result in a Sunstone DataFrame if applicable.

        Copies all metadata, dropping field_metadata for columns no longer present.
        """
        if isinstance(result, pd.DataFrame):
            new_field_meta = {
                k: v for k, v in self.metadata.field_metadata.items() if k in result.columns
            }
            new_metadata = Metadata(
                lineage=LineageMetadata(
                    sources=self.metadata.lineage.sources.copy(),
                    project_path=self.metadata.lineage.project_path,
                ),
                description=self.metadata.description,
                rdf_prefixes=self.metadata.rdf_prefixes,
                custom_properties=self.metadata.custom_properties,
                field_metadata=new_field_meta,
                slug=self.metadata.slug,
                name=self.metadata.name,
            )
            return DataFrame(
                data=result,
                metadata=new_metadata,
                strict=self.strict_mode,
            )
        return result
```

- [ ] **Step 4: Update `merge()` to use metadata**

```python
    def merge(self, right: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Merge with another Sunstone DataFrame, combining lineage."""
        merged_data = pd.merge(self.data, right.data, **kwargs)
        merged_lineage = self.metadata.lineage.merge(right.metadata.lineage)

        new_field_meta = {
            k: v for k, v in self.metadata.field_metadata.items() if k in merged_data.columns
        }
        new_metadata = Metadata(
            lineage=merged_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=merged_data, metadata=new_metadata, strict=self.strict_mode)
```

- [ ] **Step 5: Update `join()` to use metadata**

```python
    def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Join with another Sunstone DataFrame, combining lineage."""
        joined_data = self.data.join(other.data, **kwargs)
        joined_lineage = self.metadata.lineage.merge(other.metadata.lineage)

        new_field_meta = {
            k: v for k, v in self.metadata.field_metadata.items() if k in joined_data.columns
        }
        new_metadata = Metadata(
            lineage=joined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=joined_data, metadata=new_metadata, strict=self.strict_mode)
```

- [ ] **Step 6: Update `concat()` to use metadata**

```python
    def concat(self, others: List["DataFrame"], **kwargs: Any) -> "DataFrame":
        """Concatenate with other Sunstone DataFrames, combining lineage."""
        all_dfs = [self.data] + [df.data for df in others]
        concatenated_data = pd.concat(all_dfs, **kwargs)

        combined_lineage = self.metadata.lineage
        for other in others:
            combined_lineage = combined_lineage.merge(other.metadata.lineage)

        new_field_meta = {
            k: v
            for k, v in self.metadata.field_metadata.items()
            if k in concatenated_data.columns
        }
        new_metadata = Metadata(
            lineage=combined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=concatenated_data, metadata=new_metadata, strict=self.strict_mode)
```

- [ ] **Step 7: Update `__repr__` to use metadata**

```python
    def __repr__(self) -> str:
        """String representation of the DataFrame."""
        lineage_info = f"\n\nLineage: {len(self.metadata.lineage.sources)} source(s)"
        return repr(self.data) + lineage_info
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (existing tests use `df.lineage` which goes through the deprecation shim)

- [ ] **Step 10: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_metadata.py
git commit -m "Propagate metadata through DataFrame operations"
```

---

### Task 5: Migrate internal callers from `.lineage` to `.metadata.lineage`

**Files:**
- Modify: `src/sunstone/dataframe.py` (read methods, `to_csv`)

This task updates all internal code in `dataframe.py` that accesses `self.lineage` directly (not through the property) to use `self.metadata.lineage`. These are internal calls that should not emit deprecation warnings.

Note: After Task 2, `self.lineage` is a property that emits warnings. Internal code that previously set `self.lineage = ...` in `__init__` was already fixed in Task 2. This task covers the remaining references in class methods (`read_csv`, `read_excel`, `read_json`, `read_dataset`, `to_csv`).

- [ ] **Step 1: Update `read_dataset` classmethod**

In `read_dataset` (around line 184-194), change:

```python
        # Create lineage metadata
        lineage = LineageMetadata(project_path=str(manager.project_path))
        lineage.add_source(dataset)

        # ...

        # Return wrapped DataFrame
        return cls(data=df, lineage=lineage, strict=strict, project_path=project_path)
```

To:

```python
        # Create metadata with lineage
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)

        # ...

        # Return wrapped DataFrame
        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)
```

- [ ] **Step 2: Update `read_csv` classmethod**

Same pattern — change the lineage creation block (around lines 299-309):

```python
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)

        from .session import DatasetRead, get_session
        get_session().record_read(DatasetRead(slug=dataset.slug))

        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)
```

- [ ] **Step 3: Update `read_excel` classmethod**

Same pattern (around lines 412-422):

```python
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)

        from .session import DatasetRead, get_session
        get_session().record_read(DatasetRead(slug=dataset.slug))

        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)
```

- [ ] **Step 4: Update `read_json` classmethod**

Same pattern (the method added earlier in this session):

```python
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)

        from .session import DatasetRead, get_session
        get_session().record_read(DatasetRead(slug=dataset.slug))

        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)
```

- [ ] **Step 5: Update `to_csv` — lineage references**

In `to_csv`, change `self.lineage` references to `self.metadata.lineage`. Find the line:

```python
        manager.update_output_lineage(
            slug=dataset.slug,
            lineage=self.lineage,
```

Change to:

```python
        manager.update_output_lineage(
            slug=dataset.slug,
            lineage=self.metadata.lineage,
```

Also find `self.project_path` references in `to_csv` (inside the `track=False` branch). The `project_path` was previously accessed as `self.lineage.project_path` — update to `self.metadata.lineage.project_path`:

```python
            registry = PluginRegistry.get(
                Path(self.metadata.lineage.project_path)
                if self.metadata.lineage.project_path is not None
                else None
            )
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass. No deprecation warnings from internal code.

- [ ] **Step 7: Verify no deprecation warnings from internal operations**

Run: `uv run pytest -W error::DeprecationWarning tests/test_dataframe.py -v`
Expected: All pass — internal code no longer triggers the deprecation shim. (Note: tests that explicitly access `df.lineage` for assertions will fail here — that's expected and will be addressed in Task 7.)

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/dataframe.py
git commit -m "Migrate internal DataFrame code from .lineage to .metadata.lineage"
```

---

### Task 6: Write-time field schema merge and to_csv metadata flow

**Files:**
- Modify: `src/sunstone/dataframe.py` (`_infer_field_schema` → `_build_field_schema`, `to_csv`)
- Modify: `src/sunstone/datasets.py` (`add_output_dataset`, `update_output_dataset`)
- Test: `tests/test_metadata.py` (add tests)

- [ ] **Step 1: Write failing tests for field schema merge**

Add to `tests/test_metadata.py`:

```python
class TestBuildFieldSchema:
    """Tests for write-time field schema merge."""

    def test_inferred_only(self):
        """Without field metadata, all types are inferred from dtypes."""
        df = sunstone.DataFrame({"i": [1], "f": [1.5], "s": ["a"], "b": [True]})
        schema = df._build_field_schema()
        types = {f.name: f.type for f in schema}
        assert types["i"] == "integer"
        assert types["f"] == "number"
        assert types["s"] == "string"
        assert types["b"] == "boolean"

    def test_explicit_overrides_inferred(self):
        """Explicit field metadata takes precedence over inference."""
        df = sunstone.DataFrame({"val": [1]})
        df.set_field_metadata("val", type="number", description="A value", unit="kg")
        schema = df._build_field_schema()
        assert len(schema) == 1
        assert schema[0].type == "number"  # explicit, not "integer"
        assert schema[0].description == "A value"
        assert schema[0].unit == "kg"

    def test_partial_annotation(self):
        """Annotated and unannotated columns both get schemas."""
        df = sunstone.DataFrame({"annotated": [1], "plain": ["x"]})
        df.set_field_metadata("annotated", description="Important", unit="m")
        schema = df._build_field_schema()
        by_name = {f.name: f for f in schema}
        assert by_name["annotated"].description == "Important"
        assert by_name["annotated"].type == "integer"  # inferred, since type=None
        assert by_name["plain"].type == "string"
        assert by_name["plain"].description is None

    def test_explicit_type_none_gets_inferred(self):
        """FieldSchema with type=None gets type inferred from dtype."""
        df = sunstone.DataFrame({"col": [42]})
        df.set_field_metadata("col", description="Count")
        # type is None in field_metadata
        assert df.metadata.field_metadata["col"].type is None
        schema = df._build_field_schema()
        assert schema[0].type == "integer"
        assert schema[0].description == "Count"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata.py::TestBuildFieldSchema -v`
Expected: FAIL — `_build_field_schema` doesn't exist

- [ ] **Step 3: Replace `_infer_field_schema` with `_build_field_schema` and `_infer_dtype`**

In `src/sunstone/dataframe.py`, replace the `_infer_field_schema` method with:

```python
    def _infer_dtype(self, col: str) -> str:
        """Infer the dataset type string for a column from its pandas dtype."""
        dtype = self.data[col].dtype
        if pd.api.types.is_integer_dtype(dtype):
            return "integer"
        elif pd.api.types.is_float_dtype(dtype):
            return "number"
        elif pd.api.types.is_bool_dtype(dtype):
            return "boolean"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            return "datetime"
        return "string"

    def _build_field_schema(self) -> List[FieldSchema]:
        """Merge explicit field metadata with dtype-inferred schema.

        For each column: if explicit field metadata exists, use it (inferring
        type from dtype if type is None). Otherwise, create a minimal
        FieldSchema with name and inferred type.
        """
        fields = []
        for col in self.data.columns:
            col_str = str(col)
            explicit = self.metadata.field_metadata.get(col_str)
            if explicit:
                if explicit.type is None:
                    # Clone with inferred type — don't mutate the original
                    fields.append(
                        FieldSchema(
                            name=explicit.name,
                            type=self._infer_dtype(col_str),
                            description=explicit.description,
                            unit=explicit.unit,
                            source=explicit.source,
                            constraints=explicit.constraints,
                        )
                    )
                else:
                    fields.append(explicit)
            else:
                fields.append(FieldSchema(name=col_str, type=self._infer_dtype(col_str)))
        return fields
```

- [ ] **Step 4: Update `to_csv` to use `_build_field_schema` and metadata fallbacks**

In `to_csv`, update the slug/name fallback logic. Change the method signature to make slug and name optional with metadata fallback. Find the section that auto-registers (around the relaxed mode block):

Change:
```python
                if slug is None or name is None:
                    raise ValueError(
                        "In relaxed mode, 'slug' and 'name' are required "
                        "when writing to an unregistered output location."
                    )
```

To:
```python
                # Fall back to metadata for slug/name
                effective_slug = slug or self.metadata.slug
                effective_name = name or self.metadata.name
                if effective_slug is None or effective_name is None:
                    raise ValueError(
                        "In relaxed mode, 'slug' and 'name' are required "
                        "when writing to an unregistered output location. "
                        "Set them via to_csv() parameters or df.metadata.slug/name."
                    )
```

Then update the call to `add_output_dataset` to pass metadata:
```python
                fields = self._build_field_schema()
                dataset = manager.add_output_dataset(
                    name=effective_name,
                    slug=effective_slug,
                    location=location,
                    fields=fields,
                    description=self.metadata.description,
                    rdf_prefixes=self.metadata.rdf_prefixes,
                    custom_properties=self.metadata.custom_properties,
                )
```

Also replace the `self._infer_field_schema()` call with `self._build_field_schema()` (there should be exactly one reference).

- [ ] **Step 5: Update `DatasetsManager.add_output_dataset`**

In `src/sunstone/datasets.py`, update the signature and body:

```python
    def add_output_dataset(
        self,
        name: str,
        slug: str,
        location: str,
        fields: List[FieldSchema],
        description: Optional[str] = None,
        rdf_prefixes: Optional[Dict[str, str]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> DatasetMetadata:
        """
        Add a new output dataset to datasets.yaml.

        Args:
            name: Human-readable name.
            slug: Kebab-case identifier.
            location: File path for the output.
            fields: List of field schemas.
            description: Optional dataset description.
            rdf_prefixes: Optional RDF namespace prefixes.
            custom_properties: Optional custom properties (RDF-style keys).

        Returns:
            The newly created DatasetMetadata.

        Raises:
            DatasetValidationError: If a dataset with this slug already exists.
        """
        if self.find_dataset_by_slug(slug, "output"):
            raise DatasetValidationError(f"Output dataset with slug '{slug}' already exists")

        dataset_data = {
            "name": name,
            "slug": slug,
            "location": location,
            "fields": [_field_schema_to_dict(field) for field in fields],
        }
        if description is not None:
            dataset_data["description"] = description
        if rdf_prefixes is not None:
            dataset_data["rdfPrefixes"] = rdf_prefixes
        if custom_properties is not None:
            for key, value in custom_properties.items():
                dataset_data[key] = value

        self._data["outputs"].append(dataset_data)
        self._save()
        return self._parse_dataset(dataset_data, "output")
```

- [ ] **Step 6: Update `DatasetsManager.update_output_dataset`**

```python
    def update_output_dataset(
        self,
        slug: str,
        fields: Optional[List[FieldSchema]] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        rdf_prefixes: Optional[Dict[str, str]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> DatasetMetadata:
        """
        Update an existing output dataset.

        Args:
            slug: The slug of the dataset to update.
            fields: Optional new field schema.
            location: Optional new location.
            description: Optional new description.
            rdf_prefixes: Optional new RDF namespace prefixes.
            custom_properties: Optional custom properties to merge.

        Returns:
            The updated DatasetMetadata.

        Raises:
            DatasetNotFoundError: If the dataset doesn't exist.
        """
        for i, dataset_data in enumerate(self._data["outputs"]):
            if dataset_data["slug"] == slug:
                if fields is not None:
                    dataset_data["fields"] = [_field_schema_to_dict(field) for field in fields]
                if location is not None:
                    dataset_data["location"] = location
                if description is not None:
                    dataset_data["description"] = description
                if rdf_prefixes is not None:
                    dataset_data["rdfPrefixes"] = rdf_prefixes
                if custom_properties is not None:
                    for key, value in custom_properties.items():
                        dataset_data[key] = value

                self._save()
                return self._parse_dataset(dataset_data, "output")

        raise DatasetNotFoundError(f"Output dataset with slug '{slug}' not found")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata.py -v`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add src/sunstone/dataframe.py src/sunstone/datasets.py tests/test_metadata.py
git commit -m "Add write-time field schema merge and metadata flow to DatasetsManager"
```

---

### Task 7: Integration test and migrate existing test assertions

**Files:**
- Create: `tests/test_metadata.py` (add integration test)
- Modify: `tests/test_dataframe.py` (migrate `.lineage` → `.metadata.lineage`)
- Modify: `tests/test_lineage_persistence.py` (migrate `.lineage` → `.metadata.lineage`)
- Modify: `tests/test_pandas_compatibility.py` (migrate `.lineage` → `.metadata.lineage`)
- Modify: `tests/test_dataframe_coverage.py` (migrate `.lineage` → `.metadata.lineage`)
- Modify: `tests/test_remaining_coverage.py` (migrate `.lineage` → `.metadata.lineage`)

- [ ] **Step 1: Write integration test**

Add to `tests/test_metadata.py`:

```python
from pathlib import Path
from ruamel.yaml import YAML


class TestMetadataIntegration:
    """End-to-end test: read -> annotate -> write -> verify datasets.yaml."""

    def test_full_metadata_flow(self, project_path: Path, tmp_path: Path):
        """Metadata set on DataFrame flows through to datasets.yaml on write."""
        import shutil

        # Copy test project to tmp so we can write without affecting fixtures
        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)

        # Read input
        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )

        # Transform
        result = df[["Member State", "ISO Code"]].head(5)

        # Set metadata
        result.metadata.slug = "top-five-members"
        result.metadata.name = "Top Five Members"
        result.metadata.description = "First five UN member states"
        result.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
        result.metadata.custom_properties = {"schema:about": "United Nations"}
        result.set_field_metadata("Member State", description="Country name")
        result.set_field_metadata("ISO Code", description="ISO 3166-1 alpha-3", source="official-un-member-states")

        # Write
        output_path = test_project / "outputs" / "top_five.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), index=False)

        # Verify datasets.yaml
        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)

        # Find the output
        output = None
        for o in data["outputs"]:
            if o["slug"] == "top-five-members":
                output = o
                break
        assert output is not None, "Output dataset not found in datasets.yaml"

        assert output["name"] == "Top Five Members"
        assert output["description"] == "First five UN member states"
        assert output["rdfPrefixes"] == {"schema": "https://schema.org/"}
        assert output["schema:about"] == "United Nations"

        # Check fields
        fields_by_name = {f["name"]: f for f in output["fields"]}
        assert fields_by_name["Member State"]["description"] == "Country name"
        assert fields_by_name["ISO Code"]["description"] == "ISO 3166-1 alpha-3"
        assert fields_by_name["ISO Code"]["source"] == "official-un-member-states"

        # Check lineage
        assert "lineage" in output
        assert "sources" in output["lineage"]

    def test_to_csv_slug_name_from_metadata(self, project_path: Path, tmp_path: Path):
        """to_csv uses metadata slug/name when not passed as parameters."""
        import shutil

        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )
        result = df.head(3)
        result.metadata.slug = "meta-slug"
        result.metadata.name = "Meta Name"

        output_path = test_project / "outputs" / "meta_test.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), index=False)

        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next(o for o in data["outputs"] if o["slug"] == "meta-slug")
        assert output["name"] == "Meta Name"

    def test_to_csv_params_override_metadata(self, project_path: Path, tmp_path: Path):
        """Explicit to_csv params override metadata values."""
        import shutil

        test_project = tmp_path / "project"
        shutil.copytree(project_path, test_project)

        df = sunstone.DataFrame.read_csv(
            "inputs/official_un_member_states_raw.csv",
            project_path=test_project,
            strict=False,
        )
        result = df.head(3)
        result.metadata.slug = "meta-slug"
        result.metadata.name = "Meta Name"

        output_path = test_project / "outputs" / "override_test.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(str(output_path), slug="param-slug", name="Param Name", index=False)

        yaml = YAML()
        with open(test_project / "datasets.yaml") as f:
            data = yaml.load(f)

        output = next(o for o in data["outputs"] if o["slug"] == "param-slug")
        assert output["name"] == "Param Name"
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_metadata.py::TestMetadataIntegration -v`
Expected: PASS (or identify any remaining issues in `to_csv` flow)

- [ ] **Step 3: Migrate `tests/test_dataframe.py`**

Replace all `df.lineage` with `df.metadata.lineage` throughout the file. The specific lines to change (from grep output):

- Line 27: `df.lineage.sources` → `df.metadata.lineage.sources`
- Line 40: `filtered.lineage.sources` and `df.lineage.sources` → both `.metadata.lineage.sources`
- Lines 54-55: `members1.lineage.sources` and `members2.lineage.sources`
- Lines 72, 85: `df.lineage.sources`
- Line 95: `df.lineage.sources[0].slug`
- Line 154: `merged.lineage.sources`
- Line 160: `merged.lineage.get_licenses()`
- Line 182: `processed_df.lineage.to_dict()`
- Lines 225, 227, 240, 276: `df.lineage.sources`
- Lines 485-486: `df.lineage.sources`

Use find-and-replace: `.lineage.` → `.metadata.lineage.` (careful not to catch string literals or comments).

- [ ] **Step 4: Migrate `tests/test_lineage_persistence.py`**

Replace all `df.lineage` / `result.lineage` with `.metadata.lineage`:

- Line 22: `hasattr(result, "lineage")` → `hasattr(result, "metadata")`
- Line 23: `result.lineage.sources` → `result.metadata.lineage.sources`, same for `df.lineage.sources`
- Line 35: same pattern
- Line 46: same pattern
- Lines 54, 59: `df.lineage.sources` → `df.metadata.lineage.sources`

- [ ] **Step 5: Migrate `tests/test_pandas_compatibility.py`**

- Lines 113, 134, 138, 158, 244, 291: `.lineage.sources` → `.metadata.lineage.sources`

- [ ] **Step 6: Migrate `tests/test_dataframe_coverage.py`**

- Line 65: `df.lineage.project_path = None` → `df.metadata.lineage.project_path = None`

- [ ] **Step 7: Migrate `tests/test_remaining_coverage.py`**

- Line 104: `df.lineage.sources` → `df.metadata.lineage.sources`

- [ ] **Step 8: Run full test suite with deprecation warnings as errors**

Run: `uv run pytest -W error::DeprecationWarning -v`
Expected: All tests pass — no internal or test code triggers the deprecation shim

- [ ] **Step 9: Commit**

```bash
git add tests/test_metadata.py tests/test_dataframe.py tests/test_lineage_persistence.py tests/test_pandas_compatibility.py tests/test_dataframe_coverage.py tests/test_remaining_coverage.py
git commit -m "Add integration tests and migrate test assertions to .metadata.lineage"
```

---

### Task 8: Update CHANGELOG, docs, and exports

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md` (remove stale `apply_operation` if still referenced)
- Modify: `README.md` (update API reference, remove `apply_operation`, add metadata docs)

- [ ] **Step 1: Add CHANGELOG entry**

Add to the `[Unreleased]` section of `CHANGELOG.md`:

```markdown
- Added: Metadata container for DataFrame with description, RDF prefixes, custom properties, and field-level metadata
- Added: `set_field_metadata()` method for annotating DataFrame columns with description, unit, source
- Added: `read_json()` to sunstone.pandas module
- Changed: `FieldSchema.type` is now optional (None means infer at write time)
- Deprecated: `DataFrame.lineage` property — use `DataFrame.metadata.lineage` instead
```

- [ ] **Step 2: Update README.md API reference**

Remove the `apply_operation` references (lines ~236-239 and ~298).

Add `read_json` to the pandas Module section:
```markdown
- `read_json(filepath, project_path, strict=False, **kwargs)`: Read JSON with lineage
```

Add a new section after "Direct DataFrame API":

```markdown
### DataFrame Metadata

Set metadata on DataFrames that flows through to `datasets.yaml` on write:

- `df.metadata.slug`: Dataset slug (used at write time)
- `df.metadata.name`: Dataset name (used at write time)
- `df.metadata.description`: Dataset description
- `df.metadata.rdf_prefixes`: RDF namespace prefixes
- `df.metadata.custom_properties`: Custom properties (RDF-style)
- `df.set_field_metadata(column, *, description, unit, source, type, constraints)`: Annotate a column
```

Update the DataFrame Class section to include:
```markdown
- `set_field_metadata(column, **kwargs)`: Annotate column metadata
- `.metadata`: Access unified metadata container
```

And remove `apply_operation` from the list.

- [ ] **Step 3: Update AGENTS.md**

Remove `apply_operation` from the usage example if present. Add `read_json` mention if the pandas API section exists.

- [ ] **Step 4: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md AGENTS.md
git commit -m "Update docs: add metadata API, read_json, remove stale apply_operation"
```
