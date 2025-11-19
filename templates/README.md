# Sunstone Analysis Templates

This directory contains templates for starting new data analysis projects with proper Sunstone integration.

## Templates

### `analysis_notebook.ipynb` - Jupyter Notebook Template

A Jupyter notebook template with the correct setup for Sunstone's lineage tracking.

**Usage:**
```bash
# Copy to your project directory
cp templates/analysis_notebook.ipynb /path/to/YourProject/analysis.ipynb

# Open in Jupyter
cd /path/to/YourProject
jupyter notebook analysis.ipynb
```

**Features:**
- Pre-configured with `from sunstone import pandas as pd`
- Examples of loading data from datasets.yaml
- Data transformation patterns
- Dataset merging/concatenation
- Saving results with lineage tracking
- Import validation

### `analysis_notebook.py` - Marimo Notebook Template

A Marimo reactive notebook template with the same Sunstone integration.

**Usage:**
```bash
# Copy to your project directory
cp templates/analysis_notebook.py /path/to/YourProject/analysis.py

# Edit interactively
cd /path/to/YourProject
marimo edit analysis.py

# Or run non-interactively
marimo run analysis.py
```

**Features:**
- Reactive cell execution
- Same pandas-like API as Jupyter template
- Interactive UI components (tables, markdown)
- Full lineage tracking
- Non-interactive execution support

## Key Differences

### Jupyter
- Traditional notebook format (.ipynb)
- Sequential cell execution
- Widely supported
- Rich output formats

### Marimo
- Python file format (.py)
- Reactive execution (cells auto-update)
- Version control friendly
- Built-in UI components
- Can run as app or script

## Common Pattern

Both templates follow the same workflow:

1. **Import**: `from sunstone import pandas as pd`
2. **Set project path**: `PROJECT_PATH = Path.cwd()`
3. **Load data**: `df = pd.read_csv('input.csv', project_path=PROJECT_PATH)`
4. **Transform**: Use familiar pandas operations
5. **Save**: `df.to_csv('output.csv', slug='output-data', name='Output Data')`

## Requirements

### Jupyter
```bash
uv add jupyter pandas sunstone-py
```

### Marimo
```bash
uv add marimo pandas sunstone-py
```

## See Also

- [Main Documentation](../README.md)
- [Contributing Guide](../CONTRIBUTING.md)
- [Validation Tools Documentation](../src/sunstone/validation.py)
