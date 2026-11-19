# Multi-Package Support in datasets.yaml

## Problem

When a project publishes multiple datapackages (e.g. a full and a lite version), each datapackage needs its own title, description, and other top-level metadata. Currently, `package:` metadata is global and `publish:` config controls destinations, but there is no way to give each datapackage its own identity. Per-dataset `publish:` overrides were the only mechanism to create multiple datapackages, and the metadata was always shared.

## Design

### YAML API

Two mutually exclusive forms. Having both `package:` and `packages:` is a validation error.

#### Single package (backward compatible)

```yaml
package:
  title: UN Member States
  version: "1.0.0"
  license: CC-BY-4.0

publish:
  enabled: true
  to: gs://bucket/un-members/

inputs:
  - name: Raw Data
    slug: raw-data
    location: inputs/raw.csv

outputs:
  - name: Clean Data
    slug: clean-data
    location: outputs/clean.csv
    fields:
      - name: country
        type: string
```

- All outputs are implicitly included in the package (existing behavior).
- Inputs are excluded unless they have a per-dataset `publish:` with `enabled: true` (existing behavior).
- Top-level `publish:` is copied into the package as its publish config.
- The datapackage `name` field is auto-derived from the project directory slug.

#### Multiple packages

```yaml
packages:
  - name: un-members-full
    title: UN Member States (Full)
    description: Complete dataset with all fields
    version: "1.0.0"
    license: CC-BY-4.0
    publish:
      enabled: true
      to: gs://bucket/full/
    datasets:
      - clean-data
      - enriched-data

  - name: un-members-lite
    title: UN Member States (Lite)
    description: Lightweight version
    publish:
      enabled: true
      to: gs://bucket/lite/
    datasets:
      - clean-data

inputs:
  - name: Raw Data
    slug: raw-data
    location: inputs/raw.csv

outputs:
  - name: Clean Data
    slug: clean-data
    location: outputs/clean.csv
    fields:
      - name: country
        type: string
  - name: Enriched Data
    slug: enriched-data
    location: outputs/enriched.csv
    fields:
      - name: country
        type: string
      - name: region
        type: string
```

- Each entry requires `name` (the datapackage slug) and `datasets` (list of dataset slugs).
- All other PackageMetadata fields (title, description, version, keywords, license, contributors, homepage, id, image) are optional.
- Each entry has its own optional `publish:` config.
- Datasets not listed in any package are silently excluded from packaging.
- A `datasets:` slug that does not match any input or output is a validation error.

### Validation Rules

1. `package:` and `packages:` together is an error.
2. `packages:` with a top-level `publish:` is an error (each package has its own).
3. Each `packages:` entry must have `name` and `datasets`.
4. A `datasets:` slug that does not exist in inputs or outputs is an error.
5. Per-dataset `publish:` emits a deprecation warning (still functional, will be removed in a future version).

### Data Model

New dataclass in `lineage.py`:

```python
@dataclass
class PackageEntry:
    """A package definition combining metadata, publish config, and dataset membership."""

    name: str
    """Datapackage name/slug (kebab-case identifier)."""

    metadata: PackageMetadata
    """Title, description, version, and other package-level metadata."""

    publish: Optional[PublishConfig] = None
    """Where and how to publish this package."""

    datasets: Optional[list[str]] = None
    """Dataset slugs included in this package. None means all outputs (single-package mode)."""
```

When `datasets` is `None`, the package includes all publishable outputs (the `package:` singular behavior). When it is an explicit list, only those slugs are included.

### Code Changes

#### lineage.py
- Add `PackageEntry` dataclass.
- Revert `package` field from `PublishConfig` (added in the previous commit, superseded by this design).

#### datasets.py
- Add `get_packages() -> list[PackageEntry]` to `DatasetsManager`:
  - If `packages:` is present: parse each entry, validate slugs exist, return list.
  - If `package:` is present: synthesize a single `PackageEntry` with `datasets=None`, copying top-level `publish:` config.
  - If neither is present: return empty list (no packages configured).
  - If both are present: raise a validation error.
- Add `_parse_package_entry()` for parsing individual `packages:` entries.
- Validate that top-level `publish:` is not present when `packages:` is used.

#### cli.py
- Remove `_merge_package_metadata()`.
- Replace `group_datasets_by_destination()` usage in `package_build` and `package_push` with `get_packages()`.
- Update `build_datapackage()` to accept a `PackageEntry` and resolve datasets from it:
  - If `datasets` is `None`: use all publishable outputs (existing behavior).
  - If `datasets` is a list: look up each slug via the manager.
- Emit deprecation warning when per-dataset `publish:` is encountered during parsing.
- `get_effective_publish()` and `group_datasets_by_destination()` remain available for the deprecation period but are no longer the primary path.

### Migration Path

Existing `datasets.yaml` files using `package:` + top-level `publish:` continue to work unchanged. Projects using per-dataset `publish:` overrides to create multiple destinations will see deprecation warnings and should migrate to `packages:`.
