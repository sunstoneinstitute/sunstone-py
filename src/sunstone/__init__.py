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

The public surface (classes, helpers, submodules) is imported lazily via PEP 562
``__getattr__``. ``import sunstone`` is cheap; pandas, pyarrow, numpy, etc. are
only loaded when an attribute that needs them is actually accessed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Standard RDF and DCAT prefixes for automatic type properties.
# Eager because the dict is cheap and frequently consulted by the CLI.
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


def read(
    path: str,
    *,
    format: str | None = None,
    kind: "AssetKind | None" = None,
    metadata: "Metadata | None" = None,
    extras: dict[str, Any] | None = None,
    **kw: object,
) -> "Asset":
    """Read any registered format into an `Asset`.

    Dispatch order:
      1. Explicit ``kind=`` / ``format=`` arguments.
      2. ``datasets.yaml`` ``format`` field, if the path matches a registered
         dataset entry.
      3. Path extension / store classification by handler.

    Overrides: when ``kind`` / ``metadata`` / ``extras`` are provided they
    OVERRIDE (full replacement) whatever the handler produced. This is the
    reconstruction path — consumers rebuilding an Asset from a catalog row
    where the catalog (not the file) is the source of truth for envelope
    fields.
    """
    from .dataframe import _read_tabular_asset
    from .datasets import DatasetsManager
    from .plugins import PluginRegistry
    from .resource import ResourceLocation

    # 2. Consult datasets.yaml when no explicit format was given.
    if format is None:
        try:
            dm: DatasetsManager | None = DatasetsManager.from_project_path()
        except Exception:
            dm = None
        if dm is not None:
            entry = dm.find_entry_by_location(path)
            if entry is not None:
                format = entry.get("format")

    # 3. Store-vs-stream classification.
    loc = ResourceLocation(path=path)
    registry = PluginRegistry.get()
    asset: "Asset | None" = None
    if loc.is_dir():
        handler = registry.find_store_format_reader(loc, format)
        if handler is not None:
            asset = handler.read(loc, **kw)  # type: ignore[attr-defined]
        # Fall through to stream path so single-file handlers can still claim
        # directory-like paths via can_read.
    else:
        # Single-file store handlers (HDF5, NetCDF-4, ...) live behind the
        # store-format protocol because their libraries need a real path, not
        # a stream. Give them a shot before falling through to the tabular
        # stream path.
        handler = registry.find_store_format_reader(loc, format)
        if handler is not None:
            asset = handler.read(loc, **kw)  # type: ignore[attr-defined]

    if asset is None:
        asset = _read_tabular_asset(path, format=format, **kw)

    # Apply overrides (full replacement — catalog rows win over file content).
    if kind is not None:
        asset.kind = kind
    if metadata is not None:
        asset.metadata = metadata
    if extras is not None:
        asset.extras = extras
    return asset


def _materialise_default_identity(asset: "Asset") -> None:
    """If `asset.metadata.identity` is None and the asset has a slug, fill in
    the default `<package-name>/<slug>@<package-version>` path using the active
    project's pyproject.toml. No-op otherwise — user-supplied templates are
    preserved verbatim.

    The minted value is a scheme-less, environment-relative path: it carries
    only what this package owns (its name, the asset slug, its version). The
    consumer is responsible for binding it to a scheme — e.g. the data platform
    resolves it to a `sunstone:` authoring handle or an absolute `https://`
    graph IRI. Minting a `sunstone:`-schemed URI here would couple this package
    to a URL scheme it does not define.

    Skipped entirely when no `pyproject.toml` is discoverable at the resolved
    project path: otherwise the bare cwd fallback in `get_project_path()`
    would invent identities from arbitrary directory names (e.g. a user's
    home directory), leaking information into the asset and into downstream
    JSON-LD emission.

    Mutates `asset.metadata.identity` in place; subsequent writes of the
    same asset reuse the materialised value.
    """
    if asset.metadata.identity is not None:
        return
    if not asset.metadata.slug:
        return

    from .cli import get_project_slug, get_project_version
    from .config import get_project_path

    try:
        project_path = get_project_path()
    except Exception:
        # No project path configured — skip default identity.
        return
    if project_path is None:
        return

    # Refuse to invent an identity when there's no project declaration.
    if not (project_path / "pyproject.toml").exists():
        return

    pkg_name = get_project_slug(project_path)
    pkg_version = get_project_version(project_path) or "0.0.0"
    asset.metadata.identity = f"{pkg_name}/{asset.metadata.slug}@{pkg_version}"


def write(asset: "Asset", path: str, *, format: str | None = None, **kw: object) -> None:
    """Write an `Asset` to `path`. Dispatches via the plugin registry.

    Raises `IncompatibleAssetKindError` if the selected handler does not
    support `asset.kind`.
    """
    _materialise_default_identity(asset)

    from .errors import IncompatibleAssetKindError
    from .plugins import PluginRegistry

    # Forward path/format into handler kwargs so legacy handlers that use them
    # for extension-based format inference keep working when the caller
    # omitted an explicit format. Symmetric with `_read_tabular_asset`.
    kw.setdefault("path", path)
    if format is not None:
        kw.setdefault("format", format)

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if not (hasattr(handler, "can_write") and handler.can_write(path, format)):  # type: ignore[attr-defined]
            continue
        supported = tuple(handler.supported_kinds())  # type: ignore[attr-defined]
        if asset.kind not in supported:
            raise IncompatibleAssetKindError(
                expected=supported[0] if supported else asset.kind,
                actual=asset.kind,
            )
        url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
        if url_handler is None:
            raise FileNotFoundError(path)
        with url_handler.open(path, "wb") as stream:
            handler.write(asset, stream, **kw)  # type: ignore[attr-defined]
        return
    raise ValueError(f"No handler for path={path!r} format={format!r}")


# --- Lazy attribute machinery (PEP 562) -------------------------------------
# Map of public attribute -> (submodule, attribute in submodule). Resolved on
# first access via ``__getattr__``; the result is cached in this module's
# globals so subsequent accesses are direct.
_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    # Asset envelope
    "Asset": ("sunstone.asset", "Asset"),
    "AssetKind": ("sunstone.asset", "AssetKind"),
    # Component
    "ComponentSchema": ("sunstone.component", "ComponentSchema"),
    # Project-path configuration
    "clear_project_path": ("sunstone.config", "clear_project_path"),
    "get_project_path": ("sunstone.config", "get_project_path"),
    "set_project_path": ("sunstone.config", "set_project_path"),
    "use_project_path": ("sunstone.config", "use_project_path"),
    # DataFrame and datasets manager
    "DataFrame": ("sunstone.dataframe", "DataFrame"),
    "DatasetsManager": ("sunstone.datasets", "DatasetsManager"),
    # Errors (sunstone-specific)
    "IncompatibleAssetKindError": ("sunstone.errors", "IncompatibleAssetKindError"),
    # Exceptions
    "DatasetNotFoundError": ("sunstone.exceptions", "DatasetNotFoundError"),
    "DatasetValidationError": ("sunstone.exceptions", "DatasetValidationError"),
    "LineageError": ("sunstone.exceptions", "LineageError"),
    "StrictModeError": ("sunstone.exceptions", "StrictModeError"),
    "SunstoneError": ("sunstone.exceptions", "SunstoneError"),
    "UnitError": ("sunstone.exceptions", "UnitError"),
    # RDF types
    "IRI": ("sunstone.rdf", "IRI"),
    "LangString": ("sunstone.rdf", "LangString"),
    "TypedLiteral": ("sunstone.rdf", "TypedLiteral"),
    # Lineage
    "Activity": ("sunstone.lineage", "Activity"),
    "ActivityRef": ("sunstone.lineage", "ActivityRef"),
    "Agent": ("sunstone.lineage", "Agent"),
    "AgentType": ("sunstone.lineage", "AgentType"),
    "Contributor": ("sunstone.lineage", "Contributor"),
    "DatasetMetadata": ("sunstone.lineage", "DatasetMetadata"),
    "EntityRef": ("sunstone.lineage", "EntityRef"),
    "FieldDerivation": ("sunstone.lineage", "FieldDerivation"),
    "FieldSchema": ("sunstone.lineage", "FieldSchema"),
    "LineageMetadata": ("sunstone.lineage", "LineageMetadata"),
    "Metadata": ("sunstone.lineage", "Metadata"),
    "PackageMetadata": ("sunstone.lineage", "PackageMetadata"),
    "Source": ("sunstone.lineage", "Source"),
    "SourceLocation": ("sunstone.lineage", "SourceLocation"),
    "UsageRecord": ("sunstone.lineage", "UsageRecord"),
    # Plugin system
    "AuthProvider": ("sunstone.plugins", "AuthProvider"),
    "CLIProvider": ("sunstone.plugins", "CLIProvider"),
    "FormatHandler": ("sunstone.plugins", "FormatHandler"),
    "PluginRegistry": ("sunstone.plugins", "PluginRegistry"),
    "URLHandler": ("sunstone.plugins", "URLHandler"),
    # Environment config
    "DataEnvironment": ("sunstone.env", "DataEnvironment"),
    "Environment": ("sunstone.env", "Environment"),
    "activate_environment": ("sunstone.env", "activate_environment"),
    "resolve_environment": ("sunstone.env", "resolve_environment"),
    # Validation
    "ImportCheckResult": ("sunstone.validation", "ImportCheckResult"),
    "check_notebook_imports": ("sunstone.validation", "check_notebook_imports"),
    "check_script_imports": ("sunstone.validation", "check_script_imports"),
    "validate_project_notebooks": ("sunstone.validation", "validate_project_notebooks"),
    # Linter
    "LintReport": ("sunstone.lint", "LintReport"),
    "LintSeverity": ("sunstone.lint", "Severity"),
    "Violation": ("sunstone.lint", "Violation"),
    "lint_project": ("sunstone.lint", "lint_project"),
    # Context / queries / session
    "ExecutionContext": ("sunstone.context", "ExecutionContext"),
    "detect_execution_context": ("sunstone.context", "detect_execution_context"),
    "LineageNode": ("sunstone.queries", "LineageNode"),
    "display_lineage": ("sunstone.queries", "display_lineage"),
    "get_upstream": ("sunstone.queries", "get_upstream"),
    "lineage_to_dict": ("sunstone.queries", "lineage_to_dict"),
    "DatasetRead": ("sunstone.session", "DatasetRead"),
    "LineageSession": ("sunstone.session", "LineageSession"),
    "close_session": ("sunstone.session", "close_session"),
    "get_session": ("sunstone.session", "get_session"),
}

# Submodules exposed via attribute access (`sunstone.<name>`).
_LAZY_SUBMODULES: frozenset[str] = frozenset({"errors", "packaging", "pandas"})


if TYPE_CHECKING:
    # Eager-looking imports for the benefit of type checkers and IDEs. These
    # statements are never executed at runtime; they only inform static
    # analysis about the surface available on the `sunstone` namespace.
    from . import errors, packaging, pandas  # noqa: F401
    from .asset import Asset, AssetKind  # noqa: F401
    from .component import ComponentSchema  # noqa: F401
    from .config import (  # noqa: F401
        clear_project_path,
        get_project_path,
        set_project_path,
        use_project_path,
    )
    from .context import ExecutionContext, detect_execution_context  # noqa: F401
    from .dataframe import DataFrame  # noqa: F401
    from .datasets import DatasetsManager  # noqa: F401
    from .env import (  # noqa: F401
        DataEnvironment,
        Environment,
        activate_environment,
        resolve_environment,
    )
    from .errors import IncompatibleAssetKindError  # noqa: F401
    from .exceptions import (  # noqa: F401
        DatasetNotFoundError,
        DatasetValidationError,
        LineageError,
        StrictModeError,
        SunstoneError,
        UnitError,
    )
    from .lineage import (  # noqa: F401
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
    from .lint import LintReport, Severity as LintSeverity, Violation, lint_project  # noqa: F401
    from .plugins import (  # noqa: F401
        AuthProvider,
        CLIProvider,
        FormatHandler,
        PluginRegistry,
        URLHandler,
    )
    from .queries import (  # noqa: F401
        LineageNode,
        display_lineage,
        get_upstream,
        lineage_to_dict,
    )
    from .rdf import IRI, LangString, TypedLiteral  # noqa: F401
    from .session import (  # noqa: F401
        DatasetRead,
        LineageSession,
        close_session,
        get_session,
    )
    from .validation import (  # noqa: F401
        ImportCheckResult,
        check_notebook_imports,
        check_script_imports,
        validate_project_notebooks,
    )


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS:
        mod_name, attr = _LAZY_ATTRS[name]
        module = importlib.import_module(mod_name)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"sunstone.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'sunstone' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS) | _LAZY_SUBMODULES)


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
    "activate_environment",
    "DataEnvironment",
    "Environment",
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
