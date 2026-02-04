# API Reference

Complete API documentation for sunstone-py.

## pandas Module

Drop-in replacement for pandas with lineage tracking.

```python
from sunstone import pandas as pd
```

### Functions

#### `read_csv(filepath, project_path, strict=False, **kwargs)`

Read CSV file with lineage tracking.

**Parameters:**

- `filepath` (str | Path): Path to CSV file (relative to project or absolute)
- `project_path` (str | Path): Path to project directory containing `datasets.yaml`
- `strict` (bool): If True, dataset must be pre-registered in `datasets.yaml`
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

#### `read_json(filepath, project_path, strict=False, **kwargs)`

Read JSON file with lineage tracking.

**Parameters:**

- `filepath` (str | Path): Path to JSON file
- `project_path` (str | Path): Path to project directory
- `strict` (bool): Enable strict mode
- `**kwargs`: Additional arguments passed to `pandas.read_json()`

**Returns:** `DataFrame` with lineage tracking

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

#### `lineage`

Access lineage metadata.

**Type:** `LineageMetadata`

**Example:**

```python
print(df.lineage.sources)
print(df.lineage.operations)
print(df.lineage.get_licenses())
```

## DatasetsManager Class

Manage `datasets.yaml` files programmatically.

```python
from sunstone import DatasetsManager
```

### Constructor

#### `DatasetsManager(project_path)`

Create a datasets manager.

**Parameters:**

- `project_path` (str | Path): Path to project directory containing `datasets.yaml`

**Example:**

```python
manager = DatasetsManager('/path/to/project')
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
- `type` (str): Field type (string, number, integer, boolean, date, datetime)
- `description` (str, optional): Field description
- `constraints` (dict, optional): Validation constraints

**Example:**

```python
from sunstone import FieldSchema

field = FieldSchema(
    name='enrollment',
    type='integer',
    description='Number of enrolled students',
    constraints={'minimum': 0}
)
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

Lineage tracking information.

**Attributes:**

- `sources` (list[SourceDataset]): Source datasets
- `operations` (list[str]): Operations performed

**Methods:**

- `get_licenses()`: Return list of all source licenses
- `add_source(source)`: Add source dataset
- `add_operation(description)`: Add operation description

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
