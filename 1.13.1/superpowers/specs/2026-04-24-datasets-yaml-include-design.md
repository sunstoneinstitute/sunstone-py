# Design: `include:` support for datasets.yaml

## Problem

As projects grow, `datasets.yaml` becomes unwieldy with many inputs, outputs, and packages. Users need a way to organize dataset definitions across multiple files while maintaining a single logical configuration.

## Solution

A top-level `include:` key in `datasets.yaml` that references other YAML files conforming to the datasets.yaml spec. Included files contribute `inputs`, `outputs`, and `packages` lists that are merged into the main file at load time.

### Example

```yaml
# datasets.yaml
include:
  - data/external-inputs.yaml
  - packages.yaml

inputs:
  - name: Local Input
    slug: local-input
    location: inputs/local.csv

outputs:
  - name: My Output
    slug: my-output
    location: outputs/result.csv
```

```yaml
# data/external-inputs.yaml
inputs:
  - name: External Source
    slug: external-source
    location: inputs/external.csv
```

## Merge rules

- **List keys** (`inputs`, `outputs`, `packages`): concatenated. Main file entries come first, then included files in declaration order.
- **Scalar/dict top-level keys** (`defaults`, `rdfPrefixes`, `package`, `publish`, `min_sunstone_version`): only from the main file. If an included file contains any of these, raise `DatasetValidationError`.
- **Nested includes**: not supported. If an included file has an `include:` key, raise `DatasetValidationError`.
- **Path resolution**: relative paths in `include:` are resolved relative to the file containing the directive (the main `datasets.yaml`).

## Duplicate detection

After merging, validate:
- No two datasets (across inputs + outputs) share the same `slug`. Error names both files.
- No two `packages:` entries share the same `name`. Error names both files.

## Write behavior

All writes (`add_output_dataset`, `update_output_dataset`, `update_output_lineage`, `_save`) target the main `datasets.yaml` only. Included files are read-only from the perspective of `DatasetsManager`.

## Implementation

### `_merge_includes()` method

Called from `_load()` after the main file is parsed but before the rest of `_load()` runs:

1. Pop `include` from `self._data` (if absent, return immediately).
2. For each path, resolve relative to `self.datasets_file.parent`.
3. Load the file with `ruamel.yaml`.
4. Validate: no `include` key, no disallowed top-level keys.
5. Extend `self._data["inputs"]`, `self._data["outputs"]`, and (if present) `self._data["packages"]`.
6. Run duplicate slug/name detection across the merged result, reporting which files conflict.

### Disallowed keys in included files

`defaults`, `rdfPrefixes`, `package`, `publish`, `min_sunstone_version`

## Error cases

| Condition | Error type |
|---|---|
| Included file not found | `FileNotFoundError` with path |
| Included file has `include:` | `DatasetValidationError`: nested includes not supported |
| Included file has disallowed keys | `DatasetValidationError`: lists which keys are not allowed |
| Duplicate slug across files | `DatasetValidationError`: names both files |
| Duplicate package name across files | `DatasetValidationError`: names both files |

## Test plan

- Basic include merging: inputs from sub-file appear in `get_all_inputs()`
- Multiple includes, all three list types (`inputs`, `outputs`, `packages`)
- Coexistence: main file has inputs + included file has inputs
- Duplicate slug detection across files
- Duplicate package name detection
- Nested include rejection
- Disallowed keys rejection
- Missing included file
- Empty included file (valid no-op)
- `find_dataset_by_slug` and `find_dataset_by_location` work across included datasets
