# Core Concepts

Understanding the key concepts behind sunstone-py's data management and lineage tracking.

## Asset Envelope

Everything sunstone reads or writes is an `Asset` — a uniform container
with four fields:

- `payload` — the kind-native data: a `pandas.DataFrame`, a NumPy
  `ndarray`, a `dict[str, ndarray]`, a tile pyramid descriptor, or raw
  `bytes` for opaque binaries.
- `kind` — an `AssetKind` enum value (`TABULAR`, `RASTER`, `ARRAY`,
  `TILES`, `BLOB`).
- `metadata` — the unified `Metadata` container (lineage,
  per-component schema, RDF properties, license).
- `extras` — kind-specific accessory info (rasterio profile, CRS, chunk spec).

Two equivalent entry points produce and consume assets:

```python
# Kind-agnostic — works for any AssetKind
asset = sunstone.read('inputs/era5_2024.zarr')
sunstone.write(asset.derive(new_payload, slug='child', name='Child'),
               'outputs/era5_derived.zarr')

# Tabular shortcut — pandas-like API
from sunstone import pandas as pd
df = pd.read_csv('inputs/schools.csv')
df.to_csv('outputs/summary.csv', slug='summary', name='Summary')
```

`sunstone.DataFrame` is a thin facade over an `Asset` of
`kind=AssetKind.TABULAR`; the two paths record identical lineage. Use
the pandas-style API for code that should read like pandas, and the
Asset API for code that needs to be uniform across kinds.

Each kind has its own quickstart:

- [Tabular](pandas.md) — `pandas.DataFrame` payloads (CSV, Parquet, Excel, JSON, TSV).
- [Tensors](tensors.md) — `dict[str, ndarray]` payloads (`.npz`, Zarr, HDF5/NetCDF-4).
- [Images](images.md) — single-`ndarray` rasters (GeoTIFF on the roadmap).
- [Tile pyramids](nbtiles.md) — pre-tiled multi-resolution data.
- [Blob / opaque binaries](formats.md#blob--opaque-binary-formats) —
  `bytes` payloads for PDF, DOCX, PPTX, RTF, plain-text reports, and
  similar artefacts sunstone ingests without interpreting.

`Asset.derive(payload, ..., derived_from=[...])` produces a child asset
and records `prov:wasDerivedFrom` for each parent. Slug and name do
*not* inherit — the child is a new dataset.

## Pandas-Like API

sunstone-py provides a drop-in replacement for pandas that adds lineage tracking:

```python
import sunstone
from sunstone import pandas as pd

# Configure the default project path once
sunstone.set_project_path('/path/to/project')

# Works like pandas, but tracks lineage
df = pd.read_csv('input.csv')
df2 = pd.read_csv('input2.csv')

# All pandas operations work
filtered = df[df['value'] > 100]
grouped = df.groupby('category').sum()

# Merge/join operations combine lineage from both sources
merged = pd.merge(df, df2, on='key')
concatenated = pd.concat([df, df2])
```

### Key Differences from Plain Pandas

1. **Project path configuration**: Reads resolve paths against a project directory containing `datasets.yaml`. Set it once with `sunstone.set_project_path(...)`, pass `project_path=` per call, or rely on the `Path.cwd()` fallback. Use `with sunstone.use_project_path(...):` for a scoped override.
2. **Dataset registration**: All reads and writes must correspond to entries in `datasets.yaml`
3. **Access underlying data**: Use `.data` to access the pandas DataFrame directly
4. **Save with metadata**: Write operations require `slug` and `name` for dataset registration

## Strict vs Relaxed Mode

sunstone-py operates in two modes that control how it interacts with `datasets.yaml`:

### Relaxed Mode (Default)

**Behavior:**
- Writing to new outputs auto-registers them in `datasets.yaml`
- More flexible for exploratory work
- Schema is inferred from the data
- Lineage metadata is automatically added

**Use when:**
- Doing exploratory data analysis
- Prototyping new analyses
- Working in notebooks
- Iterating quickly on data transformations

**Example:**
```python
# This will auto-create an entry in datasets.yaml
result.to_csv(
    'outputs/new-analysis.csv',
    slug='new-analysis',
    name='New Analysis Results',
    index=False
)
```

### Strict Mode

**Behavior:**
- All reads and writes must be pre-registered in `datasets.yaml`
- Raises `StrictModeError` if dataset not found
- Ensures complete documentation of data operations
- Validates that lineage matches what's recorded

**Use when:**
- Running production pipelines
- Need reproducibility guarantees
- Working in team environments
- Preparing for publication or sharing

**Enable strict mode:**

```python
# Per-operation
df = pd.read_csv('data.csv', strict=True)

# Globally via environment variable
import os
os.environ['SUNSTONE_DATAFRAME_STRICT'] = '1'

# Via CLI for entire dataset
# sunstone dataset lock my-dataset
```

**Example error in strict mode:**
```python
# This will raise StrictModeError if 'new-output' not in datasets.yaml
result.to_csv(
    'outputs/new-output.csv',
    slug='new-output',
    name='New Output',
    index=False,
    strict=True
)
```

## Lineage Tracking (W3C PROV-O)

Lineage tracking automatically captures the provenance of your data through all operations. Since v1.5.0, the lineage model is aligned with [W3C PROV-O](https://www.w3.org/TR/prov-o/), the standard ontology for provenance.

### PROV-O Concepts

sunstone-py maps its data model to PROV-O:

- **Entity**: A dataset (`DatasetMetadata`) — the thing being tracked
- **Activity**: A script or notebook execution (`Activity`) — the process that transforms data
- **Agent**: A user, organization, or software (`Agent`) — who is responsible

### What Gets Tracked

**Sources:**
- Input datasets that were read
- Their metadata (slug, name, location)
- License information
- Source attribution (as PROV-O Agents)

**Activities:**
- Script/notebook executions with timestamps
- Which entities were used (with column-level detail)
- Which entities were generated
- Associated agents (user, software)
- Git commit hash and dirty state

**Field Derivations:**
- Which output columns came from which source datasets
- Column-level provenance (prov:qualifiedDerivation)
- Auto-populated on read so provenance flows through merge/join/concat

**Metadata:**
- Content hash (detects when data actually changes)
- Creation timestamp (only updated when content changes)
- Source relationships

### Accessing Lineage

```python
# Read and transform data
df = pd.read_csv('input.csv', project_path=PROJECT_PATH)
result = df[df['value'] > 100].groupby('category').sum()

# Access lineage through metadata (preferred)
print(result.metadata.lineage.sources)
print(result.metadata.lineage.get_licenses())

# Check field derivations
if result.metadata.lineage.field_derivations:
    for fd in result.metadata.lineage.field_derivations:
        print(f"  {fd.output_field} <- {fd.source_entity}.{fd.source_field}")

# Check activity details
if result.metadata.lineage.activity:
    activity = result.metadata.lineage.activity
    print(f"Activity: {activity.id}")
    print(f"Started: {activity.started_at}")
    for agent in activity.was_associated_with:
        print(f"Agent: {agent.label} ({agent.type.value})")
```

### Field-Level Derivations

When you read a dataset, sunstone automatically records which columns came from which source. This propagates through operations:

```python
# Read: each column gets a derivation record
schools = pd.read_csv('schools.csv', project_path=PROJECT_PATH)
# schools.metadata.lineage.field_derivations contains:
#   FieldDerivation(output_field='name', source_entity='school-data', source_field='name')
#   FieldDerivation(output_field='enrollment', source_entity='school-data', source_field='enrollment')
#   ...

# Merge: derivations from both sources are combined
merged = pd.merge(schools, teachers, on='school_id')
# merged has derivations from both 'school-data' and 'teacher-data'
```

### Lineage Persistence

When you save a DataFrame, lineage is automatically written to `datasets.yaml`, including PROV-O activity tracking:

```python
result.to_csv(
    'outputs/summary.csv',
    slug='summary',
    name='Summary Results',
    index=False
)
```

This adds to `datasets.yaml`:

```yaml
outputs:
  - name: Summary Results
    slug: summary
    location: outputs/summary.csv
    fields:
      - name: category
        type: string
      - name: value
        type: number
    lineage:
      content_hash: abc123...
      created_at: '2026-02-04T10:30:00'
      sources:
        - slug: input-data
      activity:
        id: exec-20260204T103000-abc123
        agents:
          - id: stig
            type: prov:Person
          - id: sunstone-py
            type: prov:SoftwareAgent
            version: '1.5.0'
        used:
          - entity: input-data
        started_at: '2026-02-04T10:29:55'
        ended_at: '2026-02-04T10:30:00'
      field_derivations:
        - output_field: category
          source_entity: input-data
          source_field: category
        - output_field: value
          source_entity: input-data
          source_field: value
```

### Lineage Propagation

Lineage automatically propagates through operations:

```python
# Read two sources
schools = pd.read_csv('schools.csv', project_path=PROJECT_PATH)  # source 1
teachers = pd.read_csv('teachers.csv', project_path=PROJECT_PATH)  # source 2

# Merge combines lineage from both
merged = pd.merge(schools, teachers, on='school_id')

# Result tracks both sources
print(len(merged.metadata.lineage.sources))  # 2
```

### Content Hash Optimization

The content hash prevents unnecessary timestamp updates:

```python
# First save
result.to_csv('output.csv', slug='output', name='Output')
# lineage.created_at = '2026-02-04T10:00:00'

# Re-run with same result
result.to_csv('output.csv', slug='output', name='Output')
# lineage.created_at = '2026-02-04T10:00:00'  (unchanged!)

# Re-run with different result
result_v2.to_csv('output.csv', slug='output', name='Output')
# lineage.created_at = '2026-02-04T11:00:00'  (updated!)
```

## DataFrame Metadata

Every DataFrame carries a `metadata` container that holds lineage and per-field annotations. This metadata flows through operations and is persisted to `datasets.yaml` on write.

### The Metadata Container

```python
df = pd.read_csv('data.csv', project_path=PROJECT_PATH)

df.metadata.slug = 'my-analysis'
df.metadata.name = 'My Analysis'
df.metadata.description = 'Analysis of school enrollment data'

# RDF prefixes and custom properties
df.metadata.rdf_prefixes = {'schema': 'http://schema.org/'}
df.metadata.custom_properties = {'schema:about': 'Education'}

# Lineage is accessed through metadata
print(df.metadata.lineage.sources)
```

### Per-Field Metadata

Annotate individual columns with descriptions, units, and source tracking:

```python
df.set_field_metadata('enrollment', description='Total enrolled students', unit='students')
df.set_field_metadata('area_km2', description='School district area', unit='km^2')
df.set_field_metadata('density', description='Students per square kilometer', unit='students / km^2')
```

Field metadata is written to `datasets.yaml` alongside the field schema:

```yaml
fields:
  - name: enrollment
    type: integer
    description: Total enrolled students
    unit: students
  - name: area_km2
    type: number
    description: School district area
    unit: km^2
```

### Deprecation: `df.lineage`

The old `df.lineage` accessor still works but is deprecated. Use `df.metadata.lineage` instead.

## Plugin System

Reading, writing, and URL fetching are handled by a plugin registry. Built-in handlers cover common formats and URL schemes; external plugins are discovered automatically via entry points.

### Built-in Support

**Formats:** CSV, JSON, Excel, Parquet, TSV

**URL schemes:**
- Local file paths (built-in)
- `http://` and `https://` (built-in, with SSRF protection)
- `gs://` (requires `sunstone-py[gcs]`)
- `s3://` and `r2://` (requires `sunstone-py[s3]`)

### Using the Plugin Registry

```python
from sunstone.plugins import PluginRegistry
from pathlib import Path

registry = PluginRegistry.get('/path/to/project')

# Fetch a file from any supported URL
registry.fetch('gs://my-bucket/data.csv', Path('data/local.csv'))
```

### Writing Custom Plugins

Implement one or more plugin protocols (`AuthProvider`, `URLHandler`,
`FormatHandler`, `StoreFormatHandler`, `CLIProvider`, `EnvSectionProvider` —
see [Plugin protocols](api.md#plugin-protocols)) and register via entry points:

```toml
# In your plugin's pyproject.toml
[project.entry-points."sunstone.plugins"]
my-plugin = "my_package:MyPlugin"
```

### Plugin Configuration

Configuration uses cascading precedence:

1. `datasets.yaml` → `plugins.<name>` section (highest priority)
2. `pyproject.toml` → `[tool.sunstone.plugins.<name>]`
3. Environment variables → `SUNSTONE_PLUGIN_<NAME>_<KEY>`

## Unit-Aware Arithmetic

sunstone-py integrates with [Pint](https://pint.readthedocs.io/) for unit-aware column operations. When columns have units set via `set_field_metadata()`, arithmetic operations validate unit compatibility.

### Unit Modes

```bash
export SUNSTONE_UNIT_MODE=auto  # or: strict, relaxed (default)
```

```python
from sunstone.units import set_unit_mode
set_unit_mode('auto')
```

| Mode | Behavior |
|------|----------|
| `relaxed` | No unit validation (default) |
| `strict` | Raises `UnitError` on incompatible operations |
| `auto` | Auto-converts compatible units, warns on mismatch |

### Example

```python
from sunstone.units import set_unit_mode
set_unit_mode('auto')

df.set_field_metadata('distance_km', unit='km')
df.set_field_metadata('distance_miles', unit='mile')

# In auto mode, merging DataFrames with km and miles on the same
# column will automatically convert to a common unit
```

### QUDT Round-Tripping

Units stored as [QUDT](http://qudt.org/) URIs in `datasets.yaml` are preserved through read/write cycles. The original URI is stored in `FieldSchema.unit_source` so it round-trips without loss.

## License Compatibility

sunstone-py treats licenses as a first-class part of lineage: every input declares a `source.license`, every output declares an effective license (its own, its `packages[]` entry, or the top-level `package.license`), and the compatibility between them is checked automatically at write time.

There are three layers of license handling, intentionally graded from soft to hard:

1. **Lint (`sunstone lint`)** — `R005` flags a dataset that has no license at all; `R006` flags a license string that isn't a recognised SPDX identifier or `LicenseRef-*` form.
2. **CLI audit (`sunstone license check`)** — runs the compatibility engine across every output's `wasDerivedFrom` chain and exits non-zero on conflict. Use it in CI. See the [CLI Guide](cli.md#license-commands).
3. **Write-time enforcement** — `to_csv()` / `to_parquet()` raise [`LicenseCompatibilityError`](errors.md#licensecompatibilityerror) when the target license is incompatible with a source license in the current session lineage. When no target license is declared, one is auto-derived from the sources (inheriting a single source's license, or picking the most restrictive license that satisfies all sources) and persisted to `datasets.yaml`. Pass `check_license=False` to skip on a specific write.

### How the Compatibility Engine Works

Each license in the embedded registry is described by four boolean properties — `public_domain`, `attribution`, `share_alike`, `non_commercial` — plus a `family` tag for ShareAlike. A `(source → target)` pair is checked against this rule set:

| Source property | Constraint on target |
|---|---|
| `public_domain` | None — compatible with anything. |
| `share_alike` | Target must also be `share_alike` **and** share the same `family`. (`CC-BY-SA-4.0` and `CC-BY-SA-3.0` are *different* families on purpose — Creative Commons treats them as one-way upgradable, not mutually equivalent.) |
| `non_commercial` | Target must also be `non_commercial`. |
| `attribution` (without SA/NC) | Target must be `attribution` *or* `share_alike` (SA implies attribution). |

A check fails as soon as any source/target pair violates the rules; the resulting `LicenseCompatibilityResult` lists every conflict and a `suggestions` list of registry licenses that *would* satisfy all known sources. The most-restrictive ordering — used by `get_most_restrictive_license()` and by suggestion ranking — is `ShareAlike > NonCommercial > Attribution > Public Domain`.

### Embedded License Registry

The registry is intentionally focused on common research-data licenses. Anything outside it must use a `LicenseRef-*` identifier; unregistered `LicenseRef-*` ids pass lint `R006` but are reported as `unknown_sources` by the compatibility engine and excluded from the rule check.

| SPDX id | Class |
|---|---|
| `CC0-1.0`, `PDDL-1.0`, `LicenseRef-US-PD` | Public domain |
| `CC-BY-4.0`, `CC-BY-3.0`, `CC-BY-3.0-IGO` | Attribution only |
| `ODC-By-1.0`, `LicenseRef-OGL-3.0`, `NLOD-1.0`, `NLOD-2.0` | Attribution only |
| `CC-BY-SA-4.0`, `CC-BY-SA-3.0`, `ODbL-1.0` | Attribution + ShareAlike (each is its own family) |
| `CC-BY-NC-4.0`, `CC-BY-NC-3.0-IGO` | Attribution + NonCommercial |
| `CC-BY-NC-SA-4.0`, `CC-BY-NC-SA-3.0`, `CC-BY-NC-SA-3.0-IGO` | Attribution + NonCommercial + ShareAlike (each is its own family) |

Adding a license is a one-line append to `_REGISTRY_ENTRIES` in `src/sunstone/licenses.py`. The full set is also available programmatically via `sunstone.licenses.known_licenses()`.

### Worked Example

A source `un-members` is licensed `CC-BY-NC-4.0`. You merge it with a `CC-BY-4.0` input and try to publish under `CC-BY-4.0`:

```python
result.to_csv(
    "outputs/derived.csv",
    slug="derived",
    name="Derived Data",
    license="CC-BY-4.0",
)
# raises LicenseCompatibilityError:
#   CC-BY-NC-4.0 is NonCommercial: derivatives must also be NonCommercial, not CC-BY-4.0
#   Suggested compatible target licenses: CC-BY-NC-4.0, CC-BY-NC-SA-4.0, CC-BY-NC-3.0-IGO
```

The fix is to widen the output to a NonCommercial license — or, if you have rights to do so, to remove the NC source from the lineage. The engine does not let you "wash out" a NonCommercial source by mixing it with a permissive one; that is the correct behaviour under Creative Commons.

### Auto-Derived Target Licenses

When the output has source licenses but no declared target (no `license:` on the dataset, no `packages[].license` / `package.license` covering it, and no `license=` argument to the writer), the writer derives a target automatically:

- **One unique source license** — the output inherits it.
- **Multiple compatible source licenses** — the writer picks the most restrictive license that satisfies every source (e.g., `CC-BY-4.0` + `CC-BY-NC-4.0` → `CC-BY-NC-4.0`).
- **Mutually incompatible sources, or unknown licenses among multiples** — `LicenseCompatibilityError`. The writer refuses to guess; declare an explicit `license:` to proceed.

Any auto-derived license is persisted to `datasets.yaml` so future reads and `sunstone license check` runs see it as declared.

### Conflicting Licenses

An explicitly declared target license that is incompatible with a source license is always a hard failure (`LicenseCompatibilityError`) — silently publishing under the wrong license can be a legal problem. Combine `sunstone lint --warnings-as-errors` (catches missing licenses at lint time) with `sunstone license check` (catches conflicts) in CI to make both classes hard failures before publish.

## Dataset Metadata

Every dataset in `datasets.yaml` has rich metadata:

### Required Fields

```yaml
- name: Human-Readable Name
  slug: machine-readable-slug
  location: path/to/file.csv
  fields:
    - name: column_name
      type: string  # or number, integer, boolean, date, datetime
```

### Optional Fields

```yaml
# Top-level publishing configuration (applies to all outputs)
publish:
  enabled: true
  to: gs://bucket-name/path/
  flatten: false  # optional: flatten directory structure

inputs:
  - name: Example Dataset
    slug: example
    location: data/example.csv

    # Source attribution for inputs
    source:
      name: Data Provider Name
      location:
        data: https://example.com/data.csv
      attributedTo: Organization or Person
      acquiredAt: '2025-01-15'
      acquisitionMethod: manual-download  # or api, web-scraping, etc.
      license: CC-BY-4.0

    # Strict mode flag
    strict: true

outputs:
  - name: Output Dataset
    slug: output-example
    location: outputs/example.csv

    # Strict mode flag
    strict: true

    # Lineage metadata (auto-generated)
    lineage:
      content_hash: abc123...
      created_at: '2026-02-04T10:00:00'
      sources:
        - slug: source-dataset
```

### Publishing Configuration

The top-level `publish` section controls how data packages are published:

```yaml
publish:
  enabled: true                              # Required: enable publishing
  to: gs://bucket/datasets/project-name/     # GCS upload destination
  as: https://data.example.com/project-name/ # Optional: public URL base for datapackage.json
  flatten: false                             # Optional: flatten directory structure
```

**Path Resolution:**

- If `to` ends with `.json`: Used as the datapackage filename
  - `gs://bucket/countries.json` → datapackage at `gs://bucket/countries.json`
  - Data files in `gs://bucket/` (relative to datapackage directory)

- If `to` doesn't end with `.json`: Treated as a directory
  - `gs://bucket/datasets/project/` → datapackage at `gs://bucket/datasets/project/datapackage.json`
  - Data files in `gs://bucket/datasets/project/`

**Public URL Option (`as`):**

When your GCS bucket is served via a CDN or custom domain, use `as` to set the public-facing URLs in `datapackage.json`:

```yaml
publish:
  to: gs://my-bucket/datasets/project/      # Files uploaded here
  as: https://data.example.com/project/     # URLs in datapackage.json use this base
```

- Files are uploaded to `gs://my-bucket/datasets/project/outputs/data.csv`
- But `datapackage.json` contains: `"path": "https://data.example.com/project/outputs/data.csv"`

This allows data consumers to fetch files directly from your public URL.

**Flatten Option:**

- `flatten: false` (default): Preserves directory structure from `location` field
  - `location: outputs/data/file.csv` → `gs://bucket/project/outputs/data/file.csv`

- `flatten: true`: Puts all files in same directory as datapackage.json
  - `location: outputs/data/file.csv` → `gs://bucket/project/file.csv`

## Validation Tools

Check notebooks and scripts for correct import usage:

```python
import sunstone

# Check a single notebook
result = sunstone.check_notebook_imports('analysis.ipynb')
print(result.summary())

# Check all notebooks in project
results = sunstone.validate_project_notebooks('/path/to/project')
for path, result in results.items():
    if not result.is_valid:
        print(f"\n{path}:")
        print(result.summary())
```

**What validation checks:**
- Files use `from sunstone import pandas as pd` instead of plain pandas
- No direct pandas imports in data processing code
- Proper usage of `project_path` parameter

## Project Path Configuration

`read_csv`, `read_excel`, `read_json`, `read_dataset`, and the `DataFrame` constructor all need to know which project's `datasets.yaml` to consult. They accept a `project_path=` argument; when none is given, they fall back to a process-wide default, and finally to `Path.cwd()`.

```python
import sunstone
from sunstone import pandas as pd
from pathlib import Path

# 1. Set once for the entire process (recommended in notebooks/scripts)
sunstone.set_project_path(Path(__file__).parent)
df = pd.read_csv('inputs/data.csv')          # uses configured path

# 2. Pass explicitly per call (overrides the default)
df = pd.read_csv('inputs/data.csv', project_path='/other/project')

# 3. Scoped override
with sunstone.use_project_path('/temporary/project'):
    df = pd.read_csv('inputs/other.csv')
# default is restored after the with block

# Read or clear the configured default
print(sunstone.get_project_path())
sunstone.clear_project_path()
```

The configured value is held in a `contextvars.ContextVar`, so it is safe across threads and async tasks.

## Organizing Datasets Across Files

For projects with many datasets, `datasets.yaml` can pull in additional files via an `include:` directive:

```yaml
# datasets.yaml
package:
  name: my-project
  license: CC-BY-4.0

include:
  - datasets/inputs.yaml
  - datasets/outputs.yaml

# Top-level inputs/outputs/packages here are still allowed
inputs: []
outputs: []
```

Each included file may declare its own `inputs:`, `outputs:`, and `packages:` lists. Top-level configuration that affects the whole project (`defaults`, `rdfPrefixes`, `package`, `publish`, `min_sunstone_version`) is not allowed in included files — only in the main `datasets.yaml`.

Other rules:

- Includes are not nested — an included file cannot itself contain an `include:` key.
- Slug collisions across files are an error: every dataset slug and every package name must be unique across the merged set.
- Paths are relative to the file containing the `include:` directive.

## Environment Variables

### SUNSTONE_DATAFRAME_STRICT

Enable strict mode globally:

```bash
export SUNSTONE_DATAFRAME_STRICT=1
# or
export SUNSTONE_DATAFRAME_STRICT=true
```

```python
# Now all operations are strict by default
df = pd.read_csv('input.csv')  # strict=True implied
```

## Best Practices

### Start Relaxed, Lock for Production

1. **Development**: Use relaxed mode for exploration
2. **Refinement**: Review auto-generated `datasets.yaml` entries
3. **Production**: Lock datasets with `sunstone dataset lock`

### Lint Before You Ship

Run `sunstone lint` to catch missing licenses, units, descriptions, and slugs that don't follow project conventions before publishing. In CI, use `sunstone lint --warnings-as-errors` to make recommended-but-not-required metadata mandatory. See the [CLI Guide](cli.md#lint-command) for the full rule list.

### Document Sources Thoroughly

```yaml
inputs:
  - name: UN Member States
    slug: un-members
    location: inputs/un_members.csv
    source:
      name: United Nations
      location:
        data: https://www.un.org/en/about-us/member-states
      attributedTo: United Nations
      acquiredAt: '2025-01-15'
      acquisitionMethod: manual-download
      license: Public Domain
      notes: |
        Downloaded from the official UN website.
        Data accurate as of January 2025.
```

### Use Descriptive Slugs

```yaml
# Good
slug: school-enrollment-by-district
slug: teacher-demographics-2025

# Avoid
slug: data1
slug: output
slug: final_final_v2
```

### Track Operations Explicitly

```python
# Instead of chaining without description
result = df.apply(complex_function)

# Add operation description for lineage
result = df.apply_operation(
    complex_function,
    description="Apply enrollment adjustment factors"
)
```

### Version Your Datasets

```yaml
outputs:
  - name: School Summary v2.1
    slug: school-summary-v2-1
    location: outputs/school-summary-v2.1.csv
```

Or use the `version` field in package metadata when building data packages.
