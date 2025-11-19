"""
Pandas-compatible API for Sunstone DataFrames.

This module provides a pandas-like interface that data scientists can use
with minimal friction, while still maintaining full lineage tracking.

Example:
    >>> from sunstone import pandas as pd
    >>>
    >>> # Read data (must be in datasets.yaml)
    >>> df = pd.read_csv('input_data.csv', project_path='/path/to/project')
    >>>
    >>> # Use familiar pandas operations
    >>> filtered = df[df['amount'] > 100]
    >>> grouped = df.groupby('category').sum()
    >>>
    >>> # Merge datasets
    >>> result = pd.merge(df1, df2, on='id')
    >>>
    >>> # Save with lineage
    >>> result.to_csv('output.csv', slug='output-data', name='Output Data')
"""

from pathlib import Path
from typing import Any, List, Optional, Union

from .dataframe import DataFrame

__all__ = [
    "read_csv",
    "merge",
    "concat",
]


def read_csv(
    filepath_or_buffer: Union[str, Path],
    project_path: Union[str, Path],
    strict: Optional[bool] = None,
    **kwargs: Any,
) -> DataFrame:
    """
    Read a CSV file into a Sunstone DataFrame with lineage tracking.

    This function provides a pandas-like interface while ensuring the dataset
    is registered in datasets.yaml and lineage is tracked.

    Args:
        filepath_or_buffer: Path to CSV file (relative to project) or URL.
        project_path: Path to project directory containing datasets.yaml.
                     Must be provided explicitly (no auto-detection).
        strict: Whether to operate in strict mode. If None, reads from
               SUNSTONE_DATAFRAME_STRICT environment variable.
        **kwargs: Additional arguments passed to pandas.read_csv.

    Returns:
        A Sunstone DataFrame with lineage metadata.

    Raises:
        DatasetNotFoundError: If dataset not found in datasets.yaml.
        FileNotFoundError: If datasets.yaml doesn't exist.

    Example:
        >>> from sunstone import pandas as pd
        >>> df = pd.read_csv('schools.csv', project_path='/path/to/project')
        >>> df = pd.read_csv('schools.csv', project_path='/path/to/project',
        ...                  encoding='utf-8', skiprows=1)
    """
    return DataFrame.read_csv(
        filepath_or_buffer=filepath_or_buffer,
        project_path=project_path,
        strict=strict,
        **kwargs,
    )


def merge(
    left: DataFrame,
    right: DataFrame,
    **kwargs: Any,
) -> DataFrame:
    """
    Merge two Sunstone DataFrames, combining their lineage.

    This function provides the same interface as pandas.merge but maintains
    lineage tracking from both input DataFrames.

    Args:
        left: Left DataFrame to merge.
        right: Right DataFrame to merge.
        **kwargs: Additional arguments passed to pandas.merge (on, how, left_on,
                 right_on, left_index, right_index, etc.).

    Returns:
        A new DataFrame with merged data and combined lineage.

    Example:
        >>> from sunstone import pandas as pd
        >>> df1 = pd.read_csv('countries.csv', project_path='/path/to/project')
        >>> df2 = pd.read_csv('populations.csv', project_path='/path/to/project')
        >>> merged = pd.merge(df1, df2, on='country_code', how='inner')
    """
    return left.merge(right, **kwargs)


def concat(
    objs: List[DataFrame],
    **kwargs: Any,
) -> DataFrame:
    """
    Concatenate Sunstone DataFrames along a particular axis, combining lineage.

    This function provides the same interface as pandas.concat but maintains
    lineage tracking from all input DataFrames.

    Args:
        objs: List of DataFrame objects to concatenate.
        **kwargs: Additional arguments passed to pandas.concat (axis, join,
                 ignore_index, keys, etc.).

    Returns:
        A new DataFrame with concatenated data and combined lineage.

    Example:
        >>> from sunstone import pandas as pd
        >>> df1 = pd.read_csv('data_2023.csv', project_path='/path/to/project')
        >>> df2 = pd.read_csv('data_2024.csv', project_path='/path/to/project')
        >>> combined = pd.concat([df1, df2], ignore_index=True)
    """
    if not objs:
        raise ValueError("No objects to concatenate")

    # Use the first DataFrame's concat method
    first = objs[0]
    rest = objs[1:]
    return first.concat(rest, **kwargs)
