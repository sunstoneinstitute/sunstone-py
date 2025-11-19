"""
Sunstone: Python library for managing datasets with lineage tracking.

This library provides tools for data scientists working on Sunstone projects
to manage datasets with full lineage tracking and integration with datasets.yaml.

Example:
    >>> import sunstone
    >>>
    >>> # Read a dataset (must be in datasets.yaml)
    >>> df = sunstone.DataFrame.read_csv(
    ...     'official_un_member_states_raw.csv',
    ...     project_path='/path/to/project'
    ... )
    >>>
    >>> # Perform operations - lineage is tracked
    >>> result = df.apply_operation(
    ...     lambda d: d[d['Amount'] > 100],
    ...     description="Filter countries with >100 schools"
    ... )
    >>>
    >>> # Write output (auto-registers in relaxed mode)
    >>> result.to_csv(
    ...     'filtered_schools.csv',
    ...     slug='filtered-schools',
    ...     name='Filtered School Counts',
    ...     index=False
    ... )
"""

from .dataframe import DataFrame
from .datasets import DatasetsManager
from .exceptions import (
    DatasetNotFoundError,
    DatasetValidationError,
    LineageError,
    StrictModeError,
    SunstoneError,
)
from .lineage import (
    DatasetMetadata,
    FieldSchema,
    LineageMetadata,
    Source,
    SourceLocation,
)

# Import pandas module for pd-like interface
from . import pandas

# Import validation utilities
from .validation import (
    ImportCheckResult,
    check_notebook_imports,
    check_script_imports,
    validate_project_notebooks,
)

__version__ = "0.1.0"

__all__ = [
    # Main classes
    "DataFrame",
    "DatasetsManager",
    # Pandas-like interface
    "pandas",
    # Validation utilities
    "ImportCheckResult",
    "check_notebook_imports",
    "check_script_imports",
    "validate_project_notebooks",
    # Lineage classes
    "LineageMetadata",
    "DatasetMetadata",
    "FieldSchema",
    "Source",
    "SourceLocation",
    # Exceptions
    "SunstoneError",
    "DatasetNotFoundError",
    "DatasetValidationError",
    "StrictModeError",
    "LineageError",
]
