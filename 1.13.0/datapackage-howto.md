# Data Packages How-To

This guide explains how to configure `datasets.yaml` to define, build, and publish data packages using the `sunstone` CLI.

## Overview

A Sunstone project's `datasets.yaml` declares **inputs** (source data), **outputs** (produced data), and **packages** (what to publish and where). The `sunstone package build` and `sunstone package push` commands use this configuration to produce [Data Package v2](https://datapackage.org/) bundles.

## Inputs and Outputs

Every project starts with `inputs:` and `outputs:` sections. Inputs describe the raw data you consume; outputs describe what your scripts produce.

```yaml
inputs:
  - name: Raw Survey Data
    slug: raw-survey-data
    location: inputs/survey_raw.csv
    source:
      name: National Statistics Office
      location:
        data: https://example.org/survey-2025.csv
      attributedTo: "National Statistics Office"
      acquiredAt: 2025-06-01
      acquisitionMethod: manual-download
      license: CC-BY-4.0
    fields:
      - name: respondent_id
        type: integer
      - name: region
        type: string
      - name: score
        type: number

outputs:
  - name: Survey Summary
    slug: survey-summary
    location: outputs/survey_summary.csv
    fields:
      - name: region
        type: string
      - name: mean_score
        type: number
      - name: respondent_count
        type: integer
```

Inputs need a `source:` block to record provenance. Outputs get their lineage tracked automatically when you write data using `sunstone.pandas`.

## Single Package

For projects that produce one data package, use the singular `package:` key with a top-level `publish:` block:

```yaml
package:
  title: Regional Survey Results
  description: Aggregated survey scores by region.
  version: "1.0.0"
  license: CC-BY-4.0
  keywords:
    - survey
    - regional-statistics
  contributors:
    - title: Data Team
      roles:
        - creator

publish:
  enabled: true
  to: gs://my-bucket/datasets/survey-results/

inputs:
  - name: Raw Survey Data
    slug: raw-survey-data
    location: inputs/survey_raw.csv
    # ... fields, source, etc.

outputs:
  - name: Survey Summary
    slug: survey-summary
    location: outputs/survey_summary.csv
    # ... fields
```

When you run `sunstone package build`, all outputs are bundled into a single `datapackage.json`. When you run `sunstone package push`, everything is uploaded to the `publish.to` destination.

### Publish options

| Field | Description |
|-------|-------------|
| `enabled` | Set to `true` to enable publishing. |
| `to` | Destination URL (e.g. `gs://bucket/path/`, `s3://bucket/path/`). Supports `${VAR}` expansion. |
| `as` | Optional public URL base. If set, resource paths in `datapackage.json` use this instead of the upload URL. |
| `flatten` | If `true`, strip subdirectories from file paths when uploading (e.g. `outputs/data.csv` becomes `data.csv`). |

## Multiple Packages

When a project produces datasets that should be published as separate packages (different audiences, licenses, or destinations), use the plural `packages:` key:

```yaml
packages:
  - name: survey-public
    title: Public Survey Results
    description: Anonymized regional aggregates.
    version: "1.0.0"
    license: CC-BY-4.0
    datasets:
      - survey-summary
    publish:
      enabled: true
      to: gs://public-bucket/survey/

  - name: survey-internal
    title: Internal Survey Data
    description: Full survey data with respondent details.
    version: "1.0.0"
    datasets:
      - survey-summary
      - survey-detailed
    publish:
      enabled: true
      to: gs://internal-bucket/survey/

inputs:
  - name: Raw Survey Data
    slug: raw-survey-data
    location: inputs/survey_raw.csv
    # ...

outputs:
  - name: Survey Summary
    slug: survey-summary
    location: outputs/survey_summary.csv
    # ...

  - name: Survey Detailed
    slug: survey-detailed
    location: outputs/survey_detailed.csv
    # ...
```

### Key differences from single package

- Each entry **must** have `name` and `datasets`.
- `datasets` is a list of slugs referencing entries in `inputs:` or `outputs:`. All slugs are validated at load time.
- Each entry has its own `publish:` block — there is no top-level `publish:` (this is enforced).
- You **cannot** use both `package:` and `packages:` in the same file.
- A dataset slug can appear in multiple packages.

### Build output

With multiple packages, `sunstone package build` creates one file per package:

```
datapackage.json        # first package
datapackage.1.json      # second package
```

### Push behavior

`sunstone package push` iterates over each package that has `publish.enabled: true` and uploads its datasets and `datapackage.json` to the configured destination.

## Package Metadata

Both `package:` and `packages:` entries support the same metadata fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Human-readable package title. |
| `description` | string | Longer description (supports multiline YAML). |
| `version` | string | Semantic version (e.g. `"1.0.0"`). |
| `license` | string | SPDX license identifier. |
| `keywords` | list | Search keywords. |
| `contributors` | list | People or organizations (each with `title`, optional `roles`, `path`, `email`). |
| `homepage` | string | URL to project homepage. |
| `id` | string | Globally unique identifier (URI, DOI, etc.). |
| `image` | string | URL to a representative image. |

## Putting It All Together

A typical project lifecycle:

1. **Define inputs** with source provenance in `datasets.yaml`.
2. **Write your analysis** using `sunstone.pandas` — lineage is tracked automatically.
3. **Define outputs** with field schemas.
4. **Add package configuration** (`package:` or `packages:`).
5. **Validate**: `sunstone dataset validate`
6. **Build locally**: `sunstone package build`
7. **Publish**: `sunstone package push`

### Minimal complete example

```yaml
package:
  title: UN Member States
  version: "1.0.0"
  license: CC-BY-4.0

publish:
  enabled: true
  to: gs://my-bucket/datasets/un-members/

inputs:
  - name: Official UN Member States
    slug: official-un-member-states
    location: inputs/un_member_states_raw.csv
    source:
      name: United Nations
      location:
        data: https://example.org/member_states.csv
      attributedTo: "United Nations"
      acquiredAt: 2025-10-08
      acquisitionMethod: manual-download
      license: CC-BY-NC-3.0-IGO
    fields:
      - name: Member State
        type: string
      - name: ISO Code
        type: string

outputs:
  - name: Current UN Member States
    slug: current-un-member-states
    location: outputs/current_un_member_states.csv
    fields:
      - name: Country
        type: string
      - name: ISO Code
        type: string
      - name: Date of Admission
        type: date
```

Run the workflow:

```bash
# Run your analysis script
uv run python create_un_members_dataset.py

# Validate
sunstone dataset validate

# Build the datapackage.json locally
sunstone package build

# Push to cloud storage
sunstone package push
```
