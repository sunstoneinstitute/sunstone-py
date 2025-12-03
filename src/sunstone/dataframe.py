"""
DataFrame wrapper with lineage tracking for Sunstone projects.
"""

import os
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import pandas as pd

from .datasets import DatasetsManager
from .exceptions import DatasetNotFoundError, StrictModeError
from .lineage import FieldSchema, LineageMetadata

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
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ):
        """
        Initialize a Sunstone DataFrame.

        Args:
            data: Data to wrap. Can be a pandas DataFrame or any data accepted
                 by pandas.DataFrame() constructor (dict, list of dicts, etc.).
            lineage: Optional lineage metadata.
            strict: Whether to operate in strict mode. If None, reads from
                   SUNSTONE_DATAFRAME_STRICT environment variable.
            project_path: Path to the project directory. If None, uses current directory.
            **kwargs: Additional arguments passed to pandas.DataFrame constructor.

        Note:
            Strict mode behavior:
            - strict=True: Operations that would modify datasets.yaml will fail
            - strict=False (relaxed): datasets.yaml will be updated as needed
            - Default is determined by SUNSTONE_DATAFRAME_STRICT env var
              ("1" or "true" -> strict mode, otherwise relaxed mode)
        """
        # Convert data to pandas DataFrame if it isn't already
        if data is None:
            self.data = pd.DataFrame(**kwargs)
        elif isinstance(data, pd.DataFrame):
            self.data = data
        else:
            # data is some other type (dict, list, etc.) - pass to pandas
            self.data = pd.DataFrame(data, **kwargs)

        self.lineage = lineage if lineage is not None else LineageMetadata()

        # Determine strict mode
        if strict is None:
            env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
            self.strict_mode = env_strict in ("1", "true")
        else:
            self.strict_mode = strict

        # Set project path
        if project_path is not None:
            self.lineage.project_path = str(Path(project_path).resolve())
        elif self.lineage.project_path is None:
            self.lineage.project_path = str(Path.cwd())

    def _get_datasets_manager(self) -> DatasetsManager:
        """Get a DatasetsManager for the current project."""
        if self.lineage.project_path is None:
            raise ValueError("Project path not set")
        return DatasetsManager(self.lineage.project_path)

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
            project_path = Path.cwd()

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

        # Determine format
        if format is None:
            # Auto-detect from file extension
            extension = absolute_path.suffix.lower()
            format_map = {
                ".csv": "csv",
                ".json": "json",
                ".xlsx": "excel",
                ".xls": "excel",
                ".parquet": "parquet",
                ".tsv": "tsv",
                ".txt": "tsv",  # Assume tab-delimited for .txt
            }
            format = format_map.get(extension)
            if format is None:
                raise ValueError(
                    f"Cannot auto-detect format for file extension '{extension}'. "
                    f"Supported extensions: {', '.join(format_map.keys())}. "
                    f"Please specify format explicitly using the 'format' parameter."
                )

        # Read using appropriate pandas function
        reader_map: dict[str, Callable[..., pd.DataFrame]] = {
            "csv": pd.read_csv,
            "json": pd.read_json,
            "excel": pd.read_excel,
            "parquet": pd.read_parquet,
            "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
        }

        reader = reader_map.get(format)
        if reader is None:
            raise ValueError(f"Unsupported format '{format}'. Supported formats: {', '.join(reader_map.keys())}")

        df = reader(absolute_path, **kwargs)

        # Create lineage metadata
        lineage = LineageMetadata(project_path=str(manager.project_path))
        lineage.add_source(dataset)
        lineage.add_operation(f"read_dataset({dataset.slug}, format={format})")

        # Return wrapped DataFrame
        return cls(data=df, lineage=lineage, strict=strict, project_path=project_path)

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
            project_path = Path.cwd()

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

        # Read the CSV using pandas
        df = pd.read_csv(absolute_path, **kwargs)

        # Create lineage metadata
        lineage = LineageMetadata(project_path=str(manager.project_path))
        lineage.add_source(dataset)
        lineage.add_operation(f"read_csv({dataset.slug})")

        # Return wrapped DataFrame
        return cls(data=df, lineage=lineage, strict=strict, project_path=project_path)

    @staticmethod
    def _get_default_strict_mode() -> bool:
        """Get the default strict mode from environment variable."""
        env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
        return env_strict in ("1", "true")

    def to_csv(
        self,
        path_or_buf: Union[str, Path],
        slug: Optional[str] = None,
        name: Optional[str] = None,
        publish: bool = False,
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
            publish: bool = False,
            **kwargs: Additional arguments passed to pandas.to_csv.

        Raises:
            StrictModeError: In strict mode, if dataset not registered.
            ValueError: In relaxed mode, if slug/name not provided for new dataset.
        """
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
                if slug is None or name is None:
                    raise ValueError(
                        "In relaxed mode, 'slug' and 'name' are required "
                        "when writing to an unregistered output location."
                    )

                # Infer field schema from DataFrame
                fields = self._infer_field_schema()

                # Register the new output
                dataset = manager.add_output_dataset(
                    name=name, slug=slug, location=location, fields=fields, publish=publish
                )

        # Write the CSV
        absolute_path = manager.get_absolute_path(dataset.location)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        self.data.to_csv(absolute_path, **kwargs)

        # Record the operation
        self.lineage.add_operation(f"to_csv({dataset.slug})")

        # Persist lineage metadata to datasets.yaml
        manager.update_output_lineage(slug=dataset.slug, lineage=self.lineage, strict=self.strict_mode)

    def _infer_field_schema(self) -> List[FieldSchema]:
        """
        Infer field schema from the DataFrame.

        Returns:
            List of FieldSchema objects based on DataFrame columns and dtypes.
        """
        fields = []
        for col in self.data.columns:
            dtype = self.data[col].dtype

            # Map pandas dtypes to dataset types
            if pd.api.types.is_integer_dtype(dtype):
                field_type = "integer"
            elif pd.api.types.is_float_dtype(dtype):
                field_type = "number"
            elif pd.api.types.is_bool_dtype(dtype):
                field_type = "boolean"
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                field_type = "datetime"
            else:
                field_type = "string"

            fields.append(FieldSchema(name=str(col), type=field_type))

        return fields

    def merge(self, right: "DataFrame", **kwargs: Any) -> "DataFrame":
        """
        Merge with another Sunstone DataFrame, combining lineage.

        Args:
            right: The other DataFrame to merge with.
            **kwargs: Arguments passed to pandas.merge.

        Returns:
            A new DataFrame with combined data and lineage.
        """
        # Perform the merge
        merged_data = pd.merge(self.data, right.data, **kwargs)

        # Combine lineage
        merged_lineage = self.lineage.merge(right.lineage)
        merged_lineage.add_operation(
            f"merge(left={len(self.lineage.sources)} sources, right={len(right.lineage.sources)} sources)"
        )

        return DataFrame(
            data=merged_data,
            lineage=merged_lineage,
            strict=self.strict_mode,
            project_path=self.lineage.project_path,
        )

    def join(self, other: "DataFrame", **kwargs: Any) -> "DataFrame":
        """
        Join with another Sunstone DataFrame, combining lineage.

        Args:
            other: The other DataFrame to join with.
            **kwargs: Arguments passed to pandas.join.

        Returns:
            A new DataFrame with combined data and lineage.
        """
        # Perform the join
        joined_data = self.data.join(other.data, **kwargs)

        # Combine lineage
        joined_lineage = self.lineage.merge(other.lineage)
        joined_lineage.add_operation(
            f"join(left={len(self.lineage.sources)} sources, right={len(other.lineage.sources)} sources)"
        )

        return DataFrame(
            data=joined_data,
            lineage=joined_lineage,
            strict=self.strict_mode,
            project_path=self.lineage.project_path,
        )

    def concat(self, others: List["DataFrame"], **kwargs: Any) -> "DataFrame":
        """
        Concatenate with other Sunstone DataFrames, combining lineage.

        Args:
            others: List of other DataFrames to concatenate.
            **kwargs: Arguments passed to pandas.concat.

        Returns:
            A new DataFrame with combined data and lineage.
        """
        # Collect all DataFrames
        all_dfs = [self.data] + [df.data for df in others]

        # Concatenate
        concatenated_data = pd.concat(all_dfs, **kwargs)

        # Combine lineage from all DataFrames
        combined_lineage = self.lineage
        for other in others:
            combined_lineage = combined_lineage.merge(other.lineage)

        combined_lineage.add_operation(
            f"concat({len(others) + 1} dataframes, "
            f"{sum(len(df.lineage.sources) for df in [self] + others)} total sources)"
        )

        return DataFrame(
            data=concatenated_data,
            lineage=combined_lineage,
            strict=self.strict_mode,
            project_path=self.lineage.project_path,
        )

    def apply_operation(self, operation: Callable[[pd.DataFrame], pd.DataFrame], description: str) -> "DataFrame":
        """
        Apply a transformation operation to the DataFrame.

        Args:
            operation: Function that takes a pandas DataFrame and returns a DataFrame.
            description: Human-readable description of the operation.

        Returns:
            A new DataFrame with the operation applied and recorded in lineage.
        """
        # Apply the operation
        new_data = operation(self.data)

        # Copy lineage and add operation
        new_lineage = LineageMetadata(
            sources=self.lineage.sources.copy(),
            operations=self.lineage.operations.copy(),
            project_path=self.lineage.project_path,
        )
        new_lineage.add_operation(description)

        return DataFrame(
            data=new_data,
            lineage=new_lineage,
            strict=self.strict_mode,
            project_path=self.lineage.project_path,
        )

    def _wrap_result(self, result: Any, operation: Optional[str] = None) -> Any:
        """
        Wrap a pandas result in a Sunstone DataFrame if applicable.

        Args:
            result: The result from a pandas operation.
            operation: Name of the operation performed. If None, no operation is recorded.

        Returns:
            Wrapped DataFrame if result is a DataFrame, otherwise the result.
        """
        if isinstance(result, pd.DataFrame):
            new_lineage = LineageMetadata(
                sources=self.lineage.sources.copy(),
                operations=self.lineage.operations.copy(),
                project_path=self.lineage.project_path,
            )
            if operation is not None:
                new_lineage.add_operation(operation)

            return DataFrame(
                data=result,
                lineage=new_lineage,
                strict=self.strict_mode,
                project_path=self.lineage.project_path,
            )
        return result

    # Methods that don't represent meaningful data transformations
    # These return DataFrames but shouldn't be tracked in lineage
    _NON_TRACKING_METHODS = frozenset({
        # Copy operations - same data, no transformation
        "copy",
        # Index operations - same data, different index
        "reset_index",
        "set_index",
        "reindex",
        # Type conversions without data change
        "astype",
        "infer_objects",
        # Column/index renaming - same data, different labels
        "rename",
        "rename_axis",
        # Reshaping without data loss
        "T",
        "transpose",
    })

    def __getattr__(self, name: str) -> Any:
        """
        Delegate attribute access to the underlying pandas DataFrame.

        Args:
            name: Attribute name.

        Returns:
            The attribute from the underlying DataFrame, wrapped if it's a method or DataFrame.
        """
        # Special handling for pandas indexers - return as-is
        if name in ("loc", "iloc", "at", "iat"):
            return getattr(self.data, name)

        attr = getattr(self.data, name)

        if callable(attr):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                result = attr(*args, **kwargs)
                # Don't track non-transforming methods
                if name in DataFrame._NON_TRACKING_METHODS:
                    return self._wrap_result(result, operation=None)
                return self._wrap_result(result, operation=f"{name}")

            return wrapper

        return self._wrap_result(attr, operation=None)  # Don't track attribute access

    def __getitem__(self, key: Any) -> Any:
        """
        Delegate item access to the underlying pandas DataFrame.

        Args:
            key: Index key.

        Returns:
            The item from the underlying DataFrame, wrapped if it's a DataFrame.
        """
        result = self.data[key]
        # Don't track __getitem__ as an operation - it's just column/row access
        # not a meaningful transformation
        return self._wrap_result(result, operation=None)

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Delegate item assignment to the underlying pandas DataFrame.

        Args:
            key: Index key.
            value: Value to assign.
        """
        self.data[key] = value
        # Track column assignment in lineage
        self.lineage.add_operation(f"__setitem__({key!r})")

    def __repr__(self) -> str:
        """String representation of the DataFrame."""
        lineage_info = (
            f"\n\nLineage: {len(self.lineage.sources)} source(s), {len(self.lineage.operations)} operation(s)"
        )
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
