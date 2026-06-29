"""Polars read facades.

Reads route bytes through the plugin URL handler (for a file-content hash)
and parse via the engine-aware BuiltinFormatHandler with ``engine="polars"``.
"""

from __future__ import annotations

import hashlib
import io as _io
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union, cast

from sunstone.config import get_project_path
from sunstone.datasets import DatasetsManager
from sunstone.exceptions import DatasetNotFoundError
from sunstone.lineage import LineageMetadata, Metadata

if TYPE_CHECKING:
    from .core import DataFrame

_PathLike = Union[str, Path]


def read_dataset(
    slug: str,
    project_path: Optional[_PathLike] = None,
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    format: Optional[str] = None,
    **kwargs: Any,
) -> "DataFrame":
    """Read a dataset by slug from ``datasets.yaml`` with polars as the engine.

    Args:
        slug: Dataset slug to look up in ``datasets.yaml``.
        project_path: Project directory containing ``datasets.yaml``.
        strict: Strict-mode override (currently unused; all unregistered datasets raise).
        fetch_from_url: Fetch from the dataset's source URL if the local file is missing.
        format: Format override (auto-detected from extension when omitted).
        **kwargs: Forwarded to the format handler.

    Returns:
        A polars ``DataFrame`` facade with construction-time lineage.

    Raises:
        DatasetNotFoundError: ``slug`` not present in ``datasets.yaml``.
        FileNotFoundError: File missing and no source URL available.
        ValueError: No handler for the resolved format / extension.
    """
    from sunstone.asset import Asset
    from sunstone.plugins import PluginRegistry, no_url_handler_error
    from sunstone.session import DatasetRead, get_session

    from .core import DataFrame

    if project_path is None:
        project_path = get_project_path()

    manager = DatasetsManager(project_path)

    dataset = manager.find_dataset_by_slug(slug)
    if dataset is None:
        raise DatasetNotFoundError(
            f"Dataset with slug '{slug}' not found in datasets.yaml. Check that the dataset is registered."
        )

    absolute_path = manager.get_absolute_path(dataset.location)

    if not absolute_path.exists() and fetch_from_url:
        if dataset.source and dataset.source.location.data:
            absolute_path = manager.fetch_from_url(dataset)
        else:
            raise FileNotFoundError(
                f"File not found: {absolute_path}\nDataset '{dataset.slug}' has no source URL to fetch from."
            )

    if format is None and dataset.format is not None:
        format = dataset.format

    location = str(absolute_path)
    registry = PluginRegistry.get(manager.project_path)

    format_handler = registry.find_format_reader(location, format)
    if format_handler is None:
        extension = absolute_path.suffix.lower()
        detail = f"format={format!r}" if format else f"extension={extension!r}"
        raise ValueError(f"No format handler found for '{absolute_path.name}' ({detail}).")

    url_handler = registry.find_url_handler(location)
    if url_handler is None:
        raise no_url_handler_error(location)

    # Read raw bytes once: hash them, then parse from the same bytes.
    with url_handler.open(location, "rb") as stream:
        raw: bytes = stream.read()

    data_hash = "sha256:" + hashlib.sha256(raw).hexdigest()

    asset = cast(
        Asset,
        format_handler.read(
            _io.BytesIO(raw),
            format=format,
            path=location,
            dialect=dataset.dialect,
            engine="polars",
            **kwargs,
        ),
    )

    columns: list[str] = list(asset.payload.columns)

    metadata = Metadata(
        lineage=LineageMetadata(
            project_path=str(manager.project_path),
            data_hash=data_hash,
            engine="polars",
        )
    )
    metadata.lineage.add_source(dataset)
    metadata.lineage.populate_field_derivations(columns, slug)
    asset.metadata = metadata

    get_session().record_read(DatasetRead(slug=slug))

    return DataFrame(asset=asset, strict=strict, project_path=project_path)


def _read_path_or_slug(
    location: _PathLike,
    project_path: Optional[_PathLike],
    strict: Optional[bool],
    fetch_from_url: bool,
    format: Optional[str],
    **kwargs: Any,
) -> "DataFrame":
    """Resolve a path or slug to a registered dataset, then read it as polars."""
    if project_path is None:
        project_path = get_project_path()

    loc = str(location)
    # A bare slug has no path separators and no suffix.
    is_slug = "/" not in loc and "\\" not in loc and not Path(loc).suffix
    if is_slug:
        return read_dataset(loc, project_path, strict, fetch_from_url, format, **kwargs)

    manager = DatasetsManager(project_path)

    # Resolve a file path to its registered dataset (matches the pandas sibling:
    # an unregistered path raises rather than guessing by filename stem).
    dataset = manager.find_dataset_by_location(loc)
    if dataset is None:
        raise DatasetNotFoundError(
            f"Dataset at '{loc}' not found in datasets.yaml. Please add it to datasets.yaml first."
        )
    return read_dataset(dataset.slug, project_path, strict, fetch_from_url, format, **kwargs)


def read_csv(
    filepath_or_buffer: _PathLike,
    project_path: Optional[_PathLike] = None,
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    **kwargs: Any,
) -> "DataFrame":
    """Read a CSV into a polars ``DataFrame`` facade with lineage tracking."""
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "csv", **kwargs)


def read_parquet(
    filepath_or_buffer: _PathLike,
    project_path: Optional[_PathLike] = None,
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    **kwargs: Any,
) -> "DataFrame":
    """Read a Parquet file into a polars ``DataFrame`` facade with lineage tracking."""
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "parquet", **kwargs)


def read_json(
    filepath_or_buffer: _PathLike,
    project_path: Optional[_PathLike] = None,
    strict: Optional[bool] = None,
    fetch_from_url: bool = True,
    **kwargs: Any,
) -> "DataFrame":
    """Read a JSON file into a polars ``DataFrame`` facade with lineage tracking."""
    return _read_path_or_slug(filepath_or_buffer, project_path, strict, fetch_from_url, "json", **kwargs)
