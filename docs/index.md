# Sunstone Python Library

A Python library for managing datasets with lineage tracking in data science projects.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

sunstone-py helps data scientists and researchers build reproducible data pipelines with automatic lineage tracking. It provides a pandas-compatible API that tracks where your data comes from, what operations you perform, and maintains a complete audit trail—all with minimal changes to your existing code.

## Key Features

- **W3C PROV-O Lineage**: Every transformation is recorded using the W3C provenance standard—know exactly where your data came from, what happened to it, and which fields derived from which sources
- **Dataset Management**: Centralized `datasets.yaml` configuration for all data inputs and outputs
- **DataFrame Metadata**: Unified metadata container with per-field annotations (descriptions, units, source tracking)
- **Plugin System**: Extensible URL handlers (local, HTTP, GCS, S3/R2) and format handlers (CSV, JSON, Excel, Parquet, TSV) with entry point discovery
- **Unit-Aware Arithmetic**: Pint integration for column-level unit tracking with automatic compatibility checks and QUDT round-tripping
- **Semantic Metadata**: RDF triple support with automatic prefix expansion for rich dataset descriptions
- **Command-Line Tools**: Validate, lock, and publish datasets with the `sunstone` CLI
- **Pandas-Compatible**: Familiar API via `from sunstone import pandas as pd`—supports CSV, Excel, JSON, and Parquet
- **Strict/Relaxed Modes**: Choose between automatic registration (exploratory) or enforced pre-registration (production)
- **Data Package Publishing**: Build standards-compliant data packages and push to cloud storage
- **Full Type Hints**: Complete type annotation support for better IDE integration and type safety

## Why sunstone-py?

**Problem:** In data science projects, it's hard to track:
- Where did this dataset come from?
- What transformations were applied?
- Which outputs are derived from which inputs?
- Is this analysis reproducible?

**Solution:** sunstone-py automatically tracks all of this as you work, storing metadata in a human-readable `datasets.yaml` file and maintaining lineage through your pandas operations.

## Installation

```bash
# Using uv (recommended)
uv add sunstone-py

# Using pip
pip install sunstone-py
```

### Development Installation

For local development or contributing:

```bash
git clone https://github.com/sunstoneinstitute/sunstone-py.git
cd sunstone-py
uv venv
uv sync
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Installing from Git

To use the latest development version:

```toml
# pyproject.toml
dependencies = [
    "sunstone-py @ git+https://github.com/sunstoneinstitute/sunstone-py.git",
]
```

Or for local development with live changes:

```toml
dependencies = [
    "sunstone-py @ file://${HOME}/git/sunstone-py"
]
```

## Quick Example

```python
from sunstone import pandas as pd
from pathlib import Path

PROJECT_PATH = Path.cwd()

# Read data - lineage automatically tracked
schools = pd.read_csv('data/schools.csv', project_path=PROJECT_PATH)

# Transform using familiar pandas operations
summary = schools[schools['enrollment'] > 100].groupby('district').sum()

# Save with automatic lineage tracking
summary.to_csv(
    'outputs/summary.csv',
    slug='school-summary',
    name='School Enrollment Summary',
    index=False
)

# Check what went into this dataset
print(summary.metadata.lineage.sources)      # Source datasets
print(summary.metadata.lineage.get_licenses())  # Source licenses
```

That's it! The lineage is automatically tracked and saved to `datasets.yaml`.

## What Gets Tracked?

### For Every Dataset

- **Metadata**: Name, description, location, schema
- **Source Attribution**: Where the data came from, when acquired, license
- **Lineage**: Which datasets were used to create this one
- **Operations**: What transformations were applied
- **Versioning**: Content hash and timestamps (only updates when data changes)

### Automatically Generated

When you save a DataFrame, sunstone-py:

1. Registers the dataset in `datasets.yaml` (in relaxed mode)
2. Infers the schema from your data
3. Records all source datasets in the lineage
4. Calculates a content hash (for change detection)
5. Saves operation descriptions

## Getting Started

Ready to dive in? Here's your learning path:

1. **[Quick Start](quickstart.md)** - Get up and running in 5 minutes
2. **[Core Concepts](concepts.md)** - Understand lineage tracking and strict/relaxed modes
3. **[CLI Guide](cli.md)** - Learn the command-line tools for dataset management
4. **[API Reference](api.md)** - Complete API documentation
5. **[Examples](examples.md)** - Real-world usage patterns and workflows

## Common Use Cases

### Research & Academia

- Track data provenance for reproducible research
- Document data sources and transformations for publications
- Share datasets with complete lineage metadata
- Validate analyses before publication

### Production Pipelines

- Enforce dataset registration with strict mode
- Build and publish data packages to cloud storage
- Validate datasets in CI/CD pipelines
- Maintain audit trails for compliance

### Data Science Teams

- Centralized dataset catalog in `datasets.yaml`
- Automatic schema inference and validation
- Track which analyses depend on which datasets
- Share work with complete documentation

## Command-Line Tools

The `sunstone` CLI provides tools for dataset management:

```bash
# List all datasets
sunstone dataset list

# Validate datasets.yaml structure
sunstone dataset validate

# Lock datasets for production (enable strict mode)
sunstone dataset lock

# Build a Data Package
sunstone package build

# Push to Google Cloud Storage
sunstone package push --env prod
```

See the [CLI Guide](cli.md) for complete documentation.

## Key Concepts

### Lineage Tracking (W3C PROV-O)

Every DataFrame automatically tracks:
- **Sources**: Which datasets were read
- **Activities**: Script/notebook executions with agents and timestamps
- **Field Derivations**: Which output columns came from which source datasets
- **Attribution**: Licenses and source information

Lineage propagates through operations like merge, join, concat, and custom transformations. Field-level derivations are auto-populated on read.

### Strict vs Relaxed Mode

- **Relaxed Mode** (default): Auto-registers new datasets, perfect for exploration
- **Strict Mode**: Requires pre-registration, enforces documentation for production

Switch between modes per-operation, globally, or via CLI.

### Dataset Management

All datasets live in `datasets.yaml`:
- **Inputs**: External data sources with attribution
- **Outputs**: Generated datasets with lineage
- **Schemas**: Field names and types
- **Metadata**: Publishing config, strict mode flags

Learn more in [Core Concepts](concepts.md).

## Integration with Data Package Standard

sunstone-py builds on the [Data Package v2](https://datapackage.org/) standard, an open specification for data distribution. You can:

- Build standards-compliant `datapackage.json` files
- Add RDF triples with automatic prefix expansion (DCAT, Dublin Core, schema.org, custom vocabularies)
- Publish to cloud storage (GCS, S3, etc.)
- Integrate with tools that consume Data Packages
- Share data with complete metadata

See [Data Package Standard](datapackage.md) for the full specification.

## Development

### Running Tests

```bash
uv run pytest
```

### Type Checking

```bash
uv run mypy
```

### Linting and Formatting

```bash
uv run ruff check
uv run ruff format
```

### Documentation

This documentation is built with [MkDocs](https://www.mkdocs.org/) and the [Material theme](https://squidfunk.github.io/mkdocs-material/):

```bash
uv run mkdocs serve  # Preview locally
uv run mkdocs build  # Build static site
```

## Support & Contributing

- **Documentation**: [https://sunstoneinstitute.github.io/sunstone-py/](https://sunstoneinstitute.github.io/sunstone-py/)
- **Issues**: [GitHub Issues](https://github.com/sunstoneinstitute/sunstone-py/issues)
- **Source Code**: [GitHub Repository](https://github.com/sunstoneinstitute/sunstone-py)
- **PyPI**: [sunstone-py](https://pypi.org/project/sunstone-py/)

Contributions are welcome! Please feel free to submit issues or pull requests.

## About Sunstone Institute

[Sunstone Institute](https://sunstone.institute) is a philanthropy-funded organization using data and AI to show the world as it really is, and inspire action everywhere.

## License

MIT License - see [LICENSE](https://github.com/sunstoneinstitute/sunstone-py/blob/main/LICENSE) file for details.
