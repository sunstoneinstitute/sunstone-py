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
    >>> # Perform operations using familiar pandas syntax
    >>> result = df[df['Amount'] > 100]
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
    Contributor,
    DatasetMetadata,
    FieldSchema,
    LineageMetadata,
    PackageMetadata,
    Source,
    SourceLocation,
)

# Import pandas module for pd-like interface
from . import pandas

# Import errors module (re-exports pandas.errors)
from . import errors

# Import validation utilities
from .validation import (
    ImportCheckResult,
    check_notebook_imports,
    check_script_imports,
    validate_project_notebooks,
)

# Lineage tracking modules
from .context import ExecutionContext, detect_execution_context
from .queries import LineageNode, display_lineage, get_upstream, lineage_to_dict
from .session import DatasetRead, LineageSession, close_session, get_session

__version__ = "0.1.0"

__all__ = [
    # Main classes
    "DataFrame",
    "DatasetsManager",
    # Pandas-like interface
    "pandas",
    # Errors (re-exported from pandas.errors)
    "errors",
    # Validation utilities
    "ImportCheckResult",
    "check_notebook_imports",
    "check_script_imports",
    "validate_project_notebooks",
    # Lineage classes
    "Contributor",
    "LineageMetadata",
    "DatasetMetadata",
    "FieldSchema",
    "PackageMetadata",
    "Source",
    "SourceLocation",
    # Exceptions
    "SunstoneError",
    "DatasetNotFoundError",
    "DatasetValidationError",
    "StrictModeError",
    "LineageError",
    # Context and session
    "ExecutionContext",
    "detect_execution_context",
    "get_session",
    "close_session",
    "LineageSession",
    "DatasetRead",
    # Lineage queries
    "LineageNode",
    "get_upstream",
    "display_lineage",
    "lineage_to_dict",
]
