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
    UnitError,
)
from .lineage import (
    Activity,
    ActivityRef,
    Agent,
    AgentType,
    Contributor,
    DatasetMetadata,
    EntityRef,
    FieldDerivation,
    FieldSchema,
    LineageMetadata,
    Metadata,
    PackageMetadata,
    Source,
    SourceLocation,
    UsageRecord,
)

# Plugin system
from .plugins import AuthProvider, CLIProvider, FormatHandler, PluginRegistry, URLHandler

# Environment config
from .env import DataEnvironment, resolve_environment

# Packaging (library functions for building and pushing data packages)
from . import packaging

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
    "Metadata",
    "DatasetMetadata",
    "FieldSchema",
    "PackageMetadata",
    "Source",
    "SourceLocation",
    # PROV-O types
    "Activity",
    "ActivityRef",
    "Agent",
    "AgentType",
    "EntityRef",
    "FieldDerivation",
    "UsageRecord",
    # Exceptions
    "SunstoneError",
    "DatasetNotFoundError",
    "DatasetValidationError",
    "StrictModeError",
    "LineageError",
    "UnitError",
    # Context and session
    "ExecutionContext",
    "detect_execution_context",
    "get_session",
    "close_session",
    "LineageSession",
    "DatasetRead",
    # Plugin system
    "AuthProvider",
    "CLIProvider",
    "URLHandler",
    "FormatHandler",
    "PluginRegistry",
    # Environment config
    "DataEnvironment",
    "resolve_environment",
    # Packaging
    "packaging",
    # Lineage queries
    "LineageNode",
    "get_upstream",
    "display_lineage",
    "lineage_to_dict",
]
