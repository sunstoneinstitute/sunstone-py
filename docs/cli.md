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

# Validate specific datasets (positional slugs or --dataset, repeatable)
sunstone dataset validate school-data summary-data
sunstone dataset validate --dataset school-data --dataset summary-data

# Strict: reject unknown keys and check Data Package property values
sunstone dataset validate --strict

# Validate with custom file location
sunstone dataset validate -f path/to/datasets.yaml
```

**Validation checks (always):**

- Required fields (`title`, `name`, `path`, and `schema.fields` for `type: table`)
- Field types are Table Schema types or plugin-registered types
- Duplicate names
- SPDX license identifiers
- Proper YAML structure

**Additional checks with `--strict`** (see [Validating datasets.yaml](datasets-yaml.md)):

- Keys: lint rules R301-R303 (unknown key, undeclared prefix, term not in a shipped vocabulary), on the normalized document
- Values of Data Package properties (field constraints, `package.version`, `contributors`, dialect blocks, ...) validate against the official v2 profiles

With `--dataset` or positional slugs, only those datasets are checked; package-level and top-level checks are skipped. Use `--strict` in CI to keep `datasets.yaml` clean.

**Example output:**
```
✓ datasets.yaml is valid (strict)
```

**Example error:**
```
Validation errors:
  - outputs[0]: missing required field 'fields'
  - inputs[1].fields[2]: invalid type 'text' (must be one of: any, array, boolean, date, datetime, duration, geojson, geopoint, integer, number, object, string, time, year, yearmonth)
  - inputs[1]: unknown key 'notes' (not a Data Resource property or a sunstone dataset key; custom metadata keys need a prefix such as 'si:notes')
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

MUST rules that are new or stricter in 1.20 (R102, R104 and all R3xx rules) are warnings in 1.x and become errors in 2.0.

| Rule | Level | Severity | Description |
|------|-------|----------|-------------|
| R001 | MUST | error | Dataset missing `title` |
| R002 | MUST | error | Dataset missing `name` |
| R003 | MUST | error | Dataset missing `path` |
| R004 | SHOULD | warning | Dataset missing `description` |
| R005 | MUST | error | Dataset missing license (input: `source.dct:license`; output: `licenses`, package `licenses`) |
| R006 | MUST | error | License is not a recognised SPDX or allow-list identifier |
| R007 | MUST | error | Field missing `name` |
| R008 | MUST | error | Field missing `type` |
| R009 | MUST | error | Malformed `lint.disable` entry (cannot itself be suppressed) |
| R010 | MUST NOT | error | Output license is NoDerivatives (`CC-BY-ND-*`, `CC-BY-NC-ND-*`), unless the output declares `prov:wasQuotedFrom` |
| R101 | SHOULD | warning | Input missing `source` block |
| R102 | MUST | warning (1.x) | Source missing `title`, `dct:publisher` (with `rdfs:label`), a link (`"@id"`, `dcat:downloadURL` or `dcat:landingPage`) or `dct:license` |
| R103 | SHOULD | warning | Numeric field missing `si:unit` |
| R104 | MUST | warning (1.x) | Dataset `name` not in kebab-case |
| R105 | SHOULD | warning | Published output field missing `description` |
| R201 | INFO | info | Generic field name (`total`, `value`, ...) without a substantive description |
| R202 | INFO | info | Generic dataset title (`data`, `output`, ...) |
| R301 | MUST | warning (1.x) | Key is not a Data Package property, a config key or an RDF property |
| R302 | MUST | warning (1.x) | RDF prefix not declared |
| R303 | MUST | warning (1.x) | Term does not exist in a shipped vocabulary |
| R304 | MUST NOT | warning (1.x) | Deprecated key; run `sunstone migrate` |
| R305 | MUST | warning (1.x) | Dataset has both `slug` and `title` |
| R306 | MUST | warning (1.x) | New-form keys without `min_sunstone_version` >= 1.20.0 |
| R307 | MUST NOT | warning (1.x) | RDF property duplicates a Data Package key or a generated value (`dct:title`, `qudt:unit`, ...) |
| R308 | MUST | warning (1.x) | `include` file is missing, has a nested `include`, a document-level key or a duplicate dataset name |
| R311 | SHOULD | warning | Source missing `skos:altLabel` on the publisher, `dct:issued` or `dct:modified`; a publication also `dct:creator` and `"@id"` |
| R312 | MUST | warning (1.x) | Input missing `prov:generatedAtTime` or `prov:wasGeneratedBy.dct:type` |
| R313 | MUST | warning (1.x) | Published output has no sources |
| R314 | SHOULD | warning | Published output missing `dct:temporal`, `dct:spatial` or `dcat:theme` |
| R315 | MUST NOT | warning (1.x) | `doi.org` URL in `dcat:downloadURL` or `dcat:landingPage` (a DOI goes in `"@id"`) |
| R316 | SHOULD | warning | Field source object missing `title`, `dct:publisher` (with `rdfs:label`), a link or `dct:license` |
| R317 | SHOULD | warning | Input field sources repeat the input's own source (field sources are for per-column upstream sources) |
| R318 | SHOULD | warning | Output field source repeats the output's only resolved source |
| R321 | SHOULD | warning | Output has no lock entry with sources and activity |
| R322 | MUST | warning (1.x) | Lock source references an unknown dataset |
| R323 | MUST NOT | warning (1.x) | Inline `lineage` in datasets.yaml |
| R331 | MUST | warning (1.x) | Field type not registered |
| R341 | SHOULD | warning | `si:unit` is neither a Pint unit nor a QUDT IRI |
| R351 | MUST | warning (1.x) | Package missing `title` when publishing |
| R361 | SHOULD | warning | No top-level `dcat-si:methodology` (project does not publish) |
| R362 | MUST | warning (1.x) | No top-level `dcat-si:methodology` while publishing a package |

MUST rules are errors (exit non-zero), SHOULD rules are warnings (exit zero unless `--warnings-as-errors`), INFO rules are informational. `--json` output carries `path` and `fix` for every violation.

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
[R005] ERROR inputs[0].source.dct:license: missing license
    hint: Add an SPDX license identifier (e.g. 'CC-BY-4.0', 'MIT').
[R103] WARNING outputs[0].schema.fields[2]: numeric field 'enrollment' has no unit
    hint: Add an 'si:unit:' (e.g. 'meter', 'USD'), or accept the lock-file unit if derived from arithmetic.
[R104] WARNING inputs[1].name: name 'School_Data' is not kebab-case
    hint: Use lowercase ASCII letters/digits separated by single hyphens.

Suppressed by lint.disable (1):
  [R201] outputs[0].schema.fields[0]: generic field name 'value' without a substantive description
      reason: Column name fixed by upstream contract

Summary: 1 error(s), 2 warning(s), 0 info, 1 suppressed
```

## Migrating key names

```bash
sunstone migrate            # rewrite datasets.yaml, include files and datasets.lock.yaml
sunstone migrate --dry-run  # report only
```

Comments and order are kept; running it twice changes nothing. Keys that are neither Data Package properties, config keys nor RDF properties are listed with suggestions from `sunstone vocab search`.

## Finding keys and terms

```bash
sunstone vocab search "attributed"                    # prov:wasAttributedTo ...
sunstone vocab search "download url" --at inputs.source
sunstone vocab search --at inputs.schema.fields       # every allowed key at that level
sunstone vocab search "publisher" --json
```

Output lines are `curie  IRI  label: definition`. `--at` takes a dotted path without array markers (`inputs.source`, `outputs.schema.fields`).

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
# Push to configured destination (--env defaults to prod; blob-store pushes to prod need --yes)
sunstone package push --yes

# Push to the dev environment (if publish.to not set)
sunstone package push --env dev

# Push to a sunstone: namespace on a branch
sunstone package push --env dev --branch my-feature

# Override destination
sunstone package push --env dev -d gs://my-bucket/datasets/project-name/

# Use custom datasets file
sunstone package push --env dev -f path/to/datasets.yaml
```

**Options:**

| Option | Meaning |
|---|---|
| `--env` | Target environment, as configured with `sunstone env`. Default `prod`. |
| `--branch` | Target branch for `sunstone:` pushes. Default: `GITHUB_HEAD_REF`, `GITHUB_REF_NAME`, then the current git branch. |
| `--yes` | Confirm a push to a protected ref or to the prod blob store. |
| `--force` | Allow force operations: incompatible schema, version overwrite, deletes. |
| `--replace` | Retract metadata not in this push (a force operation). |

`sunstone:` destinations need a package-push plugin (see [sunstone-push.md](sunstone-push.md)).

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
sunstone package push --env dev -d "gs://${BUCKET}/datasets/${PROJECT}/"
```

**Example output:**
```
✓ Uploaded datasets/countries/datapackage.json
✓ Uploaded outputs/current_countries.csv

✓ Package pushed to: gs://my-bucket/datasets/countries/
```

## License Commands

`sunstone license` inspects and audits the licenses declared in `datasets.yaml`. Use it alongside the lint rules `R005` (missing license) and `R006` (unrecognised SPDX identifier) — lint catches *missing* and *malformed* licenses, the `license` subcommand catches *incompatible* ones.

The compatibility engine is rules-based and consults an embedded registry of common research-data and software licenses (CC family including ND, CC0, ODC-By, ODbL, PDDL, OGL-3.0, NLOD, GODL-India, US-PD, MIT, Apache, BSD, GPL, LGPL, MPL). See [Concepts → License Compatibility](concepts.md#license-compatibility) for the rule reference.

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
  run: sunstone dataset validate --strict
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
sunstone package push --env $ENV --yes
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
