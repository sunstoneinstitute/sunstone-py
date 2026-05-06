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

#### `to_csv(path, slug, name, **kwargs)`

Write DataFrame to CSV and register in `datasets.yaml`.

**Parameters:**

- `path` (str | Path): Output file path
- `slug` (str): Machine-readable identifier
- `name` (str): Human-readable name
- `**kwargs`: Arguments passed to `pandas.DataFrame.to_csv()`

**Returns:** None

**Example:**

```python
df.to_csv(
    'outputs/summary.csv',
    slug='summary',
    name='Summary Results',
    index=False
)
```

**Note:** Publishing is controlled by the top-level `publish` configuration in `datasets.yaml`, not per-dataset.

---

#### `to_parquet(path, slug, name, **kwargs)`

Write DataFrame to Parquet file and register in `datasets.yaml`.

**Parameters:**

- `path` (str | Path): Output file path
- `slug` (str | None): Machine-readable identifier (required in relaxed mode if not registered)
- `name` (str | None): Human-readable name (required in relaxed mode if not registered)
- `track` (bool): If False, write without lineage tracking or dataset registration
- `**kwargs`: Arguments passed to `pandas.DataFrame.to_parquet()`

**Returns:** None

**Example:**

```python
df.to_parquet(
    'outputs/summary.parquet',
    slug='summary',
    name='Summary Results'
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

# Dataset identity
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
- `field_metadata` (dict[str, FieldSchema]): Per-column metadata, keyed by column name
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

### Plugin Protocols

Plugins implement one or more of these protocols:

- **`AuthProvider`**: Provides authentication headers for HTTP requests
- **`URLHandler`**: Resolves URLs to readable/writable streams via `open(url, mode)`
- **`FormatHandler`**: Reads and writes data formats (CSV, JSON, Excel, Parquet, TSV)

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

## Constants

### `STANDARD_RDF_PREFIXES`

Dictionary of built-in RDF prefix bindings that are always available in `datasets.yaml` and the generated `datapackage.json` without needing to be declared.

```python
from sunstone import STANDARD_RDF_PREFIXES

print(STANDARD_RDF_PREFIXES['si'])
# 'https://sunstone.institute/rdf/vocab#'
```

See [RDF Prefixes in datasets.yaml](rdf-prefixes-guide.md#standard-prefixes) for the full table and usage.

## Exceptions

```python
from sunstone.exceptions import (
    SunstoneError,
    DatasetNotFoundError,
    StrictModeError,
    DatasetValidationError,
    LineageError
)
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
