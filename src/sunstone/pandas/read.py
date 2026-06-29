"""ReadMixin — read-side classmethods for the Sunstone DataFrame.

Consumed by ``sunstone.pandas.core.DataFrame`` via multiple inheritance. pandas
is imported eagerly: the caller has already opted into the pandas facade by
this point, so the top-level lazy-load property need not be preserved here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union, cast

import pandas as pd

from sunstone.config import get_project_path
from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetNotFoundError
from sunstone.lineage import LineageMetadata, Metadata

if TYPE_CHECKING:
    from sunstone.pandas.core import DataFrame  # noqa: F401  (type hint only)


class ReadMixin:
    """Read-side classmethods for the Sunstone DataFrame.

    Assumes the concrete subclass exposes a constructor taking ``data``,
    ``metadata``, ``strict``, ``project_path`` and a
    ``_get_default_strict_mode()`` staticmethod (declared as ``TYPE_CHECKING``
    stubs below for mypy).
    """

    if TYPE_CHECKING:

        def __init__(
            self,
            data: Any = None,
            metadata: Optional[Metadata] = None,
            strict: Optional[bool] = None,
            project_path: Optional[Union[str, Path]] = None,
            **kwargs: Any,
        ) -> None: ...

        @staticmethod
        def _get_default_strict_mode() -> bool: ...

    @classmethod
    def read_dataset(
        cls,
        slug: str,
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        format: Optional[str] = None,
        **kwargs: Any,
    ) -> "DataFrame":
        """Read a dataset by slug from ``datasets.yaml`` with format auto-detection.

        Looks up the dataset by ``slug`` and dispatches to a format handler
        plugin based on the file extension (or the ``format`` override).
        Built-in formats: CSV, JSON, Excel (``.xlsx``/``.xls``), Parquet, and
        TSV; additional formats are contributed by plugins.

        Args:
            slug: Dataset slug to look up in ``datasets.yaml``.
            project_path: Project directory containing ``datasets.yaml``.
            strict: Strict-mode override.
            fetch_from_url: Fetch from the dataset's source URL if the local file is missing.
            format: Format override (built-in: ``'csv'``, ``'json'``, ``'excel'``,
                ``'parquet'``, ``'tsv'``; plugins may add more); auto-detected when omitted.
            **kwargs: Forwarded to the format handler / pandas reader.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: ``slug`` not present in ``datasets.yaml``.
            FileNotFoundError: ``datasets.yaml`` doesn't exist.
            ValueError: No handler for the resolved format / extension.

        Example:
            >>> df = DataFrame.read_dataset('official-un-member-states', project_path='/path/to/project')
            >>> df = DataFrame.read_dataset('my-data', format='json', project_path='/path/to/project')
        """
        if project_path is None:
            project_path = get_project_path()

        manager = DatasetsManager(project_path)

        # Look up by slug
        dataset = manager.find_dataset_by_slug(slug)
        if dataset is None:
            raise DatasetNotFoundError(
                f"Dataset with slug '{slug}' not found in datasets.yaml. Check that the dataset is registered."
            )

        # Get the file path
        absolute_path = manager.get_absolute_path(dataset.location)

        # If file doesn't exist and we have a source URL, fetch it
        if not absolute_path.exists() and fetch_from_url:
            if dataset.source and dataset.source.location.data:
                absolute_path = manager.fetch_from_url(dataset)
            else:
                raise FileNotFoundError(
                    f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
                )

        # Find a format handler (plugin or builtin) for this file
        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)

        # A pinned format in datasets.yaml overrides extension detection.
        if format is None and dataset.format is not None:
            format = dataset.format

        # Try explicit format string first, then extension-based detection
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, format)

        if format_handler is None:
            extension = absolute_path.suffix.lower()
            detail = f"format={format!r}" if format else f"extension={extension!r}"
            raise ValueError(
                f"No format handler found for '{absolute_path.name}' ({detail}). "
                "Install the matching extra (e.g. `pip install sunstone-py[geo]` for "
                "geojson/topojson) or check the file extension."
            )

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from sunstone.plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(
                stream,
                format=format,
                path=location,
                dialect=dataset.dialect,
                **kwargs,
            )
        # Handlers may return either a bare DataFrame (legacy) or an Asset (v2+).
        from sunstone.asset import Asset as _Asset, AssetKind as _AssetKind
        from sunstone.errors import IncompatibleAssetKindError as _IncompatibleAssetKindError

        embedded_metadata: Optional[Metadata]
        if isinstance(result, _Asset):
            if result.kind is not _AssetKind.TABULAR:
                raise _IncompatibleAssetKindError(expected=_AssetKind.TABULAR, actual=result.kind)
            df = cast(pd.DataFrame, result.payload)
            # Prefer the Asset's metadata; fall back to df.attrs for handlers
            # that still leak metadata via the legacy channel.
            asset_meta = result.metadata
            embedded_metadata = asset_meta if asset_meta is not None else df.attrs.pop("sunstone_metadata", None)
            # An empty default Metadata() carries no useful info — treat as None.
            if embedded_metadata is not None and isinstance(embedded_metadata, Metadata):
                if (
                    embedded_metadata.slug is None
                    and embedded_metadata.name is None
                    and embedded_metadata.description is None
                    and not embedded_metadata.field_metadata
                    and not embedded_metadata.rdf_prefixes
                    and not embedded_metadata.custom_properties
                ):
                    embedded_metadata = None
        else:
            df = cast(pd.DataFrame, result)
            # Extract embedded metadata if the format handler provided it
            embedded_metadata = df.attrs.pop("sunstone_metadata", None)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), slug)

        # Merge embedded metadata (datasets.yaml wins on conflicts)
        if embedded_metadata is not None:
            # Description: datasets.yaml wins if set
            if metadata.description is None and embedded_metadata.description is not None:
                metadata.description = embedded_metadata.description
            # Field metadata: datasets.yaml fields override, embedded fills gaps
            for col, field_schema in embedded_metadata.field_metadata.items():
                if col not in metadata.field_metadata:
                    metadata.field_metadata[col] = field_schema
            # RDF prefixes: merge, datasets.yaml wins on duplicate
            if embedded_metadata.rdf_prefixes:
                if metadata.rdf_prefixes is None:
                    metadata.rdf_prefixes = {}
                merged = dict(embedded_metadata.rdf_prefixes)
                merged.update(metadata.rdf_prefixes)
                metadata.rdf_prefixes = merged
            # Custom properties: merge, datasets.yaml wins on duplicate
            if embedded_metadata.custom_properties:
                if metadata.custom_properties is None:
                    metadata.custom_properties = {}
                merged_props = dict(embedded_metadata.custom_properties)
                merged_props.update(metadata.custom_properties)
                metadata.custom_properties = merged_props

        # Record read in lineage session
        from sunstone.session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=slug))

        # Return wrapped DataFrame
        return cast(
            "DataFrame",
            cls(data=df, metadata=metadata, strict=strict, project_path=project_path),
        )

    @classmethod
    def read_csv(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """Read a CSV file into a Sunstone DataFrame.

        Equivalent to ``read_dataset`` with ``format='csv'``. ``filepath_or_buffer``
        may be a dataset slug or a file path; the dataset must be registered in
        ``datasets.yaml``. See ``read_dataset`` for argument and exception docs.
        """
        location = str(filepath_or_buffer)

        # Determine if this is a slug or a file path
        # Slugs don't contain path separators and typically use kebab-case
        is_slug = "/" not in location and "\\" not in location and not Path(location).suffix

        if is_slug:
            # Delegate to read_dataset with CSV format
            return cls.read_dataset(
                slug=location,
                project_path=project_path,
                strict=strict,
                fetch_from_url=fetch_from_url,
                format="csv",
                **kwargs,
            )

        # File path - handle with original logic
        if project_path is None:
            project_path = get_project_path()

        manager = DatasetsManager(project_path)

        # Look up by location
        dataset = manager.find_dataset_by_location(location)
        if dataset is None:
            if strict or (strict is None and cls._get_default_strict_mode()):
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. "
                    f"In strict mode, all datasets must be registered."
                )
            else:
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. Please add it to datasets.yaml first."
                )

        # Use the requested location
        absolute_path = manager.get_absolute_path(location)

        # If file doesn't exist and we have a source URL, fetch it
        if not absolute_path.exists() and fetch_from_url:
            if dataset.source and dataset.source.location.data:
                absolute_path = manager.fetch_from_url(dataset)
            else:
                raise FileNotFoundError(
                    f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
                )

        # Read via format handler registry
        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "csv")
        if format_handler is None:
            raise ValueError("No format handler found for CSV files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from sunstone.plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(
                stream,
                format="csv",
                path=location,
                dialect=dataset.dialect,
                **kwargs,
            )
        from sunstone.asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from sunstone.session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cast(
            "DataFrame",
            cls(data=df, metadata=metadata, strict=strict, project_path=project_path),
        )

    @classmethod
    def read_excel(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """Read an Excel file into a Sunstone DataFrame.

        Equivalent to ``read_dataset`` with ``format='excel'``. ``filepath_or_buffer``
        may be a dataset slug or a file path; the dataset must be registered in
        ``datasets.yaml``. See ``read_dataset`` for argument and exception docs.
        """
        location = str(filepath_or_buffer)

        # Determine if this is a slug or a file path
        is_slug = "/" not in location and "\\" not in location and not Path(location).suffix

        if is_slug:
            return cls.read_dataset(
                slug=location,
                project_path=project_path,
                strict=strict,
                fetch_from_url=fetch_from_url,
                format="excel",
                **kwargs,
            )

        # File path - handle with original logic
        if project_path is None:
            project_path = get_project_path()

        manager = DatasetsManager(project_path)

        # Look up by location
        dataset = manager.find_dataset_by_location(location)
        if dataset is None:
            if strict or (strict is None and cls._get_default_strict_mode()):
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. "
                    f"In strict mode, all datasets must be registered."
                )
            else:
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. Please add it to datasets.yaml first."
                )

        # Use the requested location
        absolute_path = manager.get_absolute_path(location)

        # If file doesn't exist and we have a source URL, fetch it
        if not absolute_path.exists() and fetch_from_url:
            if dataset.source and dataset.source.location.data:
                absolute_path = manager.fetch_from_url(dataset)
            else:
                raise FileNotFoundError(
                    f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
                )

        # Read via format handler registry
        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "excel")
        if format_handler is None:
            raise ValueError("No format handler found for Excel files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from sunstone.plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(stream, format="excel", path=location, **kwargs)
        from sunstone.asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from sunstone.session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cast(
            "DataFrame",
            cls(data=df, metadata=metadata, strict=strict, project_path=project_path),
        )

    @classmethod
    def read_json(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """Read a JSON file into a Sunstone DataFrame.

        Equivalent to ``read_dataset`` with ``format='json'``. ``filepath_or_buffer``
        may be a dataset slug or a file path; the dataset must be registered in
        ``datasets.yaml``. See ``read_dataset`` for argument and exception docs.
        """
        location = str(filepath_or_buffer)

        # Determine if this is a slug or a file path
        is_slug = "/" not in location and "\\" not in location and not Path(location).suffix

        if is_slug:
            return cls.read_dataset(
                slug=location,
                project_path=project_path,
                strict=strict,
                fetch_from_url=fetch_from_url,
                format="json",
                **kwargs,
            )

        # File path - handle with original logic
        if project_path is None:
            project_path = get_project_path()

        manager = DatasetsManager(project_path)

        # Look up by location
        dataset = manager.find_dataset_by_location(location)
        if dataset is None:
            if strict or (strict is None and cls._get_default_strict_mode()):
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. "
                    f"In strict mode, all datasets must be registered."
                )
            else:
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. Please add it to datasets.yaml first."
                )

        # Use the requested location
        absolute_path = manager.get_absolute_path(location)

        # If file doesn't exist and we have a source URL, fetch it
        if not absolute_path.exists() and fetch_from_url:
            if dataset.source and dataset.source.location.data:
                absolute_path = manager.fetch_from_url(dataset)
            else:
                raise FileNotFoundError(
                    f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
                )

        # Read via format handler registry
        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "json")
        if format_handler is None:
            raise ValueError("No format handler found for JSON files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from sunstone.plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(stream, format="json", path=location, **kwargs)
        from sunstone.asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from sunstone.session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cast(
            "DataFrame",
            cls(data=df, metadata=metadata, strict=strict, project_path=project_path),
        )
