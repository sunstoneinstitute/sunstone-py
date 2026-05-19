# Error handling

The `sunstone.errors` module re-exports everything from `pandas.errors`,
so you can catch pandas exceptions without importing pandas directly:

```python
from sunstone import pandas as pd
from sunstone.errors import ParserError

try:
    df = pd.read_csv("bad_file.csv", project_path=PROJECT_PATH)
except ParserError:
    print("Failed to parse CSV")
```

All public error and warning classes from `pandas.errors` are available,
including `EmptyDataError`, `MergeError`, `ParserError`,
`SettingWithCopyWarning`, and others.

## Note on `ChainedAssignmentError`

`ChainedAssignmentError` is not available via `from sunstone.errors import
ChainedAssignmentError` because pandas itself excludes it from its star
export. It is still accessible through the module path:

```python
from sunstone import pandas as pd

pd.errors.ChainedAssignmentError
```

This matches the behavior of plain `import pandas as pd` — the drop-in
replacement works identically.

## `LicenseCompatibilityError`

Raised by `to_csv()` / `to_parquet()` (and other writers that go through the
lineage path) when the target license declared for the output is incompatible
with one or more source licenses collected from the current session lineage.

```python
from sunstone import pandas as pd
from sunstone.licenses import LicenseCompatibilityError

# Source license is CC-BY-NC-4.0 (NonCommercial),
# but we try to publish under CC-BY-4.0 (drops NC):
try:
    result.to_csv(
        "outputs/derived.csv",
        slug="derived",
        name="Derived Data",
        license="CC-BY-4.0",
    )
except LicenseCompatibilityError as e:
    print(e)
```

Typical output:

```
License compatibility check failed for output 'derived' (target: CC-BY-4.0).
  - CC-BY-NC-4.0 is NonCommercial: derivatives must also be NonCommercial, not CC-BY-4.0
Suggested compatible target licenses: CC-BY-NC-4.0, CC-BY-NC-SA-4.0, CC-BY-NC-3.0-IGO
```

The error is also exported from `sunstone.exceptions` (via the `SunstoneError`
base class) and inherits from it, so a single `except SunstoneError` handler
catches it alongside `DatasetNotFoundError`, `StrictModeError`, etc.

**Disabling the check at the call site:**

```python
result.to_csv(
    "outputs/derived.csv",
    slug="derived",
    name="Derived Data",
    license="CC-BY-4.0",
    check_license=False,  # opt out — use sparingly
)
```

When no target license can be determined for an output that has source
licenses, the writer emits a `UserWarning` instead of raising — so a missing
license is a soft signal, but a conflicting license is hard.

See [License Compatibility](concepts.md#license-compatibility) for the rule
reference and [`sunstone license check`](cli.md#check-license-compatibility)
for the equivalent CI-friendly command.
