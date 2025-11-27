# sunstone-py

A Python library for managing datasets with lineage tracking in data science projects.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Automatic Lineage Tracking**: Track data provenance through all operations automatically
- **Dataset Management**: Integration with `datasets.yaml` for organized dataset registration
- **Pandas-Compatible API**: Familiar pandas-like interface via `from sunstone import pandas as pd`
- **Strict/Relaxed Modes**: Control whether operations can modify `datasets.yaml`
- **Validation Tools**: Check notebooks and scripts for correct import usage
- **Full Type Hints**: Complete type hint support for better IDE integration

## Installation

```bash
# Using uv (recommended)
uv add sunstone-py

# Using pip
pip install sunstone-py
```

To use the latest commit from github:

```toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git",
]
```

If you are making changes to sunstone-py checked out at `~/git/sunstone-py` and testing them
directly from your project:

```toml
dependencies = [
    "sunstone-py @ file://${HOME}/git/sunstone-py"
]
```

### For Development

```bash
git clone https://github.com/sunstoneinstitute/sunstone-py.git
cd sunstone-py
uv venv
uv sync
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```


## Quick Start

### 1. Set Up Your Project with datasets.yaml

Create a `datasets.yaml` file in your project directory:

```yaml
inputs:
  - name: School Data
    slug: school-data
    location: data/schools.csv
    source:
      name: Ministry of Education
      location:
        data: https://example.com/schools.csv
      attributedTo: Ministry of Education
      acquiredAt: 2025-01-15
      acquisitionMethod: manual-download
      license: CC-BY-4.0
    fields:
      - name: school_id
        type: string
      - name: enrollment
        type: integer

outputs: []
```

### 2. Use Pandas-Like API with Lineage Tracking

```python
from sunstone import pandas as pd
from pathlib import Path

# Set project path (where datasets.yaml lives)
PROJECT_PATH = Path.cwd()

# Read data - lineage automatically tracked
df = pd.read_csv('data/schools.csv', project_path=PROJECT_PATH)

# Transform using familiar pandas operations
result = df[df['enrollment'] > 100].groupby('district').sum()

# Save with automatic lineage tracking and dataset registration
result.to_csv(
    'outputs/summary.csv',
    slug='school-summary',
    name='School Enrollment Summary',
    index=False
)
```

### 3. Check Lineage Metadata

```python
# View lineage information
print(result.lineage.sources)      # Source datasets
print(result.lineage.operations)   # Operations performed
print(result.lineage.get_licenses())  # All source licenses
```

## Core Concepts

### Pandas-Like API

sunstone-py provides a drop-in replacement for pandas that adds lineage tracking:

```python
from sunstone import pandas as pd

# Works like pandas, but tracks lineage
df = pd.read_csv('input.csv', project_path='/path/to/project')
df2 = pd.read_csv('input2.csv', project_path='/path/to/project')

# All pandas operations work
filtered = df[df['value'] > 100]
grouped = df.groupby('category').sum()

# Merge/join operations combine lineage from both sources
merged = pd.merge(df, df2, on='key')
concatenated = pd.concat([df, df2])
```

### Strict vs Relaxed Mode

**Relaxed Mode** (default):
- Writing to new outputs auto-registers them in `datasets.yaml`
- More flexible for exploratory work

**Strict Mode**:
- All reads and writes must be pre-registered in `datasets.yaml`
- Ensures complete documentation of data operations
- Enable via `strict=True` parameter or `SUNSTONE_DATAFRAME_STRICT=1` environment variable

```python
# Enable strict mode
df = pd.read_csv('data.csv', project_path=PROJECT_PATH, strict=True)

# Or globally
import os
os.environ['SUNSTONE_DATAFRAME_STRICT'] = '1'
```

### Validation Tools

Check notebooks for correct import usage:

```python
import sunstone

# Check a single notebook
result = sunstone.check_notebook_imports('analysis.ipynb')
print(result.summary())

# Check all notebooks in project
results = sunstone.validate_project_notebooks('/path/to/project')
for path, result in results.items():
    if not result.is_valid:
        print(f"\n{path}:")
        print(result.summary())
```

## Advanced Usage

### Direct DataFrame API

For more control, use the DataFrame class directly:

```python
from sunstone import DataFrame

# Read with explicit parameters
df = DataFrame.read_csv(
    'data.csv',
    project_path='/path/to/project',
    strict=True
)

# Apply custom operations with lineage tracking
result = df.apply_operation(
    lambda d: d[d['value'] > 100],
    description="Filter high-value rows"
)

# Access underlying pandas DataFrame
pandas_df = result.data
```

### Managing datasets.yaml Programmatically

```python
from sunstone import DatasetsManager, FieldSchema

manager = DatasetsManager('/path/to/project')

# Find datasets
dataset = manager.find_dataset_by_slug('school-data')
dataset = manager.find_dataset_by_location('data/schools.csv')

# Add new output dataset
manager.add_output_dataset(
    name='Analysis Results',
    slug='analysis-results',
    location='outputs/results.csv',
    fields=[
        FieldSchema(name='category', type='string'),
        FieldSchema(name='count', type='integer'),
        FieldSchema(name='avg_value', type='number')
    ],
    publish=True
)
```

## Documentation

- [Contributing Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [API Reference](#api-reference) (below)

## API Reference

### pandas Module

Drop-in replacement for pandas with lineage tracking:

- `read_csv(filepath, project_path, strict=False, **kwargs)`: Read CSV with lineage
- `read_json(filepath, project_path, strict=False, **kwargs)`: Read JSON with lineage
- `merge(left, right, **kwargs)`: Merge DataFrames with combined lineage
- `concat(dfs, **kwargs)`: Concatenate DataFrames with combined lineage

### DataFrame Class

Main class for working with data:

- `read_csv(filepath, project_path, strict=False, **kwargs)`: Read CSV with lineage tracking
- `to_csv(path, slug, name, publish=False, **kwargs)`: Write CSV and register
- `merge(right, **kwargs)`: Merge with another DataFrame
- `join(other, **kwargs)`: Join with another DataFrame
- `concat(others, **kwargs)`: Concatenate DataFrames
- `apply_operation(operation, description)`: Apply transformation with lineage
- `.data`: Access underlying pandas DataFrame
- `.lineage`: Access lineage metadata

### DatasetsManager Class

Manage `datasets.yaml` files:

- `find_dataset_by_location(location, dataset_type='input')`: Find by file path
- `find_dataset_by_slug(slug, dataset_type='input')`: Find by slug
- `get_all_inputs()`: Get all input datasets
- `get_all_outputs()`: Get all output datasets
- `add_output_dataset(...)`: Register new output
- `update_output_dataset(...)`: Update existing output

### Validation Functions

- `check_notebook_imports(notebook_path)`: Validate a single notebook
- `validate_project_notebooks(project_path)`: Validate all notebooks in project

### Exceptions

- `SunstoneError`: Base exception
- `DatasetNotFoundError`: Dataset not found in datasets.yaml
- `StrictModeError`: Operation blocked in strict mode
- `DatasetValidationError`: Validation failed
- `LineageError`: Lineage tracking error

## Environment Variables

- `SUNSTONE_DATAFRAME_STRICT`: Set to `"1"` or `"true"` to enable strict mode globally

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

### Running Tests

```bash
uv run pytest
```

### Type Checking

```bash
uv run mypy src/sunstone
```

### Linting and Formatting

```bash
uv run ruff check src/sunstone
uv run ruff format src/sunstone
```

## About Sunstone Institute

[Sunstone Institute](https://sunstone.institute) is a philanthropy-funded organization using data and AI to show the world as it really is, and inspire action everywhere.

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/sunstoneinstitute/sunstone-py/issues)

---

Made with ❤️ by [Sunstone Institute](https://sunstone.institute)
