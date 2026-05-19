# Sunstone Projects Library

This directory contains a Python library that implements Sunstone's
data science workflow.

## Overview

The `sunstone-py` package provides:
- **DataFrame wrapper**: Pandas-compatible DataFrame with automatic lineage tracking
- **Dataset management**: Integration with `datasets.yaml` for all I/O operations
- **Plugin system**: Extensible auth, URL handling, and format support via entry points
- **SSRF protection**: Reusable URL validation to prevent server-side request forgery
- **Validation tools**: Check notebooks and scripts for correct import usage
- **Metadata system**: Unified container for dataset-level and field-level metadata that flows through operations to write time
- **Pandas-like API**: Familiar interface for data scientists via `from sunstone import pandas as pd`

## Package Structure

```
.
├── pyproject.toml
├── README.md
├── src
│   └── sunstone
│       ├── __init__.py
│       ├── cli.py
│       ├── context.py
│       ├── dataframe.py
│       ├── datasets.py
│       ├── errors.py
│       ├── exceptions.py
│       ├── handlers.py
│       ├── handlers_gcs.py
│       ├── handlers_s3.py
│       ├── lineage.py
│       ├── packaging.py
│       ├── pandas.py
│       ├── plugins.py
│       ├── py.typed
│       ├── queries.py
│       ├── session.py
│       ├── ssrf.py
│       └── validation.py
├── templates
│   ├── analysis_notebook.ipynb
│   ├── analysis_notebook.py
│   └── README.md
└── tests
    ├── conftest.py
    ├── test_cli.py
    ├── test_context.py
    ├── test_dataframe.py
    ├── test_dataframe_coverage.py
    ├── test_datasets.py
    ├── test_datasets_coverage.py
    ├── test_errors.py
    ├── test_handlers.py
    ├── test_handlers_gcs.py
    ├── test_handlers_s3.py
    ├── test_lineage_flow.py
    ├── test_lineage_persistence.py
    ├── test_metadata.py
    ├── test_packaging.py
    ├── test_pandas_compatibility.py
    ├── test_plugins.py
    ├── test_queries.py
    ├── test_rdf.py
    ├── test_remaining_coverage.py
    ├── test_session.py
    ├── test_ssrf.py
    ├── test_validation.py
    └── testdata
        └── UNMembersProject
            ├── create_un_members_dataset.py
            ├── datasets.yaml
            ├── inputs
            │   └── official_un_member_states_raw.csv
            ├── outputs
            ├── pyproject.toml
            └── uv.lock
```

## Usage for Data Scientists

### Recommended Pattern

```python
from sunstone import pandas as pd
import sunstone
from pathlib import Path

# Configure the project path once. read_csv/read_excel/read_dataset
# pick this up automatically — no need to pass project_path everywhere.
sunstone.set_project_path(Path.cwd())

# Load data (must be in datasets.yaml)
df = pd.read_csv('input.csv')

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

1. **Project path**: `read_csv()`, `read_excel()`, and `read_json()` resolve paths against a project directory containing `datasets.yaml`. Set it once with `sunstone.set_project_path(...)` (recommended for notebooks/scripts), pass it explicitly via the `project_path=` argument, or rely on the `Path.cwd()` fallback. Use `with sunstone.use_project_path(...):` for scoped overrides.
2. **Dataset registration**: All reads/writes must be in `datasets.yaml`
3. **Access underlying data**: Use `.data` to access the pandas DataFrame directly
4. **Save with metadata**: `to_csv()` requires `slug` and `name` for new outputs (can be set via `df.metadata.slug`/`df.metadata.name` or passed as parameters)
5. **Metadata container**: Use `df.metadata` for dataset-level metadata (description, RDF prefixes, custom properties) and `df.set_field_metadata()` for column-level metadata. All metadata propagates through operations and flows to `datasets.yaml` on write.
6. **Lineage via metadata**: Access lineage through `df.metadata.lineage` (the old `df.lineage` accessor is deprecated)

## Plugin System

Reading, writing, and URL fetching are handled by a plugin registry. Built-in handlers
cover CSV, JSON, Excel, Parquet, TSV formats and HTTP/HTTPS, local file, GCS, and S3/R2 URLs.
External plugins are discovered via the `sunstone.plugins` entry point group and take priority
over built-ins.

Key modules:
- `plugins.py` — Protocol definitions (`AuthProvider`, `URLHandler`, `FormatHandler`) and `PluginRegistry`
- `handlers.py` — Built-in `BuiltinFormatHandler`, `HttpURLHandler`, and `LocalFileHandler`
- `handlers_gcs.py` — `GcsURLHandler` for `gs://` URLs (requires `sunstone-py[gcs]`)
- `handlers_s3.py` — `S3URLHandler` for `s3://` and `r2://` URLs (requires `sunstone-py[s3]`)
- `packaging.py` — Library functions for building and pushing data packages via URLHandler

URLHandler uses stream-based `open(url, mode) -> BinaryIO | TextIO` matching Python's built-in `open()`.
Plugin config uses cascading precedence: `datasets.yaml` → `pyproject.toml` → environment variables (`SUNSTONE_PLUGIN_<NAME>_<KEY>`).

## Cross-Platform (Windows CI)

CI runs on Windows. Never use `str(path)` for paths written to files like `datasets.yaml` — on Windows this produces backslashes. Use `path.as_posix()` for portable forward-slash paths.

## Development

### Installing in Other Projects

From a Sunstone project directory:
```bash
uv add sunstone-py
uv sync
```

### Running Tests

```bash
uv run pytest
```

### Releasing

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

#### CHANGELOG.md

The CHANGELOG.md format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
but formatted like this:

```
## [M.N.P] - YYYY-MM-DD
- <category>: <one-liner>
- <category>: <one-liner>
...
```

`<category>` is one of Added, Changed, Deprecated, Removed, Fixed, Security
`<one-liner>` is a single sentence (preferrably) describing something that's changelog-worthy

**IMPORTANT**: every time you make a commit, consider whether the change is changelog-worthy, and
if so add an entry to the "[Unreleased]" section of CHANGELOG.md. The changelog is meant for
users, so housekeeping changes (CI, agent instructions, readme, etc) should not go in there.

##### Updating CHANGELOG.md

**Keep it tight.** Each entry is one short line — ideally under ~140 characters. Write for a
user skimming the release page, not for an engineer who wants the full story. Rules:

- One line, one sentence. No subclauses piling up rationale, mechanism, edge cases, and follow-ups.
- Lead with the user-visible change. Skip implementation detail (file paths, internal flags,
  "now patches X at package time") unless it changes how the user interacts with the thing.
- If an existing `[Unreleased]` entry is verbose, rewrite it — don't just copy it forward.
- Details belong in commit messages, `docs/`, `CONTRIBUTORS.md`, etc. The changelog may point
  at them, it doesn't replace them.

#### Make a Release

Use the `/release` command. It auto-detects the bump level from commit history,
generates a changelog entry, confirms with you, then runs the release script.

You can override the bump level: `/release --bump minor`
