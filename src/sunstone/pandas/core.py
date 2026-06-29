"""
DataFrame wrapper with lineage tracking for Sunstone projects.

This module is the canonical home of :class:`sunstone.pandas.core.DataFrame`.
For backwards compatibility, ``sunstone.dataframe`` re-exports ``DataFrame``
(and a couple of helper symbols) from here; downstream code should prefer
``from sunstone.pandas import DataFrame`` or ``from sunstone.pandas.core
import DataFrame`` going forward.
"""

import os
import warnings
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union, cast

import pandas as pd

from ..config import get_project_path
from ..datasets import DatasetsManager
from ..lineage import FieldSchema, LineageMetadata, Metadata, compute_dataframe_hash
from .metadata import MetadataMixin
from .ops import OpsMixin
from .read import ReadMixin
from .write import WriteMixin

# `compute_dataframe_hash` is re-exported at this module path so tests that
# monkeypatch ``sunstone.dataframe.compute_dataframe_hash`` continue to find
# the attribute after the Write-side refactor moved its only call site into
# ``sunstone.pandas.write``. Mark as used so linters don't strip the import.
_ = compute_dataframe_hash

if TYPE_CHECKING:
    from ..asset import Asset

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    pd.options.mode.copy_on_write = True


class DataFrame(ReadMixin, WriteMixin, MetadataMixin, OpsMixin):
    """
    A pandas DataFrame wrapper that maintains lineage metadata.

    This class wraps a pandas DataFrame and tracks the provenance of the data,
    ensuring that all reads and writes are registered in datasets.yaml files.

    Attributes:
        data: The underlying pandas DataFrame.
        lineage: Lineage metadata tracking data provenance.
        strict_mode: Whether to operate in strict mode.
    """

    def __init__(
        self,
        data: Any = None,
        lineage: Optional[LineageMetadata] = None,
        metadata: Optional[Metadata] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        datasets_file: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ):
        """
        Initialize a Sunstone DataFrame.

        Internally backed by an :class:`~sunstone.asset.Asset` of
        ``kind=AssetKind.TABULAR``. ``df.metadata is df.asset.metadata``
        and ``df.data is df.asset.payload``.

        Args:
            data: Data to wrap. Can be a pandas DataFrame or any data accepted
                 by pandas.DataFrame() constructor (dict, list of dicts, etc.).
            lineage: Optional lineage metadata. Deprecated: use metadata= instead.
            metadata: Optional unified metadata container.
            strict: Whether to operate in strict mode. If None, reads from
                   SUNSTONE_DATAFRAME_STRICT environment variable.
            project_path: Path to the project directory. If None, uses current directory.
            datasets_file: Path to a specific datasets YAML file (relative to
                project_path or absolute). Defaults to "datasets.yaml".
            **kwargs: Additional arguments passed to pandas.DataFrame constructor.

        Note:
            Strict mode behavior:
            - strict=True: Operations that would modify datasets.yaml will fail
            - strict=False (relaxed): datasets.yaml will be updated as needed
            - Default is determined by SUNSTONE_DATAFRAME_STRICT env var
              ("1" or "true" -> strict mode, otherwise relaxed mode)
        """
        from ..asset import Asset, AssetKind

        # Normalise data into a pandas DataFrame payload
        if data is None:
            payload = pd.DataFrame(**kwargs)
        elif isinstance(data, pd.DataFrame):
            payload = data
        else:
            # data is some other type (dict, list, etc.) - pass to pandas
            payload = pd.DataFrame(data, **kwargs)

        # Unified metadata container
        if metadata is not None:
            meta = metadata
        elif lineage is not None:
            meta = Metadata(lineage=lineage)
        else:
            meta = Metadata()

        # Construct the underlying Asset BEFORE any property setter is invoked.
        # The .data and .metadata setters route through self._asset and would
        # AttributeError if _asset isn't on the instance yet.
        self._asset = Asset(payload=payload, kind=AssetKind.TABULAR, metadata=meta)

        # Determine strict mode
        if strict is None:
            env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
            self.strict_mode = env_strict in ("1", "true")
        else:
            self.strict_mode = strict

        # Set project path (goes through self.metadata -> self._asset.metadata)
        if project_path is not None:
            self.metadata.lineage.project_path = str(Path(project_path).resolve())
        elif self.metadata.lineage.project_path is None:
            self.metadata.lineage.project_path = str(get_project_path())

        # Store datasets file override
        self._datasets_file = datasets_file

    @property
    def asset(self) -> "Asset":
        """The underlying :class:`~sunstone.asset.Asset` (kind=TABULAR).

        ``df.metadata is df.asset.metadata`` and ``df.data is df.asset.payload``
        — facade and asset share the same metadata and payload references.
        """
        return self._asset

    @property
    def data(self) -> pd.DataFrame:
        """The underlying pandas DataFrame payload."""
        return cast(pd.DataFrame, self._asset.payload)

    @data.setter
    def data(self, value: pd.DataFrame) -> None:
        self._asset.payload = value

    @property
    def metadata(self) -> Metadata:
        """The unified :class:`~sunstone.lineage.Metadata` container."""
        return self._asset.metadata

    @metadata.setter
    def metadata(self, value: Metadata) -> None:
        self._asset.metadata = value

    def _get_datasets_manager(self) -> DatasetsManager:
        """Get a DatasetsManager for the current project."""
        if self.metadata.lineage.project_path is None:
            raise ValueError("Project path not set")
        from ..datasets import get_datasets_manager

        return get_datasets_manager(
            self.metadata.lineage.project_path,
            datasets_file=self._datasets_file,
        )

    @staticmethod
    def _get_default_strict_mode() -> bool:
        """Get the default strict mode from environment variable."""
        env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
        return env_strict in ("1", "true")

    # Sunstone-specific kwargs that should not be passed to pandas
    _SUNSTONE_KWARGS = {"publish", "transformation_params", "sources"}

    def _wrap_result(self, result: Any) -> Any:
        """Wrap a pandas result in a Sunstone DataFrame if applicable.

        Copies all metadata, dropping field_metadata and field_derivations
        for columns no longer present.
        """
        if isinstance(result, pd.DataFrame):
            new_field_meta = {k: replace(v) for k, v in self.metadata.field_metadata.items() if k in result.columns}

            # Filter field_derivations to surviving columns
            src_derivations = self.metadata.lineage.field_derivations
            new_derivations = None
            if src_derivations:
                new_derivations = [fd for fd in src_derivations if fd.output_field in result.columns]
                if not new_derivations:
                    new_derivations = None

            new_metadata = Metadata(
                lineage=LineageMetadata(
                    sources=self.metadata.lineage.sources.copy(),
                    project_path=self.metadata.lineage.project_path,
                    field_derivations=new_derivations,
                ),
                description=self.metadata.description,
                rdf_prefixes=self.metadata.rdf_prefixes,
                custom_properties=self.metadata.custom_properties,
                field_metadata=new_field_meta,
                slug=self.metadata.slug,
                name=self.metadata.name,
            )
            return DataFrame(
                data=result,
                metadata=new_metadata,
                strict=self.strict_mode,
            )
        return result

    def __getattr__(self, name: str) -> Any:
        """
        Delegate attribute access to the underlying pandas DataFrame.

        Args:
            name: Attribute name.

        Returns:
            The attribute from the underlying DataFrame, wrapped if it's a method or DataFrame.
        """
        # Guard against recursion during __init__/unpickling: if our internal
        # `_asset` isn't on the instance yet, do NOT route through self.data
        # (which would call __getattr__('_asset') -> infinite recursion).
        if name == "_asset" or name.startswith("__"):
            raise AttributeError(name)

        # Special handling for pandas indexers - return as-is
        if name in ("loc", "iloc", "at", "iat"):
            return getattr(self.data, name)

        attr = getattr(self.data, name)

        if callable(attr):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                result = attr(*args, **kwargs)
                return self._wrap_result(result)

            return wrapper

        return self._wrap_result(attr)

    def __getitem__(self, key: Any) -> Any:
        """
        Delegate item access to the underlying pandas DataFrame.

        Args:
            key: Index key.

        Returns:
            The item from the underlying DataFrame, wrapped if it's a DataFrame.
        """
        result = self.data[key]
        if isinstance(result, pd.Series) and isinstance(key, str):
            field = self.metadata.field_metadata.get(key)
            if field and field.unit:
                from ..units import UnitSeries, try_parse_unit

                unit = try_parse_unit(field.unit)
                if unit is not None:
                    display: str = getattr(self, "_unit_display", "transparent")
                    return UnitSeries(result, unit, unit_display=display)  # type: ignore[arg-type]
        return self._wrap_result(result)

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Delegate item assignment to the underlying pandas DataFrame.

        Args:
            key: Index key.
            value: Value to assign.
        """
        from ..units import UnitSeries

        if isinstance(value, UnitSeries):
            self.data[key] = value.series
            unit_str = str(value.unit)
            existing = self.metadata.field_metadata.get(key)
            if existing:
                existing.unit = unit_str
                existing.unit_source = None  # clear stale QUDT URI
            else:
                self.metadata.field_metadata[key] = FieldSchema(name=key, unit=unit_str)
        else:
            self.data[key] = value
        # Don't track column assignments automatically
        # Users should use add_operation() for meaningful transformations

    def __repr__(self) -> str:
        """String representation of the DataFrame."""
        lineage_info = f"\n\nLineage: {len(self.metadata.lineage.sources)} source(s)"
        return repr(self.data) + lineage_info

    def __str__(self) -> str:
        """String representation of the DataFrame."""
        return str(self.data)

    def __len__(self) -> int:
        """Return the number of rows in the DataFrame."""
        return len(self.data)

    def __iter__(self) -> Any:
        """Iterate over column names."""
        return iter(self.data)


def _read_tabular_asset(path: str, *, format: Optional[str] = None, **kw: Any) -> "Asset":
    """Internal helper: resolve a path to a tabular `Asset`, going through the
    plugin registry (which wraps DataFrame-returning handlers via
    `TabularDataFrameAdapter`).

    Used by `read_csv` / `read_excel` / `read_dataset` after this refactor.
    Returns the raw asset; callers can `.payload` it back to a DataFrame or
    keep it as an Asset.
    """
    from ..asset import Asset
    from ..plugins import PluginRegistry

    # Forward path/format into handler kwargs so legacy handlers that use them
    # for extension-based format inference (e.g. BuiltinFormatHandler) keep
    # working when the caller omitted an explicit format.
    kw.setdefault("path", path)
    if format is not None:
        kw.setdefault("format", format)

    registry = PluginRegistry.get()
    for handler in registry.get_asset_format_handlers():
        if hasattr(handler, "can_read") and handler.can_read(path, format):  # type: ignore[attr-defined]
            url_handler = registry.find_url_handler(path) or registry.find_url_handler(f"file://{path}")
            if url_handler is None:
                raise FileNotFoundError(path)
            with url_handler.open(path, "rb") as stream:
                return cast(Asset, handler.read(stream, **kw))  # type: ignore[attr-defined]
    raise ValueError(f"No handler for path={path!r} format={format!r}")
