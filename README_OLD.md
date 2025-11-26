# Sunstone Python Library

A Python library for managing datasets with lineage tracking in Sunstone projects.

## Features

- **Lineage Tracking**: Automatically track data provenance through all operations
- **datasets.yaml Integration**: Read from and write to datasets registered in `datasets.yaml`
- **Strict/Relaxed Modes**: Control whether operations can modify `datasets.yaml`
- **Pandas Compatible**: Wraps pandas DataFrame with full compatibility
- **Type Hints**: Full type hint support for better IDE integration

## Installation

From the project root:

```bash
cd lib
uv venv
uv sync
```

Or install with development dependencies:

```bash
uv sync --extra dev
```

## Quick Start

### Basic Usage

```python
import sunstone

# Read a dataset (must be registered in datasets.yaml)
df = sunstone.DataFrame.read_csv(
    'official_un_member_states_raw.csv',
    project_path='/path/to/SchoolCountProject'
)

# Perform operations - lineage is automatically tracked
filtered = df.apply_operation(
    lambda d: d[d['Amount'] > 100],
    description="Filter countries with >100 schools"
)

# Write output (in relaxed mode, auto-registers in datasets.yaml)
filtered.to_csv(
    'filtered_schools.csv',
    slug='filtered-schools',
    name='Filtered School Counts',
    index=False
)
```

### Strict vs Relaxed Mode

**Strict Mode** (default if `SUNSTONE_DATAFRAME_STRICT=1` or `SUNSTONE_DATAFRAME_STRICT=true`):
- Reading from unregistered datasets will fail
- Writing to unregistered outputs will fail
- Ensures all data operations are documented in `datasets.yaml`

**Relaxed Mode** (default otherwise):
- Writing to new outputs auto-registers them in `datasets.yaml`
- More flexible for exploratory work

```python
# Explicitly set mode
df = sunstone.DataFrame.read_csv(
    'data.csv',
    project_path='/path/to/project',
    strict=True  # or False for relaxed mode
)

# Or use environment variable
import os
os.environ['SUNSTONE_DATAFRAME_STRICT'] = '1'  # Enable strict mode globally
```

### Merging DataFrames with Lineage

```python
import sunstone

# Read two datasets
schools = sunstone.DataFrame.read_csv(
    'amount_school_data.csv',
    project_path='/path/to/project'
)

countries = sunstone.DataFrame.read_csv(
    'official_un_member_states_raw.csv',
    project_path='/path/to/project'
)

# Merge - lineage from both sources is preserved
result = schools.merge(
    countries,
    left_on='Country Code',
    right_on='ISO Code',
    how='left'
)

# Check lineage
print(f"Sources: {len(result.lineage.sources)}")
print(f"Operations: {result.lineage.operations}")
print(f"Licenses: {result.lineage.get_licenses()}")
```

### Working with Lineage Metadata

```python
# Access lineage information
print(result.lineage.to_dict())

# Get all licenses from source datasets
licenses = result.lineage.get_licenses()

# View operation history
for op in result.lineage.operations:
    print(f"- {op}")
```

### Advanced: Using DatasetsManager

```python
from sunstone import DatasetsManager

# Initialize manager
manager = DatasetsManager('/path/to/project')

# Find datasets
dataset = manager.find_dataset_by_slug('official-un-member-states')
dataset = manager.find_dataset_by_location('data.csv')

# Get all inputs/outputs
inputs = manager.get_all_inputs()
outputs = manager.get_all_outputs()

# Manually add output (normally done automatically in relaxed mode)
from sunstone import FieldSchema

manager.add_output_dataset(
    name='My Analysis Results',
    slug='my-analysis-results',
    location='outputs/results.csv',
    fields=[
        FieldSchema(name='country', type='string'),
        FieldSchema(name='value', type='number')
    ],
    publish=True
)
```

## API Reference

### DataFrame

Main class for working with data:

- `DataFrame.read_csv(filepath, project_path, strict, **kwargs)`: Read CSV with lineage tracking
- `to_csv(path, slug, name, publish, **kwargs)`: Write CSV and register in datasets.yaml
- `merge(right, **kwargs)`: Merge with another DataFrame, combining lineage
- `join(other, **kwargs)`: Join with another DataFrame, combining lineage
- `concat(others, **kwargs)`: Concatenate multiple DataFrames
- `apply_operation(operation, description)`: Apply transformation with lineage tracking

### DatasetsManager

Manage `datasets.yaml` files:

- `find_dataset_by_location(location, dataset_type)`: Find dataset by file path
- `find_dataset_by_slug(slug, dataset_type)`: Find dataset by slug
- `get_all_inputs()`: Get all input datasets
- `get_all_outputs()`: Get all output datasets
- `add_output_dataset(...)`: Register a new output dataset
- `update_output_dataset(...)`: Update existing output dataset

### Exceptions

- `SunstoneError`: Base exception
- `DatasetNotFoundError`: Dataset not found in datasets.yaml
- `StrictModeError`: Operation blocked in strict mode
- `DatasetValidationError`: Dataset metadata validation failed
- `LineageError`: Lineage tracking error

## Environment Variables

- `SUNSTONE_DATAFRAME_STRICT`: Set to `"1"` or `"true"` to enable strict mode by default

## Development

Run tests:

```bash
uv run pytest
```

Type checking:

```bash
uv run mypy src/sunstone
```

Linting and formatting:

```bash
uv run ruff check src/sunstone
uv run ruff format src/sunstone
```

## License

MIT
