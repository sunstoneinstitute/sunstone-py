"""
DataFrame wrapper with lineage tracking for Sunstone projects.
"""

import os
import warnings
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

import pandas as pd

from .config import get_project_path
from .datasets import DatasetsManager
from .exceptions import DatasetNotFoundError, StrictModeError
from .lineage import DatasetMetadata, FieldSchema, LineageMetadata, Metadata, compute_dataframe_hash

if TYPE_CHECKING:
    from .asset import Asset

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    pd.options.mode.copy_on_write = True


class DataFrame:
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
        from .asset import Asset, AssetKind

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

    @property
    def lineage(self) -> LineageMetadata:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.metadata.lineage

    @lineage.setter
    def lineage(self, value: LineageMetadata) -> None:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        self.metadata.lineage = value

    @property
    def description(self) -> Optional[str]:
        """Dataset description. Delegates to metadata.description."""
        return self.metadata.description

    @description.setter
    def description(self, value: Optional[str]) -> None:
        self.metadata.description = value

    @property
    def rdf_prefixes(self) -> Optional[Dict[str, str]]:
        """RDF namespace prefixes. Delegates to metadata.rdf_prefixes."""
        return self.metadata.rdf_prefixes

    @rdf_prefixes.setter
    def rdf_prefixes(self, value: Optional[Dict[str, str]]) -> None:
        self.metadata.rdf_prefixes = value

    @property
    def custom_properties(self) -> Optional[Dict[str, Any]]:
        """Custom properties. Delegates to metadata.custom_properties."""
        return self.metadata.custom_properties

    @custom_properties.setter
    def custom_properties(self, value: Optional[Dict[str, Any]]) -> None:
        self.metadata.custom_properties = value

    @property
    def unit_display(self) -> str:
        """Unit display mode: 'transparent' (default) or 'explicit'."""
        return getattr(self, "_unit_display", "transparent")

    @unit_display.setter
    def unit_display(self, value: str) -> None:
        self._unit_display = value

    def set_field_metadata(
        self,
        column: str,
        *,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        source: Optional[str] = None,
        type: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> "DataFrame":
        """Set metadata for a column. Returns self for chaining.

        Args:
            column: Column name to annotate.
            description: Human-readable description of the field.
            unit: Unit of measure (e.g., 'kg', 'students').
            source: Slug of the input dataset this field comes from.
            type: Data type override. If None, inferred from dtype at write time.
            constraints: Optional constraints (e.g., enum values).
            custom_properties: Optional field-level RDF/custom properties
                (e.g. ``{"sosa:observedProperty": "..."}``) that flow to
                datasets.yaml and datapackage.json.

        Returns:
            self, for method chaining.
        """
        if unit is not None:
            from .units import get_unit_mode, parse_unit_string

            if get_unit_mode() != "relaxed":
                parse_unit_string(unit)  # raises UnitError if invalid in strict/auto mode

        existing = self.metadata.field_metadata.get(column)
        if existing:
            if description is not None:
                existing.description = description
            if unit is not None:
                existing.unit = unit
            if source is not None:
                existing.source = source
            if type is not None:
                existing.type = type
            if constraints is not None:
                existing.constraints = constraints
            if custom_properties is not None:
                merged = dict(existing.custom_properties or {})
                merged.update(custom_properties)
                existing.custom_properties = merged or None
        else:
            self.metadata.field_metadata[column] = FieldSchema(
                name=column,
                type=type,
                description=description,
                unit=unit,
                source=source,
                constraints=constraints,
                custom_properties=custom_properties or None,
            )

        # When source is set, also create a FieldDerivation entry
        if source is not None:
            from .lineage import FieldDerivation

            fd = FieldDerivation(output_field=column, source_entity=source)
            if self.metadata.lineage.field_derivations is None:
                self.metadata.lineage.field_derivations = []
            # Replace existing derivation for this column if present
            self.metadata.lineage.field_derivations = [
                d for d in self.metadata.lineage.field_derivations if d.output_field != column
            ]
            self.metadata.lineage.field_derivations.append(fd)

        return self

    def _get_datasets_manager(self) -> DatasetsManager:
        """Get a DatasetsManager for the current project."""
        if self.metadata.lineage.project_path is None:
            raise ValueError("Project path not set")
        return DatasetsManager(
            self.metadata.lineage.project_path,
            datasets_file=self._datasets_file,
        )

    def _enforce_license_compatibility(
        self,
        manager: DatasetsManager,
        dataset_slug: str,
        target_license: Optional[str],
    ) -> None:
        """Check the proposed write against source licenses.

        When no target license is declared, auto-derives one from the source
        licenses (the single source's license, or the most restrictive license
        that satisfies every source) and persists it to the output dataset.

        Raises :class:`LicenseCompatibilityError` if the target license is
        incompatible with any source license — or if no compatible default
        can be derived (e.g., mutually incompatible ShareAlike families).
        """
        from .licenses import (
            LicenseCompatibilityError,
            check_compatibility,
            derive_compatible_target,
        )
        from .session import get_session

        source_slugs = get_session().current_source_slugs()
        source_licenses: list[str] = []
        for slug in source_slugs:
            ds = manager.find_dataset_by_slug(slug)
            if ds is None:
                continue
            if ds.dataset_type == "input" and ds.source is not None and ds.source.license:
                source_licenses.append(ds.source.license)
            elif ds.dataset_type == "output":
                eff = manager.effective_license_for(slug)
                if eff:
                    source_licenses.append(eff)

        if not source_licenses:
            return

        if target_license is None:
            derived = derive_compatible_target(source_licenses)
            if derived is None:
                unique = sorted(set(source_licenses))
                raise LicenseCompatibilityError(
                    f"Output '{dataset_slug}' has source datasets with licenses "
                    f"{unique} but no compatible default license can be derived "
                    f"(mutually incompatible or contains unknown identifiers). "
                    f"Set 'license:' on the dataset, on a package, or pass "
                    f"license= to the writer."
                )
            manager.update_output_dataset(slug=dataset_slug, license=derived)
            target_license = derived

        result = check_compatibility(source_licenses, target_license)
        if result.compatible:
            return

        message_lines = [f"License compatibility check failed for output '{dataset_slug}' (target: {target_license})."]
        message_lines.extend(f"  - {c}" for c in result.conflicts)
        if result.suggestions:
            message_lines.append("Suggested compatible target licenses: " + ", ".join(result.suggestions))
        if result.unknown_sources:
            message_lines.append("Unknown source licenses (not validated): " + ", ".join(result.unknown_sources))
        raise LicenseCompatibilityError("\n".join(message_lines))

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
        """
        Read a dataset by slug from datasets.yaml with format auto-detection.

        This method looks up a dataset by its slug in datasets.yaml and automatically
        detects the file format from the file extension unless explicitly specified.

        Supported formats:
        - CSV (.csv)
        - JSON (.json)
        - Excel (.xlsx, .xls)
        - Parquet (.parquet)
        - TSV (.tsv, .txt with tab delimiter)

        Args:
            slug: Dataset slug to look up in datasets.yaml.
            project_path: Path to project directory containing datasets.yaml.
            strict: Whether to operate in strict mode.
            fetch_from_url: If True and dataset has a source URL but no local file,
                          automatically fetch from URL.
            format: Optional format override ('csv', 'json', 'excel', 'parquet', 'tsv').
                   If not provided, format is auto-detected from file extension.
            **kwargs: Additional arguments passed to the pandas reader function.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: If dataset with slug not found in datasets.yaml.
            FileNotFoundError: If datasets.yaml doesn't exist.
            ValueError: If format cannot be detected or is unsupported.

        Examples:
            >>> # Auto-detect format from extension
            >>> df = DataFrame.read_dataset('official-un-member-states', project_path='/path/to/project')
            >>>
            >>> # Explicitly specify format
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
        from .plugins import PluginRegistry

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
            from .plugins import no_url_handler_error

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
        from .asset import Asset as _Asset, AssetKind as _AssetKind
        from .errors import IncompatibleAssetKindError as _IncompatibleAssetKindError

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
        from .session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=slug))

        # Return wrapped DataFrame
        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)

    @classmethod
    def read_csv(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """
        Read a CSV file into a Sunstone DataFrame.

        The file must be registered in datasets.yaml, otherwise this will fail
        (or in relaxed mode, register it automatically).

        Args:
            filepath_or_buffer: Path to CSV file, URL, or dataset slug.
                              If it's a slug (e.g., 'official-un-member-states'),
                              the dataset will be looked up in datasets.yaml.
            project_path: Path to project directory containing datasets.yaml.
            strict: Whether to operate in strict mode.
            fetch_from_url: If True and dataset has a source URL but no local file,
                          automatically fetch from URL.
            **kwargs: Additional arguments passed to pandas.read_csv.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: In strict mode, if dataset not found in datasets.yaml.
            FileNotFoundError: If datasets.yaml doesn't exist.

        Examples:
            >>> # Load by slug
            >>> df = DataFrame.read_csv('official-un-member-states', project_path='/path/to/project')
            >>>
            >>> # Load by file path
            >>> df = DataFrame.read_csv('inputs/data.csv', project_path='/path/to/project')
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
        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "csv")
        if format_handler is None:
            raise ValueError("No format handler found for CSV files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from .plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(
                stream,
                format="csv",
                path=location,
                dialect=dataset.dialect,
                **kwargs,
            )
        from .asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from .session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)

    @classmethod
    def read_excel(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """
        Read an Excel file into a Sunstone DataFrame.

        The file must be registered in datasets.yaml, otherwise this will fail
        (or in relaxed mode, register it automatically).

        Args:
            filepath_or_buffer: Path to Excel file or dataset slug.
                              If it's a slug (e.g., 'my-excel-data'),
                              the dataset will be looked up in datasets.yaml.
            project_path: Path to project directory containing datasets.yaml.
            strict: Whether to operate in strict mode.
            fetch_from_url: If True and dataset has a source URL but no local file,
                          automatically fetch from URL.
            **kwargs: Additional arguments passed to pandas.read_excel.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: In strict mode, if dataset not found in datasets.yaml.
            FileNotFoundError: If datasets.yaml doesn't exist.

        Examples:
            >>> # Load by slug
            >>> df = DataFrame.read_excel('my-excel-data', project_path='/path/to/project')
            >>>
            >>> # Load by file path
            >>> df = DataFrame.read_excel('inputs/data.xlsx', project_path='/path/to/project')
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
        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "excel")
        if format_handler is None:
            raise ValueError("No format handler found for Excel files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from .plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(stream, format="excel", path=location, **kwargs)
        from .asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from .session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)

    @classmethod
    def read_json(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        fetch_from_url: bool = True,
        **kwargs: Any,
    ) -> "DataFrame":
        """
        Read a JSON file into a Sunstone DataFrame.

        The file must be registered in datasets.yaml, otherwise this will fail
        (or in relaxed mode, register it automatically).

        Args:
            filepath_or_buffer: Path to JSON file or dataset slug.
                              If it's a slug (e.g., 'my-json-data'),
                              the dataset will be looked up in datasets.yaml.
            project_path: Path to project directory containing datasets.yaml.
            strict: Whether to operate in strict mode.
            fetch_from_url: If True and dataset has a source URL but no local file,
                          automatically fetch from URL.
            **kwargs: Additional arguments passed to pandas.read_json.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: In strict mode, if dataset not found in datasets.yaml.
            FileNotFoundError: If datasets.yaml doesn't exist.

        Examples:
            >>> # Load by slug
            >>> df = DataFrame.read_json('my-json-data', project_path='/path/to/project')
            >>>
            >>> # Load by file path
            >>> df = DataFrame.read_json('inputs/data.json', project_path='/path/to/project')
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
        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "json")
        if format_handler is None:
            raise ValueError("No format handler found for JSON files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            from .plugins import no_url_handler_error

            raise no_url_handler_error(location)

        with url_handler.open(location, "rb") as stream:
            result = format_handler.read(stream, format="json", path=location, **kwargs)
        from .asset import Asset as _Asset

        df = cast(pd.DataFrame, result.payload if isinstance(result, _Asset) else result)

        # Create lineage metadata
        metadata = Metadata(lineage=LineageMetadata(project_path=str(manager.project_path)))
        metadata.lineage.add_source(dataset)
        metadata.lineage.populate_field_derivations(list(df.columns), dataset.slug)

        # Record read in lineage session
        from .session import DatasetRead, get_session

        get_session().record_read(DatasetRead(slug=dataset.slug))

        # Return wrapped DataFrame
        return cls(data=df, metadata=metadata, strict=strict, project_path=project_path)

    @staticmethod
    def _get_default_strict_mode() -> bool:
        """Get the default strict mode from environment variable."""
        env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
        return env_strict in ("1", "true")

    # Sunstone-specific kwargs that should not be passed to pandas
    _SUNSTONE_KWARGS = {"publish", "transformation_params", "sources"}

    def to_csv(
        self,
        path_or_buf: Union[str, Path],
        slug: Optional[str] = None,
        name: Optional[str] = None,
        publish: bool = False,
        transformation_params: Optional[dict] = None,
        track: bool = True,
        license: Optional[str] = None,
        check_license: bool = True,
        sources: Optional[List[DatasetMetadata]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Write DataFrame to CSV file.

        In strict mode, the output must already be registered in datasets.yaml.
        In relaxed mode, it will be registered automatically if not present.

        Args:
            path_or_buf: File path for the output CSV.
            slug: Dataset slug (required in relaxed mode if not registered).
            name: Dataset name (required in relaxed mode if not registered).
            publish: Reserved for future use (publishing to data catalog).
            track: If False, write the CSV directly without lineage tracking
                or dataset registration. Useful for tests and exploratory work.
            license: SPDX license identifier for the output. Persisted to
                datasets.yaml and used for compatibility checking against
                source licenses. Falls back to the dataset's existing license
                or ``package.license`` when omitted.
            check_license: If True (default), raise
                :class:`~sunstone.licenses.LicenseCompatibilityError` when
                the target license is incompatible with any source license
                in the current session lineage.
            **kwargs: Additional arguments passed to pandas.to_csv.

        Raises:
            StrictModeError: In strict mode, if dataset not registered.
            ValueError: In relaxed mode, if slug/name not provided for new dataset.
            LicenseCompatibilityError: If ``check_license`` is True and the
                target license conflicts with a source license.
        """
        # Filter out any Sunstone-specific kwargs that might have slipped through
        pandas_kwargs = {k: v for k, v in kwargs.items() if k not in self._SUNSTONE_KWARGS}

        if not track:
            from .plugins import PluginRegistry

            registry = PluginRegistry.get(
                Path(self.metadata.lineage.project_path) if self.metadata.lineage.project_path is not None else None
            )
            location = str(path_or_buf)

            url_handler = registry.find_url_handler(location)
            if url_handler:
                with url_handler.open(location, "wb") as stream:
                    self.data.to_csv(stream, **pandas_kwargs)
            else:
                path = Path(path_or_buf)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.data.to_csv(path, **pandas_kwargs)
            return

        manager = self._get_datasets_manager()
        location = str(path_or_buf)

        # Try to find existing dataset
        dataset = manager.find_dataset_by_location(location, "output")

        if dataset is None:
            if self.strict_mode:
                raise StrictModeError(
                    f"Output dataset at '{location}' not registered in datasets.yaml. "
                    f"In strict mode, outputs must be pre-registered."
                )
            else:
                # Relaxed mode: auto-register
                effective_slug = slug or self.metadata.slug
                effective_name = name or self.metadata.name
                if effective_slug is None or effective_name is None:
                    raise ValueError(
                        "In relaxed mode, 'slug' and 'name' are required "
                        "when writing to an unregistered output location. "
                        "Set them via to_csv() parameters or df.metadata.slug/name."
                    )

                # Build field schema merging explicit metadata with inferred dtypes
                fields = self._build_field_schema()

                # Register the new output with full metadata
                dataset = manager.add_output_dataset(
                    name=effective_name,
                    slug=effective_slug,
                    location=location,
                    fields=fields,
                    description=self.metadata.description,
                    rdf_prefixes=self.metadata.rdf_prefixes,
                    custom_properties=self.metadata.custom_properties,
                    license=license,
                )
        elif license is not None and dataset.license != license:
            # Persist explicit override on a pre-registered dataset
            dataset = manager.update_output_dataset(slug=dataset.slug, license=license)

        if check_license:
            target_license = license or manager.effective_license_for(dataset.slug)
            self._enforce_license_compatibility(manager, dataset.slug, target_license)

        # Write the data
        absolute_path = manager.get_absolute_path(dataset.location)

        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)

        url_handler = registry.find_url_handler(location)
        format_writer = registry.find_format_writer(location, None)

        dialect = dataset.dialect if dataset is not None else None
        if url_handler and format_writer:
            with url_handler.open(location, "wb") as stream:
                format_writer.write(self.data, stream, format=None, path=location, dialect=dialect, **pandas_kwargs)
        elif format_writer:
            with open(absolute_path, "wb") as stream:
                format_writer.write(self.data, stream, format=None, path=location, dialect=dialect, **pandas_kwargs)
        else:
            self.data.to_csv(absolute_path, **pandas_kwargs)

        # Compute data hash for change detection
        data_hash = compute_dataframe_hash(self.data)

        # Flush session lineage with execution context
        from .session import get_session

        session = get_session()
        lineage_data = session.flush_to_output(transformation_params=transformation_params)

        # Resolve effective lineage sources:
        # 1. Explicit sources= parameter takes priority
        # 2. DataFrame's own lineage sources (from read/merge/concat)
        # 3. Fall back to session-accumulated sources (when sources is None)
        effective_lineage = self.metadata.lineage
        if sources is not None:
            effective_lineage.sources = list(sources)
        elif not effective_lineage.sources and lineage_data.get("sources"):
            for src in lineage_data["sources"]:
                src_dataset = manager.find_dataset_by_slug(src["slug"])
                if src_dataset:
                    effective_lineage.add_source(src_dataset)

        # Persist lineage metadata to datasets.yaml
        manager.update_output_lineage(
            slug=dataset.slug,
            lineage=effective_lineage,
            data_hash=data_hash,
            strict=self.strict_mode,
            context=lineage_data.get("context"),
            transformation_params=lineage_data.get("transformation_params"),
            activity=lineage_data.get("_activity"),
        )

    def to_parquet(
        self,
        path_or_buf: Union[str, Path],
        slug: Optional[str] = None,
        name: Optional[str] = None,
        publish: bool = False,
        transformation_params: Optional[dict] = None,
        track: bool = True,
        license: Optional[str] = None,
        check_license: bool = True,
        sources: Optional[List[DatasetMetadata]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Write DataFrame to Parquet file.

        In strict mode, the output must already be registered in datasets.yaml.
        In relaxed mode, it will be registered automatically if not present.

        Args:
            path_or_buf: File path for the output Parquet file.
            slug: Dataset slug (required in relaxed mode if not registered).
            name: Dataset name (required in relaxed mode if not registered).
            publish: Reserved for future use (publishing to data catalog).
            track: If False, write the Parquet directly without lineage tracking
                or dataset registration. Useful for tests and exploratory work.
            license: SPDX license identifier for the output. Persisted to
                datasets.yaml and used for compatibility checking against
                source licenses. Falls back to the dataset's existing license
                or ``package.license`` when omitted.
            check_license: If True (default), raise
                :class:`~sunstone.licenses.LicenseCompatibilityError` when
                the target license is incompatible with any source license
                in the current session lineage.
            **kwargs: Additional arguments passed to pandas.to_parquet.

        Raises:
            StrictModeError: In strict mode, if dataset not registered.
            ValueError: In relaxed mode, if slug/name not provided for new dataset.
            LicenseCompatibilityError: If ``check_license`` is True and the
                target license conflicts with a source license.
        """
        # Filter out any Sunstone-specific kwargs that might have slipped through
        pandas_kwargs = {k: v for k, v in kwargs.items() if k not in self._SUNSTONE_KWARGS}

        if not track:
            from .plugins import PluginRegistry

            registry = PluginRegistry.get(
                Path(self.metadata.lineage.project_path) if self.metadata.lineage.project_path is not None else None
            )
            location = str(path_or_buf)

            url_handler = registry.find_url_handler(location)
            if url_handler:
                with url_handler.open(location, "wb") as stream:
                    self.data.to_parquet(stream, **pandas_kwargs)
            else:
                path = Path(path_or_buf)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.data.to_parquet(path, **pandas_kwargs)
            return

        manager = self._get_datasets_manager()
        location = str(path_or_buf)

        # Try to find existing dataset
        dataset = manager.find_dataset_by_location(location, "output")

        if dataset is None:
            if self.strict_mode:
                raise StrictModeError(
                    f"Output dataset at '{location}' not registered in datasets.yaml. "
                    f"In strict mode, outputs must be pre-registered."
                )
            else:
                # Relaxed mode: auto-register
                effective_slug = slug or self.metadata.slug
                effective_name = name or self.metadata.name
                if effective_slug is None or effective_name is None:
                    raise ValueError(
                        "In relaxed mode, 'slug' and 'name' are required "
                        "when writing to an unregistered output location. "
                        "Set them via to_parquet() parameters or df.metadata.slug/name."
                    )

                # Build field schema merging explicit metadata with inferred dtypes
                fields = self._build_field_schema()

                # Register the new output with full metadata
                dataset = manager.add_output_dataset(
                    name=effective_name,
                    slug=effective_slug,
                    location=location,
                    fields=fields,
                    description=self.metadata.description,
                    rdf_prefixes=self.metadata.rdf_prefixes,
                    custom_properties=self.metadata.custom_properties,
                    license=license,
                )
        elif license is not None and dataset.license != license:
            # Persist explicit override on a pre-registered dataset
            dataset = manager.update_output_dataset(slug=dataset.slug, license=license)

        if check_license:
            target_license = license or manager.effective_license_for(dataset.slug)
            self._enforce_license_compatibility(manager, dataset.slug, target_license)

        # Write the data
        absolute_path = manager.get_absolute_path(dataset.location)

        from .plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)

        url_handler = registry.find_url_handler(location)
        format_writer = registry.find_format_writer(location, None)

        # Wrap data in an Asset envelope so format handlers receive both the
        # payload and the unified Metadata in a single argument (protocol v2).
        # v1/legacy handlers that expect a bare DataFrame won't accept this,
        # but the only built-in writer that supports metadata is the Parquet
        # handler — which is now v2.
        from .asset import Asset as _Asset
        from .asset import AssetKind as _AssetKind

        if format_writer and registry.handler_supports_metadata(format_writer):
            payload_for_write: object = _Asset(payload=self.data, kind=_AssetKind.TABULAR, metadata=self.metadata)
        else:
            payload_for_write = self.data

        if url_handler and format_writer:
            with url_handler.open(location, "wb") as stream:
                format_writer.write(payload_for_write, stream, format=None, path=location, **pandas_kwargs)
        elif format_writer:
            with open(absolute_path, "wb") as stream:
                format_writer.write(payload_for_write, stream, format=None, path=location, **pandas_kwargs)
        else:
            self.data.to_parquet(absolute_path, **pandas_kwargs)

        # Compute data hash for change detection
        data_hash = compute_dataframe_hash(self.data)

        # Flush session lineage with execution context
        from .session import get_session

        session = get_session()
        lineage_data = session.flush_to_output(transformation_params=transformation_params)

        # Resolve effective lineage sources:
        # 1. Explicit sources= parameter takes priority
        # 2. DataFrame's own lineage sources (from read/merge/concat)
        # 3. Fall back to session-accumulated sources (when sources is None)
        effective_lineage = self.metadata.lineage
        if sources is not None:
            effective_lineage.sources = list(sources)
        elif not effective_lineage.sources and lineage_data.get("sources"):
            for src in lineage_data["sources"]:
                src_dataset = manager.find_dataset_by_slug(src["slug"])
                if src_dataset:
                    effective_lineage.add_source(src_dataset)

        # Persist lineage metadata to datasets.yaml
        manager.update_output_lineage(
            slug=dataset.slug,
            lineage=effective_lineage,
            data_hash=data_hash,
            strict=self.strict_mode,
            context=lineage_data.get("context"),
            transformation_params=lineage_data.get("transformation_params"),
            activity=lineage_data.get("_activity"),
        )

    def _infer_dtype(self, col: str) -> str:
        """Infer the dataset type string for a column from its pandas dtype."""
        dtype = self.data[col].dtype
        if pd.api.types.is_integer_dtype(dtype):
            return "integer"
        elif pd.api.types.is_float_dtype(dtype):
            return "number"
        elif pd.api.types.is_bool_dtype(dtype):
            return "boolean"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            return "datetime"
        return "string"

    def _build_field_schema(self) -> List[FieldSchema]:
        """Merge explicit field metadata with dtype-inferred schema."""
        fields = []
        for col in self.data.columns:
            col_str = str(col)
            explicit = self.metadata.field_metadata.get(col_str)
            if explicit:
                if explicit.type is None:
                    fields.append(
                        FieldSchema(
                            name=explicit.name,
                            type=self._infer_dtype(col_str),
                            description=explicit.description,
                            unit=explicit.unit,
                            source=explicit.source,
                            constraints=explicit.constraints,
                        )
                    )
                else:
                    fields.append(explicit)
            else:
                fields.append(FieldSchema(name=col_str, type=self._infer_dtype(col_str)))
        return fields

    def merge(self, right: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Merge with another Sunstone DataFrame, combining lineage.

        Validates unit compatibility on overlapping value columns (not join keys)
        and brings in right-side field metadata for columns not already in left.
        """
        from .units import resolve_units, try_parse_unit

        merged_data = pd.merge(self.data, right.data, **kwargs)
        merged_lineage = self.metadata.lineage.merge(right.metadata.lineage)

        # Determine join keys to exclude from unit validation
        on = kwargs.get("on")
        left_on = kwargs.get("left_on")
        right_on = kwargs.get("right_on")
        join_keys: set[str] = set()
        if on is not None:
            join_keys = {on} if isinstance(on, str) else set(on)
        if left_on is not None:
            join_keys |= {left_on} if isinstance(left_on, str) else set(left_on)
        if right_on is not None:
            join_keys |= {right_on} if isinstance(right_on, str) else set(right_on)

        # Validate units on overlapping value columns
        left_cols = set(self.data.columns) - join_keys
        right_cols = set(right.data.columns) - join_keys
        overlap = left_cols & right_cols
        for col in overlap:
            left_field = self.metadata.field_metadata.get(col)
            right_field = right.metadata.field_metadata.get(col)
            if left_field and left_field.unit and right_field and right_field.unit:
                left_unit = try_parse_unit(left_field.unit)
                right_unit = try_parse_unit(right_field.unit)
                if left_unit is None or right_unit is None:
                    continue
                resolved = resolve_units(left_unit, right_unit, "add")
                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

        # Build field metadata: left first, then right for columns not in left
        new_field_meta = {k: replace(v) for k, v in self.metadata.field_metadata.items() if k in merged_data.columns}
        for k, v in right.metadata.field_metadata.items():
            if k in merged_data.columns and k not in new_field_meta:
                new_field_meta[k] = replace(v)

        new_metadata = Metadata(
            lineage=merged_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=merged_data, metadata=new_metadata, strict=self.strict_mode)

    def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """Join with another Sunstone DataFrame, combining lineage.

        Validates unit compatibility on overlapping columns and brings in
        right-side field metadata for columns not already in left.
        """
        from .units import resolve_units, try_parse_unit

        joined_data = self.data.join(other.data, **kwargs)
        joined_lineage = self.metadata.lineage.merge(other.metadata.lineage)

        # Validate units on overlapping columns
        overlap = set(self.data.columns) & set(other.data.columns)
        for col in overlap:
            left_field = self.metadata.field_metadata.get(col)
            right_field = other.metadata.field_metadata.get(col)
            if left_field and left_field.unit and right_field and right_field.unit:
                left_unit = try_parse_unit(left_field.unit)
                right_unit = try_parse_unit(right_field.unit)
                if left_unit is None or right_unit is None:
                    continue
                resolved = resolve_units(left_unit, right_unit, "add")
                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

        # Build field metadata: left first, then right for columns not in left
        new_field_meta = {k: replace(v) for k, v in self.metadata.field_metadata.items() if k in joined_data.columns}
        for k, v in other.metadata.field_metadata.items():
            if k in joined_data.columns and k not in new_field_meta:
                new_field_meta[k] = replace(v)

        new_metadata = Metadata(
            lineage=joined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=joined_data, metadata=new_metadata, strict=self.strict_mode)

    def concat(self, others: List["DataFrame"], **kwargs: Any) -> "DataFrame":
        """Concatenate with other Sunstone DataFrames, combining lineage.

        Before delegating to pandas, iterates shared columns. For each column
        with units in multiple DataFrames, calls resolve_units to check
        compatibility and apply conversions in auto mode.
        """
        from .units import resolve_units, try_parse_unit

        all_frames = [self] + others

        # Collect all column names across frames
        all_columns: set[str] = set()
        for frame in all_frames:
            all_columns |= set(frame.data.columns)

        # Track resolved units and conversion factors per frame per column
        # We work on copies of the data to avoid mutating originals
        data_copies = [frame.data.copy() for frame in all_frames]
        resolved_units_map: dict[str, str] = {}  # col -> winning unit string

        for col in all_columns:
            # Find the first frame with a parseable unit for this column
            ref_unit = None
            ref_unit_str: str | None = None
            ref_idx = None
            for i, frame in enumerate(all_frames):
                if col in frame.data.columns:
                    field = frame.metadata.field_metadata.get(col)
                    if field and field.unit:
                        parsed = try_parse_unit(field.unit)
                        if parsed is not None:
                            ref_unit = parsed
                            ref_unit_str = field.unit
                            ref_idx = i
                            break

            if ref_unit is None:
                continue

            # Resolve against all subsequent frames with units for this column
            winner_unit = ref_unit
            winner_unit_str = ref_unit_str
            conversion_happened = False
            for i, frame in enumerate(all_frames):
                if i == ref_idx or col not in frame.data.columns:
                    continue
                field = frame.metadata.field_metadata.get(col)
                if not (field and field.unit):
                    continue

                other_unit = try_parse_unit(field.unit)
                if other_unit is None:
                    continue
                resolved = resolve_units(winner_unit, other_unit, "concat")

                if resolved.warning:
                    warnings.warn(resolved.warning, stacklevel=2)

                # Apply conversions if auto mode produced them
                if resolved.convert_a is not None:
                    conversion_happened = True
                    # Convert all previous frames that used winner_unit
                    for j in range(i):
                        if col in data_copies[j].columns:
                            f = all_frames[j].metadata.field_metadata.get(col)
                            if f and f.unit:
                                data_copies[j][col] = data_copies[j][col] * resolved.convert_a

                if resolved.convert_b is not None:
                    conversion_happened = True
                    data_copies[i][col] = data_copies[i][col] * resolved.convert_b

                if resolved.result_unit is not None:
                    if resolved.result_unit != winner_unit:
                        conversion_happened = True
                        winner_unit_str = field.unit
                    winner_unit = resolved.result_unit

            # Use original string if no conversion happened, otherwise pint's canonical form
            if conversion_happened:
                resolved_units_map[col] = str(winner_unit)
            else:
                assert winner_unit_str is not None
                resolved_units_map[col] = winner_unit_str

        concatenated_data = pd.concat(data_copies, **kwargs)

        combined_lineage = self.metadata.lineage
        for other in others:
            combined_lineage = combined_lineage.merge(other.metadata.lineage)

        # Build field metadata, updating units to resolved values
        new_field_meta = {
            k: replace(v) for k, v in self.metadata.field_metadata.items() if k in concatenated_data.columns
        }
        for col, unit_str in resolved_units_map.items():
            if col in new_field_meta:
                new_field_meta[col].unit = unit_str
                new_field_meta[col].unit_source = None  # clear stale QUDT URI
            elif col in concatenated_data.columns:
                new_field_meta[col] = FieldSchema(name=col, unit=unit_str)

        new_metadata = Metadata(
            lineage=combined_lineage,
            description=self.metadata.description,
            rdf_prefixes=self.metadata.rdf_prefixes,
            custom_properties=self.metadata.custom_properties,
            field_metadata=new_field_meta,
            slug=self.metadata.slug,
            name=self.metadata.name,
        )
        return DataFrame(data=concatenated_data, metadata=new_metadata, strict=self.strict_mode)

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
                from .units import UnitSeries, try_parse_unit

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
        from .units import UnitSeries

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
    from .asset import Asset
    from .plugins import PluginRegistry

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
