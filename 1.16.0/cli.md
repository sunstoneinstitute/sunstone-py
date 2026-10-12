# CLI Guide

The `sunstone` command-line interface provides tools for managing datasets and building data packages.

## Installation

The CLI is automatically installed with sunstone-py:

```bash
uv add sunstone-py

# Verify installation
sunstone --version
```

## Environment Commands

`sunstone env` manages cascading TOML configuration that overlays values
on `os.environ` for CLI invocations and Python sessions that call
`sunstone.activate_environment()`. Environments are useful for storing
catalog URLs, warehouse names, region settings, and `op://` references
to secrets without committing them to `datasets.yaml`.

**Config file precedence (highest wins for active-environment selection):**

1. `SUNSTONE_DATA_ENV` env var.
2. `.sunstone/data_platform.toml` (project — walked up from cwd).
3. `~/.config/sunstone/data_platform.toml` (user).
4. `/etc/sunstone/data_platform.toml` (system).

Within an environment definition, field-level merging follows the same
order — project entries override user entries override system entries.

### Show Active Environment

```bash
sunstone env
```

Lists all defined environments and marks the active one. Output:

```
Active: dev (from /Users/me/.config/sunstone/data_platform.toml)

* dev          3 keys, sections: data-platform   (/Users/me/.config/sunstone/data_platform.toml)
  prod         2 keys                            (/etc/sunstone/data_platform.toml)
```

### Switch Active Environment

```bash
# Set the active environment in the project file
sunstone env use dev

# Set it in the user file instead
sunstone env use dev --user
```

### Add an Environment

`KEY=VAL` entries with a `.` in the key are written to plugin-namespaced
subtables — handy for per-plugin configuration like
`data-platform.warehouse=main`.

```bash
# User scope (default)
sunstone env add dev CATALOG_URL=https://data.dev.example.com

# Mix top-level scalars and a subtable entry
sunstone env add dev data-platform.warehouse=main GIT_BRANCH=main

# Write to project or system scope instead
sunstone env add dev CATALOG_URL=https://... --scope project
sunstone env add dev CATALOG_URL=https://... --scope system

# Replace an existing entry
sunstone env add dev CATALOG_URL=https://... --overwrite
```

`--scope` accepts `user` (default), `project`, or `system` and applies
to `add`, `set`, `unset`, and `remove`.

### Update an Environment

`env set` merges entries into an existing environment without touching
unspecified keys.

```bash
sunstone env set dev CATALOG_URL=https://new.example.com
sunstone env set dev data-platform.warehouse=staging --scope project
```

If the same environment is also defined in a higher-precedence layer,
the CLI warns that the update will be shadowed.

### Remove Entries

```bash
# Remove specific keys (dotted keys target subtables; the subtable is
# deleted if it ends up empty)
sunstone env unset dev CATALOG_URL data-platform.warehouse

# Remove the entire environment
sunstone env remove dev
sunstone env remove dev --scope system
```

### Credential References

Values of the form `op://vault/item/field` are resolved through 1Password
CLI at activation time, so secrets stay out of version control. Real env
vars still win — if `CATALOG_URL` is already set in the shell, the
environment value is left alone.

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

## Lint Command

`sunstone lint` checks `datasets.yaml` against the Sunstone Minimum Viable Metadata recommendations. It complements `sunstone dataset validate` (which checks structure and types) by flagging missing metadata that hurts reproducibility and discoverability.

```bash
# Lint the current project
sunstone lint

# Lint a project at a specific path
sunstone lint -p path/to/project

# Use a non-default datasets file
sunstone lint -f config/my-datasets.yaml

# Run only specific rules
sunstone lint --rules R005,R104

# Treat warnings as errors (useful in CI)
sunstone lint --warnings-as-errors

# Machine-readable output
sunstone lint --json
```

### Rules

| ID | Severity | Title |
|------|----------|-------|
| R001 | error | Dataset missing `name` |
| R002 | error | Dataset missing `slug` |
| R003 | error | Dataset missing `location` |
| R004 | error | Dataset missing `description` |
| R005 | error | Dataset missing license (input: `source.license`; output: dataset, `package.license`, or matching `packages[]` entry) |
| R006 | error | License is not a recognised SPDX or allow-list identifier |
| R007 | error | Field missing `name` |
| R008 | error | Field missing `type` |
| R009 | error | Malformed `lint.disable` entry (cannot itself be suppressed) |
| R101 | warning | Input missing `source` block |
| R102 | warning | Source block malformed or missing required keys |
| R103 | warning | Numeric field missing `unit` |
| R104 | warning | Slug not in kebab-case |
| R105 | warning | Published output field missing `description` |
| R201 | info | Generic field name (`total`, `value`, ...) without a substantive description |
| R202 | info | Generic dataset name (`data`, `output`, ...) |

R001–R009 are errors (exit non-zero), R101–R105 are warnings (exit zero unless `--warnings-as-errors`), R201–R202 are informational.

### Suppressing Rules

Specific findings can be suppressed in `datasets.yaml` with a written justification:

```yaml
lint:
  disable:
    R104: "Slug mirrors the upstream UN identifier 'A_HRC_RES'"
    R103: "Pure-count column, unit would be misleading"
```

Suppressed findings stay in the report under a separate `suppressed` list so reviewers can audit the reasons later. R009 itself cannot be suppressed — it's the rule that catches malformed suppressions.

### Programmatic Use

```python
from sunstone import lint_project

report = lint_project('/path/to/project')

if report.errors:
    for v in report.errors:
        print(f"{v.rule_id} {v.location}: {v.message}")

# Suppressed findings (still tracked for audit)
for v in report.suppressed:
    reason = report.suppressions.get(v.rule_id, "")
    print(f"  [{v.rule_id}] suppressed because: {reason}")
```

### Example Output

```
[R005] ERROR inputs[0].source.license: missing license
    hint: Add an SPDX license identifier (e.g. 'CC-BY-4.0', 'MIT').
[R103] WARNING outputs[0].fields[2]: numeric field 'enrollment' has no unit
    hint: Add a 'unit:' (e.g. 'meter', 'USD'), or accept the lock-file unit if derived from arithmetic.
[R104] WARNING inputs[1].slug: slug 'School_Data' is not kebab-case
    hint: Use lowercase ASCII letters/digits separated by single hyphens.

Suppressed by lint.disable (1):
  [R201] outputs[0].fields[0]: generic field name 'value' without a substantive description
      reason: Column name fixed by upstream contract

Summary: 1 error(s), 2 warning(s), 0 info, 1 suppressed
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

Pushing to `gs://` requires the optional GCS extra (`s3://`/`r2://` need `[s3]`):

```bash
uv add 'sunstone-py[gcs]'
```

Without it, the push fails with "No URL handler found for: gs://…".

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

## License Commands

`sunstone license` inspects and audits the licenses declared in `datasets.yaml`. Use it alongside the lint rules `R005` (missing license) and `R006` (unrecognised SPDX identifier) — lint catches *missing* and *malformed* licenses, the `license` subcommand catches *incompatible* ones.

The compatibility engine is rules-based and consults an embedded registry of common research-data licenses (CC family, CC0, ODC-By, ODbL, PDDL, OGL-3.0, NLOD, and US-PD `LicenseRef-*` entries). See [Concepts → License Compatibility](concepts.md#license-compatibility) for the rule reference.

### List Licenses

Show every license referenced in the project and which datasets declare it:

```bash
# Default datasets.yaml in current directory
sunstone license list

# Custom file or project directory
sunstone license list -f path/to/datasets.yaml

# Machine-readable output
sunstone license list --json
```

**Example output:**

```
CC-BY-4.0
  - input:un-members
  - input:world-bank-gdp
CC-BY-SA-4.0
  - output:enriched-members
```

Output licenses are resolved to their *effective* license — explicit `license:` on the dataset, otherwise the matching `packages[]` entry, otherwise the top-level `package.license`.

### Check License Compatibility

Verify that each output's declared license is compatible with the licenses of every source dataset in its `wasDerivedFrom` chain:

```bash
# Check every output
sunstone license check

# Check a single output
sunstone license check enriched-members

# Machine-readable output (for CI)
sunstone license check --json
```

Exits non-zero if any output has a conflict, so it slots into CI alongside `sunstone lint` and `sunstone dataset validate`.

**Example output (compatible):**

```
enriched-members: target=CC-BY-SA-4.0 status=compatible
public-summary: target=CC-BY-4.0 status=compatible
```

**Example output (conflict):**

```
nc-derived: target=CC-BY-4.0 status=conflict
  conflict: CC-BY-NC-4.0 is NonCommercial: derivatives must also be NonCommercial, not CC-BY-4.0
  suggestions: CC-BY-NC-4.0, CC-BY-NC-SA-4.0, CC-BY-NC-3.0-IGO
```

**Skipped outputs:**

The check is skipped (status `skipped`) for an output when it has no source licenses to consider, or when no effective target license can be resolved. Skipped outputs do not fail the command.

**Unknown licenses:**

A `LicenseRef-*` identifier that is not in the embedded registry is reported as an *unknown source* on the JSON result and excluded from rules-based comparisons — callers (or reviewers) must decide how to treat it.

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
