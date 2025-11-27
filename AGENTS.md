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
.
├── pyproject.toml
├── README.md
├── src
│   └── sunstone
│       ├── __init__.py
│       ├── _release.py
│       ├── dataframe.py
│       ├── datasets.py
│       ├── exceptions.py
│       ├── lineage.py
│       ├── pandas.py
│       ├── py.typed
│       └── validation.py
├── templates
│   ├── analysis_notebook.ipynb
│   ├── analysis_notebook.py
│   └── README.md
└── tests
    ├── conftest.py
    ├── test_dataframe.py
    ├── test_datasets.py
    ├── test_lineage_persistence.py
    ├── test_pandas_compatibility.py
    └── testdata
        └── UNMembersProject
            ├── create_un_members_dataset.py
            ├── datasets.yaml
            ├── inputs
            │   └── official_un_member_states_raw.csv
            ├── outputs
            ├── pyproject.toml
            └── uv.lock
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
uv add sunstone-py
uv sync
```

### Running Tests

```bash
cd lib
uv run pytest
```

### Releasing

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

#### CHANGELOG.md

The CHANGELOG.md format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),

#### Make a Release

To make a new release, run `uv run release` from the main branch.
This will commit a CHANGELOG.md update, add a new version tag, and
push. The `uv run release` command does a patchlevel upgrade by
default, to do a minor or major version upgrade, use the
`--bump` option, for example:

 * `uv run release --bump=patch` - bump patchlevel (v0.8.1 -> v0.8.2)
 * `uv run release --bump-minor` - bump minor version (v0.8.1 -> v0.9.0)
 * `uv run release --bump-major` - bump major version (v0.8.1 -> v1.0.0)
