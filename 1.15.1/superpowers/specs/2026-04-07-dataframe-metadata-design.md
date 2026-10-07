# DataFrame Metadata Design

**Date**: 2026-04-07
**Status**: Approved

## Problem

There is no way to set metadata on a `sunstone.pandas.DataFrame` instance. Dataset-level metadata (description, RDF properties, custom properties) and field-level metadata (description, unit, source) can only be expressed in `datasets.yaml`, but cannot be attached to a DataFrame in memory and carried through transformations to write time.

## Design

### Metadata Container

A new `Metadata` dataclass in `lineage.py` that serves as a unified metadata container for data objects. It is not DataFrame-specific and can be reused for other data containers in the future.

```python
@dataclass
class Metadata:
    """Unified metadata container for data objects."""

    lineage: LineageMetadata = field(default_factory=LineageMetadata)
    description: Optional[str] = None
    rdf_prefixes: Optional[Dict[str, str]] = None
    custom_properties: Optional[Dict[str, Any]] = None
    field_metadata: Dict[str, FieldSchema] = field(default_factory=dict)

    # Dataset identity (used at write time)
    slug: Optional[str] = None
    name: Optional[str] = None
```

- `field_metadata` is keyed by column name, values are the existing `FieldSchema` dataclass (which already has description, unit, source, constraints).
- `slug` and `name` live here so they can be set early rather than only at `to_csv()` time.
- `lineage` defaults to an empty `LineageMetadata`, preserving current behavior.

### DataFrame Integration

#### New `.metadata` attribute

`DataFrame.__init__` accepts an optional `metadata` parameter. For backwards compatibility, the existing `lineage` parameter is still accepted and wrapped into a `Metadata` container.

```python
def __init__(self, data=None, lineage=None, metadata=None, strict=None,
             project_path=None, **kwargs):
    if metadata is not None:
        self.metadata = metadata
    elif lineage is not None:
        self.metadata = Metadata(lineage=lineage)
    else:
        self.metadata = Metadata()
    # ... rest unchanged
```

#### Deprecation shim for `.lineage`

A property that delegates to `.metadata.lineage` with a `DeprecationWarning`:

```python
@property
def lineage(self) -> LineageMetadata:
    warnings.warn("DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
                   DeprecationWarning, stacklevel=2)
    return self.metadata.lineage

@lineage.setter
def lineage(self, value):
    warnings.warn("DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
                   DeprecationWarning, stacklevel=2)
    self.metadata.lineage = value
```

#### Convenience properties

Thin property wrappers on DataFrame for ergonomic access to common metadata fields:

- `df.description` delegates to `df.metadata.description`
- `df.rdf_prefixes` delegates to `df.metadata.rdf_prefixes`
- `df.custom_properties` delegates to `df.metadata.custom_properties`

These are pure convenience — `df.metadata.description` always works too.

#### `set_field_metadata()` method

```python
def set_field_metadata(self, column: str, *, description: str | None = None,
                       unit: str | None = None, source: str | None = None,
                       type: str | None = None,
                       constraints: dict | None = None) -> "DataFrame":
    """Set metadata for a column. Returns self for chaining."""
    existing = self.metadata.field_metadata.get(column)
    if existing:
        if description is not None: existing.description = description
        if unit is not None: existing.unit = unit
        if source is not None: existing.source = source
        if type is not None: existing.type = type
        if constraints is not None: existing.constraints = constraints
    else:
        self.metadata.field_metadata[column] = FieldSchema(
            name=column, type=type,
            description=description, unit=unit,
            source=source, constraints=constraints,
        )
    return self
```

Returns `self` for chaining: `df.set_field_metadata("a", unit="kg").set_field_metadata("b", unit="m")`

### Metadata Propagation

All metadata propagates through pandas operations via `_wrap_result()`. Field metadata for columns that no longer exist in the result is silently dropped.

```python
def _wrap_result(self, result):
    if isinstance(result, pd.DataFrame):
        new_field_meta = {k: v for k, v in self.metadata.field_metadata.items()
                         if k in result.columns}
        new_metadata = Metadata(
            lineage=LineageMetadata(
                sources=self.metadata.lineage.sources.copy(),
                project_path=self.metadata.lineage.project_path),
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=result, metadata=new_metadata, strict=self.strict_mode)
    return result
```

The same approach applies to `merge()`, `join()`, and `concat()` — metadata from the left/first DataFrame is used as the base, with lineage merged from all sources as it is today.

### Write-time Field Schema Merge

A new `_build_field_schema()` replaces the current `_infer_field_schema()`. Explicit field metadata wins; inferred dtype fills gaps for unannotated columns.

```python
def _build_field_schema(self) -> List[FieldSchema]:
    """Merge explicit field metadata with dtype-inferred schema."""
    fields = []
    for col in self.data.columns:
        inferred_type = self._infer_dtype(col)
        explicit = self.metadata.field_metadata.get(str(col))
        if explicit:
            if explicit.type is None:
                explicit = FieldSchema(name=explicit.name, type=inferred_type,
                    description=explicit.description, unit=explicit.unit,
                    source=explicit.source, constraints=explicit.constraints)
            fields.append(explicit)
        else:
            fields.append(FieldSchema(name=str(col), type=inferred_type))
    return fields
```

The existing dtype-to-type mapping logic moves into a `_infer_dtype(col)` helper extracted from the current `_infer_field_schema()`.

Note: `FieldSchema.type` must change from `str` to `Optional[str]` to support the case where a user sets field metadata (description, unit, etc.) without specifying the type, letting it be inferred at write time.

### Changes to `to_csv()`

- `slug` and `name` parameters become optional, falling back to `self.metadata.slug` / `self.metadata.name`.
- `description`, `rdf_prefixes`, `custom_properties` flow from metadata to `add_output_dataset()` / `update_output_dataset()`.
- Explicit `to_csv()` parameters override metadata values (backwards compatible).
- `_infer_field_schema()` replaced by `_build_field_schema()`.

### Changes to DatasetsManager

`add_output_dataset()` and `update_output_dataset()` gain optional parameters: `description`, `rdf_prefixes`, `custom_properties`.

- `description` is written as a `description` key on the dataset entry.
- `rdf_prefixes` is written as a `rdfPrefixes` key.
- `custom_properties` entries are written as top-level keys on the dataset entry (RDF-style, e.g. `schema:about`).
- `None` means "don't touch" on update; only explicitly provided values are written/overwritten.
- The read side (`_parse_dataset`) already handles all these fields, so round-tripping works without changes.

### Internal callers

All internal code that currently passes `lineage=` to the `DataFrame` constructor or accesses `df.lineage` directly (read methods, merge, join, concat, `_wrap_result`, `to_csv`) must be updated to use `df.metadata.lineage`. These are internal and do not need deprecation warnings.

## Usage Example

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

df = pd.read_csv('input.csv', project_path=PROJECT_PATH)
result = df[df['enrollment'] > 100].groupby('district').sum()

# Set output identity and metadata
result.metadata.slug = "enrollment-by-district"
result.metadata.name = "Enrollment by District"
result.metadata.description = "Aggregated school enrollment figures by district"
result.metadata.rdf_prefixes = {"schema": "https://schema.org/"}
result.metadata.custom_properties = {"schema:about": "Education"}

# Annotate columns
result.set_field_metadata("enrollment",
    description="Total enrolled students in district",
    unit="students",
    source="school-data")
result.set_field_metadata("district",
    description="School district name")

# Write — slug/name come from metadata
result.to_csv('outputs/enrollment_by_district.csv', index=False)
```

Old-style usage still works — `to_csv()` params override metadata:

```python
result.to_csv('outputs/result.csv', slug='my-output', name='My Output', index=False)
```

## Testing Strategy

- Unit tests for `Metadata` dataclass construction and field access.
- Unit tests for `set_field_metadata()` — create, update, chaining.
- Propagation tests: metadata survives filter, groupby, merge, join, concat; field metadata for dropped columns is removed.
- Write-time tests: `_build_field_schema()` merges explicit + inferred correctly.
- Integration test: full read -> annotate -> write -> verify datasets.yaml output.
- Deprecation tests: accessing `df.lineage` emits `DeprecationWarning`.
- Backwards compatibility: existing `to_csv(slug=, name=)` call pattern still works.
