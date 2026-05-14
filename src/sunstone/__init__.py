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

from .asset import Asset, AssetKind
from .component import ComponentSchema
from .config import (
    clear_project_path,
    get_project_path,
    set_project_path,
    use_project_path,
)
from .dataframe import DataFrame
from .datasets import DatasetsManager
from .errors import IncompatibleAssetKindError
from .exceptions import (
    DatasetNotFoundError,
    DatasetValidationError,
    LineageError,
    StrictModeError,
    SunstoneError,
    UnitError,
)
from .rdf import IRI, LangString, TypedLiteral
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

# Linter
from .lint import LintReport, Severity as LintSeverity, Violation, lint_project

# Lineage tracking modules
from .context import ExecutionContext, detect_execution_context
from .queries import LineageNode, display_lineage, get_upstream, lineage_to_dict
from .session import DatasetRead, LineageSession, close_session, get_session


def read(path: str, *, format: str | None = None, **kw: object) -> "Asset":
    """Read any registered format into an `Asset`. Dispatches via the plugin
    registry (which normalises DataFrame-returning handlers through the
    adapter)."""
    from .dataframe import _read_tabular_asset

    return _read_tabular_asset(path, format=format, **kw)


def write(asset: "Asset", path: str, *, format: str | None = None, **kw: object) -> None:
    """Write an `Asset` to `path`. Dispatches via the plugin registry."""
    from .plugins import PluginRegistry

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if hasattr(handler, "can_write") and handler.can_write(path, format):  # type: ignore[attr-defined]
            url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
            if url_handler is None:
                raise FileNotFoundError(path)
            with url_handler.open(path, "wb") as stream:
                handler.write(asset, stream, **kw)  # type: ignore[attr-defined]
            return
    raise ValueError(f"No handler for path={path!r} format={format!r}")


# Standard RDF and DCAT prefixes for automatic type properties
STANDARD_RDF_PREFIXES = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "dwc": "http://rs.tdwg.org/dwc/terms/",
    "gtio-i": "https://sunstone.institute/rdf/gtio/0.3/interventions#",
    "gtio-t": "https://sunstone.institute/rdf/gtio/0.3/threats#",
    "prov": "http://www.w3.org/ns/prov#",
    "qudt": "http://qudt.org/schema/qudt/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "schema": "http://schema.org/",
    "si": "https://sunstone.institute/rdf/vocab#",
    "si30": "https://sunstone.institute/rdf/threat/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "sosa": "http://www.w3.org/ns/sosa/",
}

__all__ = [
    # Main classes
    "DataFrame",
    "DatasetsManager",
    # Top-level I/O
    "read",
    "write",
    # Asset envelope
    "Asset",
    "AssetKind",
    "ComponentSchema",
    # RDF types
    "IRI",
    "LangString",
    "TypedLiteral",
    # Project-path configuration
    "set_project_path",
    "get_project_path",
    "clear_project_path",
    "use_project_path",
    # Pandas-like interface
    "pandas",
    # Errors (re-exported from pandas.errors)
    "errors",
    # Validation utilities
    "ImportCheckResult",
    "check_notebook_imports",
    "check_script_imports",
    "validate_project_notebooks",
    # Linter
    "LintReport",
    "LintSeverity",
    "Violation",
    "lint_project",
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
    "IncompatibleAssetKindError",
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
    # RDF prefixes
    "STANDARD_RDF_PREFIXES",
    # Lineage queries
    "LineageNode",
    "get_upstream",
    "display_lineage",
    "lineage_to_dict",
]
