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
