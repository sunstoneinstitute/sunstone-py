# API Reference

Complete API documentation for sunstone-py.

## Project Path Configuration

```python
import sunstone
```

`read_csv`, `read_excel`, `read_json`, `read_dataset`, and the `DataFrame` constructor look up paths against a project directory containing `datasets.yaml`. The `project_path` argument is optional — when omitted, these functions fall back to the process-wide configured value, then to `Path.cwd()`.

The configured value is stored in a `contextvars.ContextVar`, so it is safe across threads and async tasks.

### `sunstone.set_project_path(path)`

Set the default project path for the current context.

**Parameters:**

- `path` (str | Path): Project directory.

**Returns:** `Path` — the resolved absolute path.

**Example:**

```python
import sunstone
from pathlib import Path

sunstone.set_project_path(Path(__file__).parent)
```

---

### `sunstone.get_project_path()`

Return the configured default project path, or `Path.cwd()` if none is set.

**Returns:** `Path`

---

### `sunstone.clear_project_path()`

Clear any previously configured default project path.

**Returns:** `None`

---

### `sunstone.use_project_path(path)`

Context manager that temporarily sets the default project path.

**Parameters:**

- `path` (str | Path): Project directory.

**Yields:** `Path` — the resolved absolute path.

**Example:**

```python
with sunstone.use_project_path('/path/to/other/project'):
    df = pd.read_csv('inputs/data.csv')
# previous default restored here
```

## Asset Envelope

`Asset` is the uniform container for every kind of data sunstone handles
— tabular, raster, n-D array, tile pyramid. `sunstone.DataFrame` is a
thin facade over an `Asset` of `kind=AssetKind.TABULAR`; the two record
identical lineage.

```python
from sunstone import Asset, AssetKind, ComponentSchema, IncompatibleAssetKindError
```

### `sunstone.read(path, *, format=None, kind=None, metadata=None, extras=None, **kwargs)`

Read any registered format into an `Asset`.

**Parameters:**

- `path` (str): Path or URL to read.
- `format` (str | None): Format override (`'csv'`, `'parquet'`, `'zarr'`,
  `'hdf5'`, `'pdf'`, `'docx'`, a canonical MIME like `'application/pdf'`,
  …). Auto-detected if not provided.
- `kind` (AssetKind | None): When supplied, overrides the kind on the
  returned `Asset`. Use this when reconstructing an asset from a
  catalog row where the catalog is authoritative.
- `metadata` (Metadata | None): When supplied, fully replaces the
  handler-produced `metadata`. Use this for catalog-driven
  reconstruction where the canonical metadata lives outside the file.
- `extras` (dict | None): When supplied, fully replaces the
  handler-produced `extras` dict.
- `**kwargs`: Handler-specific keyword arguments.

**Returns:** `Asset`

**Dispatch order:**

1. Explicit `kind=` / `format=` arguments.
2. The `format:` field on the matching `datasets.yaml` entry (resolved by location).
3. The path itself — directory paths route to the `StoreFormatHandler`
   registry; single-file paths consult store handlers first (so HDF5 /
   NetCDF-4 can claim them), then fall through to the tabular stream
   pipeline.

**Example:**

```python
import sunstone as ss
from sunstone.lineage import Metadata

asset = ss.read('inputs/era5_2024.zarr')
assert asset.kind is ss.AssetKind.ARRAY
arrays = asset.as_array()  # dict[str, numpy.ndarray]

# Catalog-driven reconstruction: override handler-produced fields.
pdf_asset = ss.read(
    'inputs/report.pdf',
    metadata=Metadata(slug='q4-report', name='Q4 Report'),
    extras={'media_type': 'application/pdf', 'origin': 'catalog'},
)
```

---

### `sunstone.write(asset, path, *, format=None, **kwargs)`

Write an `Asset` to `path`. Dispatches via the plugin registry.

**Parameters:**

- `asset` (Asset): Asset to write.
- `path` (str): Destination path or URL.
- `format` (str | None): Format override.
- `**kwargs`: Handler-specific keyword arguments.

**Returns:** None

**Raises:**

- `IncompatibleAssetKindError`: If the selected handler does not support
  `asset.kind`.
- `ValueError`: If no handler matches `path` and `format`.

---

### `AssetKind`

Closed enum of supported asset kinds.

**Values:**

- `AssetKind.TABULAR` — `pandas.DataFrame`
- `AssetKind.RASTER` — `numpy.ndarray` (single payload, e.g. GeoTIFF)
- `AssetKind.ARRAY` — `dict[str, numpy.ndarray]` (multi-variable n-D arrays)
- `AssetKind.TILES` — tile pyramid descriptor
- `AssetKind.BLOB` — `bytes` (opaque binaries: PDF, DOCX, PPTX, RTF,
  plain text, etc.)

New kinds require adding a variant; plugin authors cannot extend the
enum.

---

### `Asset`

Uniform envelope across kinds.

**Attributes:**

- `payload` (Any): Kind-native data.
- `kind` (AssetKind): Which kind this asset is.
- `metadata` (Metadata): Unified metadata container.
- `extras` (dict[str, Any]): Kind-specific accessory info (CRS,
  rasterio profile, chunk spec). Never copies of the payload.

**Read-only convenience properties:**

- `asset.profile` → `extras.get("profile")`
- `asset.crs` → `extras.get("crs")`

**Typed kind accessors** (raise `IncompatibleAssetKindError` on mismatch):

- `asset.as_table() -> pandas.DataFrame`
- `asset.as_raster() -> numpy.ndarray`
- `asset.as_array() -> dict[str, numpy.ndarray]`
- `asset.as_tiles() -> Any`
- `asset.as_blob() -> bytes`

#### `Asset.derive(payload, *, slug=None, name=None, kind=None, derived_from=None, metadata_updates=None, extras_updates=None, inherit_custom_properties=False)`

Return a new `Asset` derived from this one. Records
`prov:wasDerivedFrom` for each parent.

**Parameters:**

- `payload` (Any): New payload for the child asset.
- `slug` / `name` (str | None): Identity for the child. Slug and name
  do *not* inherit from the parent.
- `kind` (AssetKind | None): Override the child's kind (default: same
  as parent).
- `derived_from` (Iterable[Asset] | None): Multi-parent provenance.
  Defaults to `[self]` (single-parent derivation).
- `metadata_updates` (dict | None): Extra `Metadata` keys to set on the child.
- `extras_updates` (dict | None): Updates merged into the deep-copied parent extras.
- `inherit_custom_properties` (bool): If `True`, copy
  `parent.metadata.custom_properties` to the child.

**Returns:** `Asset`

**Example (multi-parent):**

```python
ndvi = (nir.as_raster() - red.as_raster()) / (nir.as_raster() + red.as_raster())

child = nir.derive(
    ndvi,
    slug='ndvi-2024',
    name='NDVI 2024',
    derived_from=[nir, red],
)
ss.write(child, 'outputs/ndvi.tif')
```

Per-kind derive policies (e.g. clearing stale rasterio `profile`
fields when shape or dtype changes) run after the metadata fork.

---

### `ComponentSchema`

Per-component metadata: a tabular column, a raster band, an array
variable, or a tile layer.

```python
from sunstone import ComponentSchema
```

**Attributes:**

- `name` (str): Component name.
- `component_kind` (str): One of `"column"`, `"band"`, `"variable"`, `"layer"`.
- `dtype` (str | None): Data type, e.g. `"float32"`, `"uint16"`.
- `units` (str | None): Pint-parsable unit string, e.g. `"kelvin"`, `"m/s"`.
- `description` (str | None): Human-readable description.

Stored on `Metadata.component_metadata` keyed by component name.

---

### `IncompatibleAssetKindError`

Raised when a typed accessor (`as_table`, `as_raster`, ...) or a handler
is called with an asset whose `kind` does not match.

```python
from sunstone import IncompatibleAssetKindError
```

## pandas Module

Drop-in replacement for pandas with lineage tracking.

```python
from sunstone import pandas as pd
```

### Functions

#### `read_dataset(slug, project_path=None, strict=None, fetch_from_url=True, format=None, **kwargs)`

Read a dataset by slug with automatic format detection.

**Parameters:**

- `slug` (str): Dataset slug to look up in `datasets.yaml`
- `project_path` (str | Path | None): Path to project directory. Defaults to the value set with `sunstone.set_project_path()`, or `Path.cwd()` if none is set
- `strict` (bool | None): Enable strict mode. If None, reads from `SUNSTONE_DATAFRAME_STRICT` env var
- `fetch_from_url` (bool): If True and dataset has a source URL but no local file, fetch automatically
- `format` (str | None): Format override (`'csv'`, `'json'`, `'excel'`, `'parquet'`, `'tsv'`). Auto-detected from extension if not provided
- `**kwargs`: Additional arguments passed to the underlying pandas reader

**Returns:** `DataFrame` with lineage tracking

**Example:**

```python
df = pd.read_dataset('official-un-member-states')
df = pd.read_dataset('my-data', format='json', project_path='/path/to/project')
```

---

#### `read_csv(filepath, project_path=None, strict=None, **kwargs)`

Read CSV file with lineage tracking.

**Parameters:**

- `filepath` (str | Path): Path to CSV file, URL, or dataset slug
- `project_path` (str | Path | None): Path to project directory containing `datasets.yaml`. Defaults to the value set with `sunstone.set_project_path()`, or `Path.cwd()` if none is set
- `strict` (bool | None): If True, dataset must be pre-registered in `datasets.yaml`. If None, reads from `SUNSTONE_DATAFRAME_STRICT` env var
- `**kwargs`: Additional arguments passed to `pandas.read_csv()`

**Returns:** `DataFrame` with lineage tracking

**Raises:**

- `DatasetNotFoundError`: If dataset not found in `datasets.yaml`
- `StrictModeError`: If strict=True and dataset not pre-registered

**Example:**

```python
df = pd.read_csv(
    'data/schools.csv',
    project_path='/path/to/project',
    strict=True,
    encoding='utf-8'
)
```

---

#### `read_excel(filepath, project_path=None, strict=None, fetch_from_url=True, **kwargs)`

Read Excel file (.xlsx/.xls) with lineage tracking.

**Parameters:**

- `filepath` (str | Path): Path to Excel file or dataset slug
- `project_path` (str | Path | None): Path to project directory containing `datasets.yaml`. Defaults to the value set with `sunstone.set_project_path()`, or `Path.cwd()` if none is set
- `strict` (bool | None): If True, dataset must be pre-registered. If None, reads from `SUNSTONE_DATAFRAME_STRICT` env var
- `fetch_from_url` (bool): If True and dataset has a source URL but no local file, automatically fetch from URL
- `**kwargs`: Additional arguments passed to `pandas.read_excel()`

**Returns:** `DataFrame` with lineage tracking

**Raises:**

- `DatasetNotFoundError`: If dataset not found in `datasets.yaml`
- `FileNotFoundError`: If `datasets.yaml` doesn't exist

**Example:**

```python
# Load by slug (recommended)
df = pd.read_excel('my-excel-data', project_path='/path/to/project')

# Load by file path
df = pd.read_excel('data/schools.xlsx', project_path='/path/to/project', sheet_name='Sheet1')
```

---

#### `read_json(filepath, project_path=None, strict=None, **kwargs)`

Read JSON file with lineage tracking.

**Parameters:**

- `filepath` (str | Path): Path to JSON file or dataset slug
- `project_path` (str | Path | None): Path to project directory. Defaults to the value set with `sunstone.set_project_path()`, or `Path.cwd()` if none is set
- `strict` (bool | None): Enable strict mode. If None, reads from `SUNSTONE_DATAFRAME_STRICT` env var
- `**kwargs`: Additional arguments passed to `pandas.read_json()`

**Returns:** `DataFrame` with lineage tracking

**Example:**

```python
# Read a JSON file
df = pd.read_json('data/records.json', project_path=PROJECT_PATH)

# With pandas options
df = pd.read_json('data/records.json', orient='records', lines=True)
```

---

#### `merge(left, right, **kwargs)`

Merge DataFrames with combined lineage.

**Parameters:**

- `left` (DataFrame): Left DataFrame
- `right` (DataFrame): Right DataFrame
- `**kwargs`: Arguments passed to `pandas.merge()`

**Returns:** `DataFrame` with lineage from both sources

**Example:**

```python
result = pd.merge(schools, teachers, on='school_id', how='inner')
print(len(result.lineage.sources))  # 2
```

---

#### `concat(dfs, **kwargs)`

Concatenate DataFrames with combined lineage.

**Parameters:**

- `dfs` (list[DataFrame]): List of DataFrames to concatenate
- `**kwargs`: Arguments passed to `pandas.concat()`

**Returns:** `DataFrame` with lineage from all sources

**Example:**

```python
result = pd.concat([df1, df2, df3], ignore_index=True)
```

## DataFrame Class

Main class for working with data and lineage.

```python
from sunstone import DataFrame
```

### Class Methods

#### `read_csv(filepath, project_path, strict=False, **kwargs)`

Read CSV file and return DataFrame.

**Parameters:** Same as `pandas.read_csv()`

**Returns:** `DataFrame` instance

---

#### `read_excel(filepath, project_path, strict=False, fetch_from_url=True, **kwargs)`

Read Excel file and return DataFrame.

**Parameters:** Same as `pandas.read_excel()`

**Returns:** `DataFrame` instance

---

### Instance Methods

#### `to_csv(path, slug, name, *, license=None, check_license=True, track=True, **kwargs)`

Write DataFrame to CSV and register in `datasets.yaml`.

**Parameters:**

- `path` (str | Path): Output file path
- `slug` (str | None): Machine-readable identifier (required in relaxed mode if not registered)
- `name` (str | None): Human-readable name (required in relaxed mode if not registered)
- `license` (str | None): SPDX license identifier for the output. Persisted to `datasets.yaml` and used as the target for the compatibility check. When omitted, falls back to the dataset's existing `license`, then to `packages[].license` / `package.license`. If still unresolved and source licenses exist, one is auto-derived (inherited from a single source, or the most restrictive license that satisfies all sources) and persisted to `datasets.yaml`.
- `check_license` (bool): If `True` (default), raise [`LicenseCompatibilityError`](errors.md#licensecompatibilityerror) when the effective target license is incompatible with any source license collected from the current session lineage. Pass `check_license=False` to skip the check (and the auto-derivation).
- `track` (bool): If `False`, write the CSV directly without lineage tracking, dataset registration, or license enforcement. Useful for tests and exploratory work.
- `**kwargs`: Arguments passed to `pandas.DataFrame.to_csv()`

**Returns:** None

**Raises:**

- `StrictModeError`: In strict mode, if dataset not registered.
- `ValueError`: In relaxed mode, if `slug`/`name` not provided for a new dataset.
- `LicenseCompatibilityError`: If `check_license` is `True` and either (a) the declared target license conflicts with a source license, or (b) no target was declared and the source licenses are mutually incompatible / unverifiable so no default can be derived.

**Example:**

```python
df.to_csv(
    'outputs/summary.csv',
    slug='summary',
    name='Summary Results',
    license='CC-BY-4.0',
    index=False,
)
```

**Note:** Publishing is controlled by the top-level `publish` configuration in `datasets.yaml`, not per-dataset.

---

#### `to_parquet(path, slug, name, *, license=None, check_license=True, track=True, **kwargs)`

Write DataFrame to Parquet file and register in `datasets.yaml`.

**Parameters:**

- `path` (str | Path): Output file path
- `slug` (str | None): Machine-readable identifier (required in relaxed mode if not registered)
- `name` (str | None): Human-readable name (required in relaxed mode if not registered)
- `license` (str | None): SPDX license identifier for the output. Same semantics as `to_csv`'s `license` parameter.
- `check_license` (bool): If `True` (default), enforce license compatibility against source licenses. See `to_csv`.
- `track` (bool): If `False`, write without lineage tracking, dataset registration, or license enforcement.
- `**kwargs`: Arguments passed to `pandas.DataFrame.to_parquet()`

**Returns:** None

**Raises:** Same as `to_csv`.

**Example:**

```python
df.to_parquet(
    'outputs/summary.parquet',
    slug='summary',
    name='Summary Results',
    license='CC-BY-4.0',
)
```

---

#### `set_field_metadata(column, *, description, unit, source, type, constraints)`

Set metadata for a column. Returns self for method chaining.

**Parameters:**

- `column` (str): Column name to annotate
- `description` (str, optional): Human-readable description of the field
- `unit` (str, optional): Unit of measure (e.g., `'kg'`, `'students'`, `'%'`)
- `source` (str, optional): Slug of the input dataset this field comes from
- `type` (str, optional): Data type override. If None, inferred from dtype at write time
- `constraints` (dict, optional): Validation constraints (e.g., enum values)

**Returns:** `DataFrame` (self, for chaining)

**Example:**

```python
df.set_field_metadata('population', description='Total population', unit='people')
df.set_field_metadata('gdp', description='Gross domestic product', unit='USD')

# Method chaining
df = (df
    .set_field_metadata('area', unit='km^2')
    .set_field_metadata('density', unit='people / km^2')
)
```

---

#### `merge(right, **kwargs)`

Merge with another DataFrame.

**Parameters:**

- `right` (DataFrame): DataFrame to merge with
- `**kwargs`: Arguments passed to `pandas.merge()`

**Returns:** New `DataFrame` with combined lineage

---

#### `join(other, **kwargs)`

Join with another DataFrame.

**Parameters:**

- `other` (DataFrame): DataFrame to join with
- `**kwargs`: Arguments passed to `pandas.DataFrame.join()`

**Returns:** New `DataFrame` with combined lineage

---

#### `concat(others, **kwargs)`

Concatenate with other DataFrames.

**Parameters:**

- `others` (list[DataFrame]): DataFrames to concatenate
- `**kwargs`: Arguments passed to `pandas.concat()`

**Returns:** New `DataFrame` with combined lineage

---

#### `apply_operation(operation, description)`

Apply transformation with lineage tracking.

**Parameters:**

- `operation` (callable): Function that takes a pandas DataFrame and returns a pandas DataFrame
- `description` (str): Human-readable description of the operation

**Returns:** New `DataFrame` with operation recorded in lineage

**Example:**

```python
def adjust_enrollment(df):
    return df.assign(adjusted=df['enrollment'] * 1.1)

result = df.apply_operation(
    adjust_enrollment,
    description="Apply 10% enrollment adjustment factor"
)
```

---

### Instance Attributes

#### `data`

Access the underlying pandas DataFrame.

**Type:** `pandas.DataFrame`

**Example:**

```python
# Get numpy array
values = df.data.values

# Use pandas methods not wrapped
styled = df.data.style.highlight_max()
```

---

#### `metadata`

Access the unified metadata container.

**Type:** `Metadata`

**Example:**

```python
# Lineage is accessed through metadata
print(df.metadata.lineage.sources)
print(df.metadata.lineage.get_licenses())

df.metadata.slug = 'my-dataset'
df.metadata.name = 'My Dataset'
df.metadata.description = 'A description of this dataset'

# RDF prefixes and custom properties
df.metadata.rdf_prefixes = {'schema': 'http://schema.org/'}
df.metadata.custom_properties = {'schema:about': 'Education'}

# Per-field metadata (see set_field_metadata)
print(df.metadata.field_metadata)
```

---

#### `lineage` *(deprecated)*

Access lineage metadata directly. Use `df.metadata.lineage` instead.

**Type:** `LineageMetadata`

**Example:**

```python
# Preferred
print(df.metadata.lineage.sources)

# Deprecated (still works)
print(df.lineage.sources)
```

## DatasetsManager Class

Manage `datasets.yaml` files programmatically.

```python
from sunstone import DatasetsManager
```

### Constructor

#### `DatasetsManager(project_path, datasets_file=None)`

Create a datasets manager.

**Parameters:**

- `project_path` (str | Path): Path to project directory containing `datasets.yaml`
- `datasets_file` (str | Path | None): Path to a specific datasets YAML file (relative to project_path or absolute). Defaults to `"datasets.yaml"`

**Example:**

```python
manager = DatasetsManager('/path/to/project')

# Use a custom datasets file
manager = DatasetsManager('/path/to/project', datasets_file='config/my-datasets.yaml')
```

---

### Methods

#### `find_dataset_by_location(location, dataset_type=None)`

Find dataset by file path.

**Parameters:**

- `location` (str): File path to search for
- `dataset_type` (str, optional): Filter by 'input' or 'output'

**Returns:** `DatasetMetadata | None`

**Example:**

```python
dataset = manager.find_dataset_by_location('data/schools.csv')
if dataset:
    print(dataset.slug)
```

---

#### `find_dataset_by_slug(slug, dataset_type=None)`

Find dataset by slug identifier.

**Parameters:**

- `slug` (str): Slug to search for
- `dataset_type` (str, optional): Filter by 'input' or 'output'

**Returns:** `DatasetMetadata | None`

**Example:**

```python
dataset = manager.find_dataset_by_slug('school-data')
```

---

#### `get_all_inputs()`

Get all input datasets.

**Returns:** `list[DatasetMetadata]`

---

#### `get_all_outputs()`

Get all output datasets.

**Returns:** `list[DatasetMetadata]`

---

#### `get_publish_config()`

Get the top-level publish configuration.

**Returns:** `PublishConfig | None`

**Example:**

```python
publish_config = manager.get_publish_config()
if publish_config and publish_config.enabled:
    print(f"Publishing to: {publish_config.to}")
    print(f"Flatten: {publish_config.flatten}")
```

---

#### `add_output_dataset(name, slug, location, fields)`

Register new output dataset.

**Parameters:**

- `name` (str): Human-readable name
- `slug` (str): Machine-readable identifier
- `location` (str): File path
- `fields` (list[FieldSchema]): Field definitions

**Returns:** None

**Example:**

```python
from sunstone import FieldSchema

manager.add_output_dataset(
    name='Analysis Results',
    slug='analysis-results',
    location='outputs/results.csv',
    fields=[
        FieldSchema(name='category', type='string'),
        FieldSchema(name='count', type='integer'),
        FieldSchema(name='avg_value', type='number')
    ]
)
```

**Note:** Use the top-level `publish` configuration in `datasets.yaml` to enable publishing for all outputs.

---

#### `update_output_dataset(slug, **kwargs)`

Update existing output dataset.

**Parameters:**

- `slug` (str): Dataset slug to update
- `**kwargs`: Fields to update (name, location, fields, etc.)

**Returns:** None

---

#### `set_dataset_strict(slug, strict, dataset_type=None)`

Enable or disable strict mode for a dataset.

**Parameters:**

- `slug` (str): Dataset slug
- `strict` (bool): True to enable strict mode, False to disable
- `dataset_type` (str, optional): Filter by 'input' or 'output'

**Returns:** None

**Raises:** `DatasetNotFoundError` if dataset not found

**Example:**

```python
# Enable strict mode
manager.set_dataset_strict('school-data', True)

# Disable strict mode
manager.set_dataset_strict('school-data', False)
```

---

#### `update_output_lineage(slug, lineage, content_hash, strict=False)`

Update lineage metadata for an output dataset.

**Parameters:**

- `slug` (str): Output dataset slug
- `lineage` (LineageMetadata): Lineage metadata to write
- `content_hash` (str): Hash of the file content
- `strict` (bool): If True, validates without modifying

**Returns:** None

**Raises:**

- `DatasetNotFoundError`: If dataset not found
- `DatasetValidationError`: In strict mode, if lineage differs

**Note:** Timestamp only updates when content_hash changes.

---

#### `get_absolute_path(location)`

Convert relative path to absolute project path.

**Parameters:**

- `location` (str): Relative or absolute path

**Returns:** `Path`

## Linting

```python
from sunstone import lint_project
```

### `lint_project(project_path, *, datasets_file='datasets.yaml', rules=None)`

Lint a Sunstone project's `datasets.yaml` against the Sunstone Minimum Viable Metadata recommendations.

**Parameters:**

- `project_path` (str | Path): Project directory or a direct path to a `datasets.yaml` file.
- `datasets_file` (str): Filename relative to `project_path`. Defaults to `'datasets.yaml'`.
- `rules` (set[str] | None): Optional set of rule IDs to run (e.g. `{'R005', 'R104'}`). `None` runs all rules.

**Returns:** `LintReport` — see below.

**Example:**

```python
from sunstone import lint_project

report = lint_project('/path/to/project')
for v in report.errors:
    print(f"{v.rule_id} {v.location}: {v.message}")
```

See the [CLI Guide](cli.md#lint-command) for the full rule list.

---

### `LintReport`

Aggregated lint output.

**Attributes:**

- `project_path` (Path): The linted project directory.
- `violations` (list[Violation]): Active findings (not suppressed by `lint.disable`).
- `suppressed` (list[Violation]): Findings silenced by `lint.disable`, kept around for audit.
- `suppressions` (dict[str, str]): Map of `rule_id` → justification string from `lint.disable`.

**Properties:**

- `errors` (list[Violation]): Subset of `violations` with `severity == ERROR`.
- `warnings` (list[Violation]): Subset of `violations` with `severity == WARNING`.
- `info` (list[Violation]): Subset of `violations` with `severity == INFO`.

**Methods:**

- `to_dict()` — JSON-serialisable summary including counts and violation details.
- `format_text()` — Human-readable text summary.

---

### `Violation`

A single rule violation.

**Attributes:**

- `rule_id` (str): Stable identifier (e.g. `'R005'`).
- `severity` (Severity): `ERROR`, `WARNING`, or `INFO`.
- `message` (str): Short description of the problem.
- `location` (str): Path within `datasets.yaml` (e.g. `'inputs[0].source.license'`).
- `fix_hint` (str | None): Suggestion for how to fix it.

## Validation Functions

```python
from sunstone import check_notebook_imports, validate_project_notebooks
```

### `check_notebook_imports(notebook_path)`

Validate a single notebook's imports.

**Parameters:**

- `notebook_path` (str | Path): Path to notebook file

**Returns:** `ValidationResult`

**Example:**

```python
result = check_notebook_imports('analysis.ipynb')
if result.is_valid:
    print("✓ Notebook uses sunstone imports")
else:
    print(result.summary())
```

---

### `validate_project_notebooks(project_path)`

Validate all notebooks in a project.

**Parameters:**

- `project_path` (str | Path): Path to project directory

**Returns:** `dict[Path, ValidationResult]`

**Example:**

```python
results = validate_project_notebooks('/path/to/project')
for path, result in results.items():
    if not result.is_valid:
        print(f"\n{path}:")
        print(result.summary())
```

## Data Classes

### FieldSchema

Field definition for datasets.

**Attributes:**

- `name` (str): Field name
- `type` (str | None): Field type (string, number, integer, boolean, date, datetime). If None, inferred from dtype at write time
- `description` (str, optional): Field description
- `unit` (str, optional): Unit of measure (e.g., `'kg'`, `'%'`, `'people'`)
- `source` (str, optional): Slug of the input dataset this field's data comes from
- `constraints` (dict, optional): Validation constraints

**Example:**

```python
from sunstone import FieldSchema

field = FieldSchema(
    name='enrollment',
    type='integer',
    description='Number of enrolled students',
    unit='students',
    constraints={'minimum': 0}
)

# type can be omitted — it's inferred at write time
field = FieldSchema(name='ratio', description='Student-teacher ratio')
```

---

### DatasetMetadata

Dataset metadata from `datasets.yaml`.

**Attributes:**

- `name` (str): Human-readable name
- `slug` (str): Machine-readable identifier
- `location` (str): File path
- `fields` (list[FieldSchema]): Field definitions
- `source` (SourceMetadata | None): Source attribution (inputs only)
- `strict` (bool): Strict mode enabled
- `dataset_type` (str): 'input' or 'output'

---

### PublishConfig

Top-level publishing configuration.

**Attributes:**

- `enabled` (bool): Whether publishing is enabled
- `to` (str | None): Destination URL or path
- `flatten` (bool): Whether to flatten directory structure (default: False)

**Path Resolution:**

- If `to` ends with `.json`: Used as datapackage filename
  - `gs://bucket/countries.json` → datapackage at exact path
- If `to` doesn't end with `.json`: Treated as directory
  - `gs://bucket/datasets/project/` → adds `/datapackage.json`

**Example:**

```python
from sunstone import PublishConfig

config = PublishConfig(
    enabled=True,
    to='gs://my-bucket/datasets/project/',
    flatten=False
)
```

---

### LineageMetadata

Lineage tracking information. Aligned with W3C PROV-O.

**Attributes:**

- `sources` (list[DatasetMetadata]): Source datasets that contributed to this data
- `created_at` (datetime | None): Timestamp when lineage was last updated (content changed)
- `content_hash` (str | None): SHA256 hash of the DataFrame content
- `activity` (Activity | None): The PROV-O Activity that generated this data
- `field_derivations` (list[FieldDerivation] | None): Field-level derivation detail (prov:qualifiedDerivation)

**Methods:**

- `get_licenses()`: Return list of all source licenses
- `add_source(source)`: Add source dataset
- `populate_field_derivations(columns, slug)`: Auto-populate field derivations for columns from a source
- `merge(other)`: Merge lineage from another DataFrame, combining sources and field derivations

---

### Activity

A W3C PROV-O Activity representing a script or notebook execution.

**Attributes:**

- `id` (str): Unique identifier (e.g., `'exec-{timestamp}-{hash}'`)
- `used` (list[UsageRecord]): Input entities consumed by this activity
- `generated` (list[EntityRef]): Output entities produced
- `was_associated_with` (list[Agent]): Agents involved in this activity
- `started_at` (datetime | None): When the activity started
- `ended_at` (datetime | None): When the activity ended
- `script_path` (str | None): Path to the executed Python script
- `git_commit` (str | None): Git commit hash at time of execution

---

### Agent

A W3C PROV-O Agent: something that bears responsibility for an activity.

**Attributes:**

- `id` (str): Unique identifier (username, org name, software name)
- `type` (AgentType): One of `PERSON`, `SOFTWARE`, `ORGANIZATION`
- `label` (str | None): Human-readable label
- `version` (str | None): Version string (for SoftwareAgent)

---

### FieldDerivation

Records that an output field was derived from a source entity. Maps to prov:qualifiedDerivation at the field level.

**Attributes:**

- `output_field` (str): Name of the output column
- `source_entity` (str): Slug of the source dataset
- `source_field` (str | None): Name of the source field, if known

---

### EntityRef

Lightweight reference to a PROV Entity (dataset).

**Attributes:**

- `slug` (str): Dataset slug identifier
- `namespace` (str | None): Optional namespace URI for external entities

---

### UsageRecord

Records how an Activity used an Entity. Maps to prov:qualifiedUsage.

**Attributes:**

- `entity` (EntityRef): Which entity was used
- `columns` (list[str] | None): Which columns were selected (None means all)
- `filters` (dict | None): Filters applied during read

## Metadata Class

Unified metadata container for DataFrames.

```python
from sunstone.lineage import Metadata
```

**Attributes:**

- `lineage` (LineageMetadata): Lineage metadata tracking data provenance
- `description` (str | None): Human-readable description of the dataset
- `rdf_prefixes` (dict | None): RDF namespace prefixes for custom properties
- `custom_properties` (dict | None): Custom properties including RDF triples
- `field_metadata` (dict[str, FieldSchema]): Per-column metadata, keyed by column name (tabular shortcut over `component_metadata`)
- `component_metadata` (dict[str, ComponentSchema]): Per-component metadata keyed by component name (column, band, variable, layer)
- `slug` (str | None): Dataset slug, used at write time
- `name` (str | None): Human-readable dataset name, used at write time

## Plugin System

The plugin system handles reading, writing, and URL resolution through a registry of handlers.

```python
from sunstone.plugins import PluginRegistry
```

### PluginRegistry

Central registry for auth providers, URL handlers, and format handlers.

#### `PluginRegistry.get(project_path=None)`

Return a cached registry instance. If `project_path` is provided, the registry is scoped to that project and loads project-specific plugin configuration.

**Example:**

```python
registry = PluginRegistry.get('/path/to/project')
```

---

#### `registry.fetch(url, dest)`

Download a URL to a local file using the appropriate URL handler.

**Parameters:**

- `url` (str): URL to download (supports `http://`, `https://`, `gs://`, `s3://`, `r2://`, local paths)
- `dest` (Path): Local destination file path

**Returns:** `Path` to the downloaded file

**Example:**

```python
from pathlib import Path
from sunstone.plugins import PluginRegistry

registry = PluginRegistry.get()
registry.fetch('gs://my-bucket/data.csv', Path('data/local.csv'))
```

> **Note:** `DatasetsManager.fetch_from_url()` is deprecated. Use `PluginRegistry.get().fetch()` instead.

---

#### Content-type discovery

Four accessors expose what sunstone knows how to read or write so
downstream tools (catalogs, dispatch layers, UIs) can enumerate the
format surface without re-implementing the format catalogue.

##### `registry.known_content_descriptors() -> set[ContentDescriptor]`

Union of `content_descriptors()` across every registered format and
store handler that declares the method. Handlers without the method
contribute nothing.

##### `registry.known_content_types() -> set[str]`

Convenience projection — the set of canonical MIME strings present in
`known_content_descriptors()`, regardless of encoding.

##### `registry.known_extensions() -> dict[str, FormatHandler | StoreFormatHandler]`

Map of declared file extension → handler. First-registered wins on
conflict, matching dispatch priority (external plugins win over
built-ins on overlapping extensions).

##### `registry.handler_for_content(content_type, content_encoding=None)`

First handler whose declared `content_descriptors()` contains a
matching `(content_type, content_encoding)` pair.

- Parameters are stripped from `content_type` (so
  `"text/csv; charset=utf-8"` matches `"text/csv"`).
- `content_encoding=None` matches identity-encoded handlers; passing
  `"gzip"`, `"br"`, etc. requires a handler that declares the encoded
  variant explicitly.
- Returns `None` when nothing matches.

```python
from sunstone.plugins import PluginRegistry

reg = PluginRegistry.get()
reg.known_content_types()                          # {'text/csv', 'application/pdf', ...}
reg.handler_for_content('text/csv; charset=utf-8') # <BuiltinFormatHandler ...>
reg.handler_for_content('text/csv', 'gzip')        # None
```

##### `ContentDescriptor`

```python
from sunstone.handlers_meta import ContentDescriptor
```

Frozen dataclass identifying what a handler reads or writes. Mirrors
HTTP `Content-Type` + `Content-Encoding`.

**Attributes:**

- `content_type` (str): Canonical MIME, no parameters
  (e.g. `"text/csv"`).
- `content_encoding` (str | None): Transport/storage encoding —
  `"gzip"`, `"br"`, `"zstd"`, `"deflate"`, or `None` for identity.

`ContentDescriptor` is hashable and equal-by-value, so the
`known_content_descriptors()` view is a real `set`.

---

### Plugin Protocols

Plugins implement one or more of these protocols:

- **`AuthProvider`**: Provides authentication headers for HTTP requests.
- **`URLHandler`**: Resolves URLs to readable/writable streams via `open(url, mode)`.
- **`FormatHandler`**: Stream-based format reader/writer. Used for
  single-file formats whose library accepts a byte stream (CSV, JSON,
  Parquet, `.npz`, PDF/DOCX/etc. via `BlobFormatHandler`). Returns /
  accepts `Asset`.
- **`ContentDescriptorAware`** (optional, `sunstone.plugins`): Extends
  any `FormatHandler` / `StoreFormatHandler` with `content_descriptors()`
  and `extensions()` methods so it participates in
  [content-type discovery](#content-type-discovery). Handlers without
  these methods still dispatch normally; they just don't appear in
  enumeration.
- **`StoreFormatHandler`** (`sunstone.resource.StoreFormatHandler`):
  Path-based format reader/writer for formats whose library needs a
  real path or directory (HDF5, Zarr, MBTiles, partitioned Parquet).
  Handlers MUST declare `__sunstone_handler_protocol__ = 2` and operate
  on a `ResourceLocation`. Single-file store handlers are consulted
  before the stream registry, so they can claim paths like `data.h5`.
- **`CLIProvider`**: Contributes a `typer` command group mounted under
  `sunstone <name>`. Built-in groups (`dataset`, `package`, `lineage`,
  `env`, `license`) are protected from collision.

### `ResourceLocation`

```python
from sunstone.resource import ResourceLocation
```

Wraps a path or URL that may refer to a single file or a
directory/prefix. Pass to `StoreFormatHandler.read()` / `.write()`.

**Attributes:**

- `path` (str): The underlying path or URL string.

**Methods:**

- `as_path() -> pathlib.Path` — local-path view.
- `is_dir() -> bool` — true when the path resolves to a directory.
- `list(glob='*') -> Iterator[ResourceLocation]` — enumerate children.
- `subpath(rel) -> ResourceLocation` — join a relative path.
- `open_byte_stream(mode='rb') -> BinaryIO` — single-file byte stream
  (routes through the `URLHandler` registry for non-local paths).

### Plugin Discovery

External plugins are discovered via the `sunstone.plugins` entry point group:

```toml
# In your plugin's pyproject.toml
[project.entry-points."sunstone.plugins"]
my-plugin = "my_package:MyPlugin"
```

### Plugin Configuration

Configuration is loaded with cascading precedence:

1. `datasets.yaml` → `plugins.<name>` section (highest priority)
2. `pyproject.toml` → `[tool.sunstone.plugins.<name>]` section
3. Environment variables → `SUNSTONE_PLUGIN_<NAME>_<KEY>`

### Built-in URL Handlers

| Scheme | Handler | Extra |
|--------|---------|-------|
| Local files | `LocalFileHandler` | Built-in |
| `http://`, `https://` | `HttpURLHandler` | Built-in (with SSRF protection) |
| `gs://` | `GcsURLHandler` | Requires `sunstone-py[gcs]` |
| `s3://`, `r2://` | `S3URLHandler` | Requires `sunstone-py[s3]` |

## Unit-Aware Arithmetic

sunstone-py integrates with [Pint](https://pint.readthedocs.io/) for unit-aware column arithmetic.

### Unit Modes

Set via `SUNSTONE_UNIT_MODE` environment variable or programmatically:

```python
from sunstone.units import set_unit_mode

set_unit_mode('strict')  # Raise on unit mismatch
set_unit_mode('auto')    # Auto-convert compatible units
set_unit_mode('relaxed') # No unit validation (default)
```

| Mode | Add/Sub mismatch | Mul/Div | Unknown units |
|------|-----------------|---------|---------------|
| `relaxed` | Allowed | Allowed | Allowed |
| `strict` | Error | Computes result unit | Error |
| `auto` | Auto-converts if compatible | Computes result unit | Warning |

### Setting Units on Columns

```python
df.set_field_metadata('distance', unit='km')
df.set_field_metadata('time', unit='hour')
```

### Unit Tracking Through Operations

When columns with units are used in merge, join, or concat operations, sunstone validates unit compatibility and (in `auto` mode) applies conversions automatically.

### QUDT Round-Tripping

Units stored as [QUDT](http://qudt.org/) URIs in `datasets.yaml` are preserved through read/write cycles via the `unit_source` field on `FieldSchema`.

## RDF Value Wrappers

Plain Python literals (`str`, `int`, `float`, `bool`, `datetime`, `Decimal`)
cover most of what shows up in `Metadata.custom_properties`. These
three wrappers disambiguate the cases Python's type system cannot
distinguish on its own.

```python
from sunstone import IRI, LangString, TypedLiteral
```

### `IRI`

A subclass of `str` flagged as an IRI reference. Stays string-comparable
and JSON-friendly, but `isinstance(x, IRI)` distinguishes it from a
plain string literal. Prefix resolution (e.g. `sosa:NDVI` → full URI)
runs at JSON-LD serialisation time against `Metadata.rdf_prefixes`.

```python
metadata.custom_properties['schema:about'] = IRI('schema:Education')
```

---

### `LangString`

A language-tagged literal. Serialises to JSON-LD as
`{"@value": ..., "@language": ...}`.

**Attributes:**

- `value` (str)
- `lang` (str): BCP-47 tag, e.g. `"en"`, `"fr-CA"`.

```python
metadata.custom_properties['dct:title'] = LangString('Mon ensemble', 'fr-CA')
```

---

### `TypedLiteral`

A literal with an explicit XSD datatype. Use when Python-type inference
would pick the wrong xsd type. Serialises to JSON-LD as
`{"@value": ..., "@type": ...}`.

**Attributes:**

- `value` (Any)
- `datatype` (str): e.g. `"xsd:double"`.

```python
metadata.custom_properties['si:precision'] = TypedLiteral('1.0', 'xsd:double')
```

## Constants

### `STANDARD_RDF_PREFIXES`

Dictionary of built-in RDF prefix bindings that are always available in `datasets.yaml` and the generated `datapackage.json` without needing to be declared.

```python
from sunstone import STANDARD_RDF_PREFIXES

print(STANDARD_RDF_PREFIXES['si'])
# 'https://sunstone.institute/rdf/vocab#'
```

See [RDF Prefixes in datasets.yaml](rdf-prefixes-guide.md#standard-prefixes) for the full table and usage.

## License Compatibility

```python
from sunstone.licenses import (
    is_valid_spdx,
    known_licenses,
    get_properties,
    check_compatibility,
    get_most_restrictive_license,
    derive_compatible_target,
    LicenseProperties,
    LicenseCompatibilityResult,
    LicenseCompatibilityError,
)
```

Programmatic counterparts to the [`sunstone license`](cli.md#license-commands) CLI. The rules engine and embedded registry are documented in [Concepts → License Compatibility](concepts.md#license-compatibility).

---

### `is_valid_spdx(identifier)`

True if `identifier` is a recognised SPDX id, an entry in the embedded registry, or any well-formed `LicenseRef-*` identifier per the SPDX spec. This is the validator used by lint rule `R006`.

**Parameters:**

- `identifier` (str): License identifier to validate.

**Returns:** `bool`

---

### `known_licenses()`

Return every license in the embedded registry, sorted by SPDX identifier.

**Returns:** `list[LicenseProperties]`

---

### `get_properties(identifier)`

Return the `LicenseProperties` for `identifier`, or `None` if it is not in the embedded registry. Returns `None` even for *valid* `LicenseRef-*` ids that are not registered — callers must decide how to treat unknown licenses.

**Parameters:**

- `identifier` (str): SPDX identifier or alias.

**Returns:** `LicenseProperties | None`

---

### `check_compatibility(source_licenses, target_license)`

Check whether `target_license` is compatible with every license in `source_licenses`. This is the function the CLI and the writers' `check_license` enforcement both call.

**Parameters:**

- `source_licenses` (Iterable[str]): SPDX identifiers of source licenses.
- `target_license` (str): Proposed target license identifier.

**Returns:** `LicenseCompatibilityResult`

**Example:**

```python
from sunstone.licenses import check_compatibility

result = check_compatibility(
    source_licenses=["CC-BY-NC-4.0", "CC-BY-4.0"],
    target_license="CC-BY-4.0",
)
if not result.compatible:
    for conflict in result.conflicts:
        print(conflict)
    if result.suggestions:
        print("Try one of:", result.suggestions)
```

---

### `get_most_restrictive_license(licenses)`

Return the SPDX identifier of the most restrictive license in `licenses`, or `None` if none of them are registered. Useful for suggesting a target license for a derived dataset.

Ordering, most-to-least restrictive: ShareAlike > NonCommercial > Attribution > Public Domain.

**Parameters:**

- `licenses` (Iterable[str]): SPDX identifiers to compare.

**Returns:** `str | None`

---

### `derive_compatible_target(source_licenses)`

Derive a target license that satisfies every source. Used by the writers to auto-assign an output license when none has been declared:

- A single unique source license is returned as-is (the output inherits it).
- Multiple unique source licenses produce the most restrictive registry license that satisfies every source.
- Returns `None` when no compatible target exists — mutually incompatible ShareAlike families, or unknown identifiers among multiple sources that prevent verification.

**Parameters:**

- `source_licenses` (Iterable[str]): SPDX identifiers of source licenses.

**Returns:** `str | None`

---

### `LicenseProperties`

Frozen dataclass describing a license in the registry.

**Attributes:**

- `spdx` (str): SPDX identifier (e.g. `'CC-BY-4.0'`).
- `name` (str): Human-readable name.
- `public_domain` (bool): True for CC0, PDDL, and similar — compatible with everything.
- `attribution` (bool): Downstream users must credit the source.
- `share_alike` (bool): Derivatives must use the same (same-family) license.
- `non_commercial` (bool): Commercial use is forbidden downstream.
- `family` (str | None): ShareAlike family identifier — only same-family SA licenses are mutually compatible.
- `aliases` (tuple[str, ...]): Alternate identifiers (case-insensitive) that map to this license.

---

### `LicenseCompatibilityResult`

Outcome of a `check_compatibility` call.

**Attributes:**

- `target` (str): The proposed target license identifier.
- `sources` (list[str]): Source identifiers considered (deduplicated, preserving order).
- `compatible` (bool): True if `target` satisfies every source's downstream requirements.
- `conflicts` (list[str]): Human-readable conflict descriptions; empty when `compatible` is `True`.
- `suggestions` (list[str]): Target licenses that *would* satisfy every known source (best-effort).
- `unknown_sources` (list[str]): Source identifiers not present in the registry — excluded from the rule check.
- `unknown_target` (bool): True if `target` is not in the registry; the result then carries a conflict explaining that compatibility could not be verified.

---

### `LicenseCompatibilityError`

Subclass of [`SunstoneError`](#sunstoneerror). Raised by `to_csv()` / `to_parquet()` when `check_license=True` and the effective target license conflicts with a source license. See [Error handling → `LicenseCompatibilityError`](errors.md#licensecompatibilityerror) for the recovery pattern.

## Environment Configuration

```python
from sunstone import (
    Environment,
    activate_environment,
    resolve_environment,
)
```

Sunstone resolves environment settings from cascading TOML files and
overlays them on `os.environ`. Within a single environment definition,
field-level merging follows the same precedence: project > user >
system. See the [`sunstone env`](cli.md#environment-commands) commands
for the CLI surface.

**File precedence (highest wins for active-environment selection):**

1. `SUNSTONE_DATA_ENV` env var.
2. `.sunstone/data_platform.toml` (project, walked up from cwd).
3. `~/.config/sunstone/data_platform.toml` (user).
4. `/etc/sunstone/data_platform.toml` (system).

---

### `Environment`

Resolved environment configuration.

**Attributes:**

- `name` (str): Active environment name.
- `source` (str): The file (or `SUNSTONE_DATA_ENV`) that selected this environment.
- `vars` (Mapping[str, str]): Flattened key/value pairs from top-level
  scalars and plugin-namespaced subtables. Keys are uppercased and
  hyphens become underscores.
- `sections` (Mapping[str, Any]): Typed models built by registered
  `EnvSectionProvider` plugins, keyed by section name.

**Methods:**

- `activate() -> dict[str, str]`: Layer `vars` onto `os.environ`.
  Pre-existing real env vars always win — this never overwrites them.
  Returns the dict of keys this call actually set.

---

### `activate_environment(*, system_config=None, user_config=None, project_config=None)`

Convenience: resolve the active environment and call `.activate()`.

**Returns:** `dict[str, str]` — keys actually set in `os.environ`
(empty when no active environment is configured or all keys were
already set).

**Example:**

```python
import sunstone

applied = sunstone.activate_environment()
print(f"Applied {len(applied)} env vars from active environment")
```

---

### `resolve_environment(*, system_config=None, user_config=None, project_config=None)`

Load all config files, merge environments, resolve the active name,
flatten keys, resolve `op://` credential references, and build typed
section models for any registered `EnvSectionProvider` plugins.

**Returns:** `Environment | None` — `None` if no active environment is configured.

**Raises:** `ValueError` if the active environment name does not match
any defined environment, or a section model fails validation.

---

### `DataEnvironment` *(deprecated)*

Deprecated alias retained for backward compatibility. Use
`Environment` instead.

## Exceptions

```python
from sunstone.exceptions import (
    SunstoneError,
    DatasetNotFoundError,
    StrictModeError,
    DatasetValidationError,
    LineageError,
)
from sunstone.errors import IncompatibleAssetKindError
from sunstone.licenses import LicenseCompatibilityError
```

### `SunstoneError`

Base exception for all sunstone-py errors.

---

### `DatasetNotFoundError`

Raised when dataset not found in `datasets.yaml`.

**Example:**

```python
try:
    df = pd.read_csv('missing.csv', project_path=PROJECT_PATH)
except DatasetNotFoundError as e:
    print(f"Dataset not registered: {e}")
```

---

### `StrictModeError`

Raised when operation blocked in strict mode.

**Example:**

```python
try:
    df.to_csv('new.csv', slug='new', name='New', strict=True)
except StrictModeError as e:
    print(f"Strict mode violation: {e}")
```

---

### `DatasetValidationError`

Raised when dataset validation fails.

---

### `LineageError`

Raised when lineage tracking encounters an error.

## Type Hints

sunstone-py includes complete type hints for IDE support:

```python
from sunstone import DataFrame, DatasetsManager
from pathlib import Path

# Type hints work automatically
def process_data(path: Path, project: Path) -> DataFrame:
    df: DataFrame = pd.read_csv(str(path), project_path=project)
    return df[df['value'] > 100]
```
