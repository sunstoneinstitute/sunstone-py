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
        data: Optional[pd.DataFrame] = None,
        lineage: Optional[LineageMetadata] = None,
        strict: Optional[bool] = None,
        project_path: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize a Sunstone DataFrame.

        Args:
            data: Optional pandas DataFrame to wrap.
            lineage: Optional lineage metadata.
            strict: Whether to operate in strict mode. If None, reads from
                   SUNSTONE_DATAFRAME_STRICT environment variable.
            project_path: Path to the project directory. If None, uses current directory.

        Note:
            Strict mode behavior:
            - strict=True: Operations that would modify datasets.yaml will fail
            - strict=False (relaxed): datasets.yaml will be updated as needed
            - Default is determined by SUNSTONE_DATAFRAME_STRICT env var
              ("1" or "true" -> strict mode, otherwise relaxed mode)
        """
        self.data = data if data is not None else pd.DataFrame()
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
    def read_csv(
        cls,
        filepath_or_buffer: Union[str, Path],
        project_path: Optional[Union[str, Path]] = None,
        strict: Optional[bool] = None,
        **kwargs: Any,
    ) -> "DataFrame":
        """
        Read a CSV file into a Sunstone DataFrame.

        The file must be registered in datasets.yaml, otherwise this will fail
        (or in relaxed mode, register it automatically).

        Args:
            filepath_or_buffer: Path to CSV file or URL.
            project_path: Path to project directory containing datasets.yaml.
            strict: Whether to operate in strict mode.
            **kwargs: Additional arguments passed to pandas.read_csv.

        Returns:
            A new Sunstone DataFrame with lineage metadata.

        Raises:
            DatasetNotFoundError: In strict mode, if dataset not found in datasets.yaml.
            FileNotFoundError: If datasets.yaml doesn't exist.
        """
        if project_path is None:
            project_path = Path.cwd()

        manager = DatasetsManager(project_path)
        location = str(filepath_or_buffer)

        # Try to find the dataset
        dataset = manager.find_dataset_by_location(location)

        if dataset is None:
            if strict or (strict is None and cls._get_default_strict_mode()):
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. "
                    f"In strict mode, all datasets must be registered."
                )
            else:
                # Relaxed mode: we could auto-register here, but that's complex
                # For now, just fail with a helpful message
                raise DatasetNotFoundError(
                    f"Dataset at '{location}' not found in datasets.yaml. "
                    f"Please add it to datasets.yaml first."
                )

        # Read the CSV using pandas
        # Use the actual requested location, not the one from datasets.yaml
        # (they might differ if files were moved to subdirectories)
        absolute_path = manager.get_absolute_path(location)
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
            publish: Whether to publish the dataset.
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
            f"merge(left={len(self.lineage.sources)} sources, "
            f"right={len(right.lineage.sources)} sources)"
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
            f"join(left={len(self.lineage.sources)} sources, "
            f"right={len(other.lineage.sources)} sources)"
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

    def apply_operation(
        self, operation: Callable[[pd.DataFrame], pd.DataFrame], description: str
    ) -> "DataFrame":
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

    def _wrap_result(self, result: Any, operation: str = "pandas_operation") -> Any:
        """
        Wrap a pandas result in a Sunstone DataFrame if applicable.

        Args:
            result: The result from a pandas operation.
            operation: Name of the operation performed.

        Returns:
            Wrapped DataFrame if result is a DataFrame, otherwise the result.
        """
        if isinstance(result, pd.DataFrame):
            new_lineage = LineageMetadata(
                sources=self.lineage.sources.copy(),
                operations=self.lineage.operations.copy(),
                project_path=self.lineage.project_path,
            )
            new_lineage.add_operation(operation)

            return DataFrame(
                data=result,
                lineage=new_lineage,
                strict=self.strict_mode,
                project_path=self.lineage.project_path,
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
        attr = getattr(self.data, name)

        if callable(attr):

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                result = attr(*args, **kwargs)
                return self._wrap_result(result, operation=f"{name}")

            return wrapper

        return self._wrap_result(attr, operation=f"access_attribute_{name}")

    def __getitem__(self, key: Any) -> Any:
        """
        Delegate item access to the underlying pandas DataFrame.

        Args:
            key: Index key.

        Returns:
            The item from the underlying DataFrame, wrapped if it's a DataFrame.
        """
        result = self.data[key]
        return self._wrap_result(result, operation="__getitem__")

    def __setitem__(self, key: Any, value: Any) -> None:
        """
        Delegate item assignment to the underlying pandas DataFrame.

        Args:
            key: Index key.
            value: Value to assign.
        """
        self.data[key] = value
        self.lineage.add_operation("__setitem__")

    def __repr__(self) -> str:
        """String representation of the DataFrame."""
        lineage_info = (
            f"\n\nLineage: {len(self.lineage.sources)} source(s), "
            f"{len(self.lineage.operations)} operation(s)"
        )
        return repr(self.data) + lineage_info

    def __str__(self) -> str:
        """String representation of the DataFrame."""
        return str(self.data)
