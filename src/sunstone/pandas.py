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

import pandas as _pd

from .dataframe import DataFrame

# Re-export commonly used pandas types and functions
# This allows scripts to use `from sunstone import pandas as pd` and still
# access standard pandas utilities like pd.Timestamp, pd.NaT, etc.
#
# NOTE: DataFrame is our wrapped version from .dataframe
# For vanilla pandas DataFrame, use _pd.DataFrame directly if needed
Timestamp = _pd.Timestamp
NaT = _pd.NaT
isna = _pd.isna
isnull = _pd.isnull
notna = _pd.notna
notnull = _pd.notnull
to_datetime = _pd.to_datetime
to_numeric = _pd.to_numeric
to_timedelta = _pd.to_timedelta
Series = _pd.Series  # Re-export pandas Series

__all__ = [
    "read_csv",
    "read_dataset",
    "merge",
    "concat",
    # Pandas types and utilities
    "DataFrame",
    "Series",
    "Timestamp",
    "NaT",
    "isna",
    "isnull",
    "notna",
    "notnull",
    "to_datetime",
    "to_numeric",
    "to_timedelta",
]


def read_dataset(
    slug: str,
    project_path: Union[str, Path],
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    format: Optional[str] = None,
    **kwargs: Any,
) -> DataFrame:
    """
    Read a dataset by slug from datasets.yaml with automatic format detection.

    This function provides a pandas-like interface while ensuring the dataset
    is registered in datasets.yaml and lineage is tracked. The file format is
    automatically detected from the file extension unless explicitly specified.

    Supported formats:
    - CSV (.csv)
    - JSON (.json)
    - Excel (.xlsx, .xls)
    - Parquet (.parquet)
    - TSV (.tsv, .txt with tab delimiter)

    Args:
        slug: Dataset slug to look up in datasets.yaml.
        project_path: Path to project directory containing datasets.yaml.
                     Must be provided explicitly (no auto-detection).
        strict: Whether to operate in strict mode. If None, reads from
               SUNSTONE_DATAFRAME_STRICT environment variable.
        fetch_from_url: If True and dataset has a source URL but no local file,
                      automatically fetch from URL.
        format: Optional format override ('csv', 'json', 'excel', 'parquet', 'tsv').
               If not provided, format is auto-detected from file extension.
        **kwargs: Additional arguments passed to the pandas reader function.

    Returns:
        A Sunstone DataFrame with lineage metadata.

    Raises:
        DatasetNotFoundError: If dataset with slug not found in datasets.yaml.
        FileNotFoundError: If datasets.yaml doesn't exist.
        ValueError: If format cannot be detected or is unsupported.

    Examples:
        >>> from sunstone import pandas as pd
        >>>
        >>> # Auto-detect format from extension
        >>> df = pd.read_dataset('official-un-member-states', project_path='/path/to/project')
        >>>
        >>> # Explicitly specify format
        >>> df = pd.read_dataset('my-data', format='json', project_path='/path/to/project')
        >>>
        >>> # With additional reader arguments
        >>> df = pd.read_dataset('data-file', project_path='/path/to/project',
        ...                      encoding='utf-8', skiprows=1)
    """
    return DataFrame.read_dataset(
        slug=slug,
        project_path=project_path,
        strict=strict,
        fetch_from_url=fetch_from_url,
        format=format,
        **kwargs,
    )


def read_csv(
    filepath_or_buffer: Union[str, Path],
    project_path: Union[str, Path],
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    **kwargs: Any,
) -> DataFrame:
    """
    Read a CSV file into a Sunstone DataFrame with lineage tracking.

    This function provides a pandas-like interface while ensuring the dataset
    is registered in datasets.yaml and lineage is tracked.

    Args:
        filepath_or_buffer: Path to CSV file, URL, or dataset slug.
                          If it's a slug (e.g., 'official-un-member-states'),
                          the dataset will be looked up in datasets.yaml.
        project_path: Path to project directory containing datasets.yaml.
                     Must be provided explicitly (no auto-detection).
        strict: Whether to operate in strict mode. If None, reads from
               SUNSTONE_DATAFRAME_STRICT environment variable.
        fetch_from_url: If True and dataset has a source URL but no local file,
                      automatically fetch from URL.
        **kwargs: Additional arguments passed to pandas.read_csv.

    Returns:
        A Sunstone DataFrame with lineage metadata.

    Raises:
        DatasetNotFoundError: If dataset not found in datasets.yaml.
        FileNotFoundError: If datasets.yaml doesn't exist.

    Examples:
        >>> from sunstone import pandas as pd
        >>>
        >>> # Load by slug (recommended)
        >>> df = pd.read_csv('official-un-member-states', project_path='/path/to/project')
        >>>
        >>> # Load by file path
        >>> df = pd.read_csv('schools.csv', project_path='/path/to/project')
        >>>
        >>> # With additional pandas arguments
        >>> df = pd.read_csv('schools.csv', project_path='/path/to/project',
        ...                  encoding='utf-8', skiprows=1)
    """
    return DataFrame.read_csv(
        filepath_or_buffer=filepath_or_buffer,
        project_path=project_path,
        strict=strict,
        fetch_from_url=fetch_from_url,
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
