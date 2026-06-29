"""
WriteMixin — write-side instance methods for the Sunstone DataFrame.

This mixin is consumed by `sunstone.pandas.core.DataFrame` via multiple
inheritance. The methods are called as `df.to_csv(...)` / `df.to_parquet(...)`,
so `self` resolves to a Sunstone DataFrame through the MRO.

Note: pandas is imported eagerly here. By the time this module is
imported, the caller has already opted into the pandas facade (either
via `from sunstone import pandas as pd` or by importing the DataFrame
class directly), so we no longer need to preserve the top-level
`import sunstone` lazy-load property at this layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

import pandas as pd

from sunstone.datasets import DatasetsManager
from sunstone.exceptions import StrictModeError
from sunstone.lineage import DatasetMetadata, FieldSchema, Metadata, compute_dataframe_hash

if TYPE_CHECKING:
    from sunstone.pandas.core import DataFrame  # noqa: F401  (type hint only)


class WriteMixin:
    """Write-side instance methods for the Sunstone DataFrame.

    This mixin assumes the concrete subclass (DataFrame) provides:
    - ``data`` (pandas DataFrame payload),
    - ``metadata`` (unified :class:`~sunstone.lineage.Metadata` container),
    - ``strict_mode`` (bool),
    - ``_SUNSTONE_KWARGS`` (class attribute, set of reserved kwarg names),
    - ``_get_datasets_manager()`` returning a :class:`DatasetsManager`.

    Those expectations are encoded as ``TYPE_CHECKING`` stubs below so
    mypy can verify usage inside the mixin without runtime overhead.
    """

    if TYPE_CHECKING:
        # Attributes/methods the concrete subclass provides. ``data`` and
        # ``metadata`` are ``@property`` on the concrete subclass, so we
        # declare them as properties here too — bare attribute stubs would
        # trigger pyright's "overrides symbol of same name" diagnostic.
        strict_mode: bool
        _SUNSTONE_KWARGS: set[str]

        @property
        def data(self) -> pd.DataFrame: ...

        @property
        def metadata(self) -> Metadata: ...

        def _get_datasets_manager(self) -> DatasetsManager: ...

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
        from sunstone.licenses import (
            LicenseCompatibilityError,
            check_compatibility,
            derive_compatible_target,
        )
        from sunstone.session import get_session

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
            from sunstone.plugins import PluginRegistry

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

        from sunstone.plugins import PluginRegistry

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
        from sunstone.session import get_session

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
            from sunstone.plugins import PluginRegistry

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

        from sunstone.plugins import PluginRegistry

        registry = PluginRegistry.get(manager.project_path)
        location = str(absolute_path)

        url_handler = registry.find_url_handler(location)
        format_writer = registry.find_format_writer(location, None)

        # Wrap data in an Asset envelope so format handlers receive both the
        # payload and the unified Metadata in a single argument (protocol v2).
        # v1/legacy handlers that expect a bare DataFrame won't accept this,
        # but the only built-in writer that supports metadata is the Parquet
        # handler — which is now v2.
        from sunstone.asset import Asset as _Asset
        from sunstone.asset import AssetKind as _AssetKind

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
        from sunstone.session import get_session

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
