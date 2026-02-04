# CLI Guide

The `sunstone` command-line interface provides tools for managing datasets and building data packages.

## Installation

The CLI is automatically installed with sunstone-py:

```bash
uv add sunstone-py

# Verify installation
sunstone --version
```

## Dataset Commands

### List Datasets

Show all input and output datasets in your project:

```bash
sunstone dataset list
sunstone dataset list -f path/to/datasets.yaml
```

**Example output:**
```
Inputs:
  - school-data (School Data)
  - teacher-data (Teacher Information)

Outputs:
  - school-summary (School Enrollment Summary) [publish]
  - analysis-results (Analysis Results) [strict, publish]
```

### Validate Datasets

Check that your `datasets.yaml` follows the correct structure:

```bash
# Validate all datasets
sunstone dataset validate

# Validate specific datasets
sunstone dataset validate school-data summary-data

# Validate with custom file location
sunstone dataset validate -f path/to/datasets.yaml
```

**Validation checks:**

- Required fields (name, slug, location, fields)
- Valid field types (string, number, integer, boolean, date, datetime)
- Duplicate slugs
- Proper YAML structure

**Example output:**
```
✓ datasets.yaml is valid
```

**Example error:**
```
Validation errors:
  - outputs[0]: missing required field 'fields'
  - inputs[1].fields[2]: invalid type 'text' (must be one of: string, number, integer, boolean, date, datetime)
  - Dataset 'school-data' not found
```

### Lock Datasets (Enable Strict Mode)

Enable strict mode for datasets to prevent programmatic modifications:

```bash
# Lock specific datasets
sunstone dataset lock school-data summary-data

# Lock all datasets
sunstone dataset lock
```

**Output:**
```
✓ Locked 2 dataset(s): school-data, summary-data
```

When a dataset is locked, any attempt to modify it in `datasets.yaml` will fail with an error. This ensures complete documentation of all data operations.

### Unlock Datasets (Disable Strict Mode)

Disable strict mode to allow programmatic modifications:

```bash
# Unlock specific datasets
sunstone dataset unlock school-data

# Unlock all datasets
sunstone dataset unlock
```

**Output:**
```
✓ Unlocked 1 dataset(s): school-data
```

## Package Commands

### Build Data Package

Create a `datapackage.json` from your `datasets.yaml`:

```bash
# Build with default output (datapackage.json)
sunstone package build

# Specify custom output file
sunstone package build -o path/to/package.json

# Use custom datasets file
sunstone package build -f path/to/datasets.yaml -o package.json
```

This creates a [Data Package v2](https://datapackage.org/) with all publishable output datasets as resources.

**Example output:**
```
  + school-summary
  + analysis-results

✓ Created datapackage.json with 2 resource(s)
```

**Requirements:**
- Only output datasets with `publish.enabled: true` are included
- Output files must exist at their specified locations
- Requires `frictionless` package to be installed

### Push to Google Cloud Storage

Upload your data package and all output datasets to GCS.

**Prerequisites:**

Publishing requires a top-level `publish` configuration in `datasets.yaml`:

```yaml
publish:
  enabled: true
  to: gs://my-bucket/datasets/project-name/
  as: https://data.example.com/project-name/  # optional: public URL base
  flatten: false  # optional, default: false
```

**Commands:**

```bash
# Push to configured destination
sunstone package push

# Push to environment-specific destination (if publish.to not set)
sunstone package push --env prod

# Override destination
sunstone package push -d gs://my-bucket/datasets/project-name/

# Use custom datasets file
sunstone package push -f path/to/datasets.yaml
```

**Path Resolution:**

The `publish.to` field determines where files are uploaded:

1. **Directory path** (no `.json` extension):
   ```yaml
   publish:
     to: gs://bucket/datasets/countries/
   ```
   Uploads to:
   - `gs://bucket/datasets/countries/datapackage.json`
   - `gs://bucket/datasets/countries/outputs/data.csv`

2. **Custom datapackage filename** (ends with `.json`):
   ```yaml
   publish:
     to: gs://bucket/datasets/countries.json
   ```
   Uploads to:
   - `gs://bucket/datasets/countries.json`
   - `gs://bucket/datasets/outputs/data.csv` (relative to datapackage directory)

3. **Flattened structure** (ignores subdirectories in `location`):
   ```yaml
   publish:
     to: gs://bucket/datasets/countries/
     flatten: true
   ```
   Uploads to:
   - `gs://bucket/datasets/countries/datapackage.json`
   - `gs://bucket/datasets/countries/data.csv` (no `outputs/` prefix)

4. **Public URL mapping** (different URLs in datapackage.json vs upload destination):
   ```yaml
   publish:
     to: gs://bucket/datasets/countries/
     as: https://data.example.com/countries/
   ```
   Uploads to GCS:
   - `gs://bucket/datasets/countries/datapackage.json`
   - `gs://bucket/datasets/countries/outputs/data.csv`

   But `datapackage.json` contains public URLs:
   ```json
   {
     "resources": [{
       "path": "https://data.example.com/countries/outputs/data.csv"
     }]
   }
   ```

   This is useful when your GCS bucket is served via a CDN or custom domain.

**Environment variable expansion:**

Destination URLs support `${VAR}` or `${VAR:-default}` syntax:

```yaml
publish:
  to: gs://${BUCKET:-default-bucket}/datasets/${PROJECT}/
```

Or via command line:
```bash
sunstone package push -d "gs://${BUCKET}/datasets/${PROJECT}/"
```

**Example output:**
```
✓ Uploaded datasets/countries/datapackage.json
✓ Uploaded outputs/current_countries.csv

✓ Package pushed to: gs://my-bucket/datasets/countries/
```

## Common Workflows

### Pre-commit Validation

Add validation to your CI/CD pipeline:

```bash
# .github/workflows/validate.yml
- name: Validate datasets
  run: sunstone dataset validate
```

### Lock Datasets for Production

Before deploying to production, lock all datasets:

```bash
sunstone dataset lock
git add datasets.yaml
git commit -m "Lock datasets for production"
```

### Build and Push Pipeline

Automate package building and publishing:

```bash
#!/bin/bash
set -e

# Validate first
sunstone dataset validate

# Build package
sunstone package build

# Push to appropriate environment
ENV=${1:-dev}
sunstone package push --env $ENV
```

## Shell Completion

Enable tab completion for dataset slugs:

```bash
# Bash
eval "$(_SUNSTONE_COMPLETE=bash_source sunstone)"

# Zsh
eval "$(_SUNSTONE_COMPLETE=zsh_source sunstone)"

# Fish
_SUNSTONE_COMPLETE=fish_source sunstone | source
```

After enabling completion, you can tab-complete dataset slugs:

```bash
sunstone dataset validate <TAB>
# Shows: school-data  teacher-data  school-summary  analysis-results
```
