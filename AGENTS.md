# Sunstone Projects Library

This directory contains a Python library that implements Sunstone's
data science workflow.

## Overview

The `sunstone-py` package provides:
- **DataFrame wrapper**: Pandas-compatible DataFrame with automatic lineage tracking
- **Dataset management**: Integration with `datasets.yaml` for all I/O operations
- **Validation tools**: Check notebooks and scripts for correct import usage
- **Pandas-like API**: Familiar interface for data scientists via `from sunstone import pandas as pd`

## Package Structure

```
src/sunstone/
├── __init__.py           # Main package exports
├── pandas.py             # Pandas-like API (import as pd)
├── dataframe.py          # DataFrame wrapper with lineage tracking
├── datasets.py           # Dataset management and YAML integration
├── lineage.py            # Lineage metadata models
├── validation.py         # Import validation utilities
└── exceptions.py         # Custom exceptions

templates/
└── analysis_notebook.ipynb  # Template for new analyses
```

## Usage for Data Scientists

### Recommended Pattern

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Load data (must be in datasets.yaml)
df = pd.read_csv('input.csv', project_path=PROJECT_PATH)

# Transform using familiar pandas operations
result = df[df['value'] > 100].groupby('category').sum()

# Save with lineage tracking
result.to_csv(
    'output.csv',
    slug='output-data',
    name='Output Data',
    index=False
)
```

### Key Differences from Plain Pandas

1. **Explicit project_path required**: `read_csv()` requires `project_path` parameter
2. **Dataset registration**: All reads/writes must be in `datasets.yaml`
3. **Access underlying data**: Use `.data` to access the pandas DataFrame directly
4. **Save with metadata**: `to_csv()` requires `slug` and `name` for new outputs

## Development

### Installing in Other Projects

From a Sunstone project directory:
```bash
# Manually add to pyproject.toml dependencies:
# "sunstone-py @ file:///${PROJECT_ROOT}/../lib"

uv sync
```

### Running Tests

```bash
cd lib
uv run pytest
```


