"""Lineage-tracking geopandas facade. Requires the [geo] extra.

Mirrors ``sunstone.pandas``: read functions resolve a slug/path against the
project's datasets.yaml and return a ``GeoDataFrame`` wrapper backed by an
``Asset(kind=GEOFEATURES)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .asset import Asset, AssetKind
from .config import get_project_path
from .datasets import DatasetsManager
from .exceptions import DatasetNotFoundError
from .lineage import Metadata
from .plugins import PluginRegistry
from .resolution import resolve_to_dataset


class GeoDataFrame:
    """Wraps a geopandas.GeoDataFrame with sunstone metadata + lineage."""

    def __init__(self, asset: Asset) -> None:
        if asset.kind is not AssetKind.GEOFEATURES:
            raise ValueError("GeoDataFrame must wrap a GEOFEATURES asset")
        self._asset = asset

    @property
    def asset(self) -> Asset:
        return self._asset

    @property
    def data(self) -> Any:
        return self._asset.payload

    @property
    def metadata(self) -> Metadata:
        return self._asset.metadata

    def to_geojson(self, path: str | Path, *, slug: str | None = None, name: str | None = None) -> None:
        self._write(path, "geojson", slug, name)

    def to_topojson(self, path: str | Path, *, slug: str | None = None, name: str | None = None) -> None:
        self._write(path, "topojson", slug, name)

    def _write(self, path: str | Path, fmt: str, slug: str | None, name: str | None) -> None:
        if slug is not None:
            self._asset.metadata.slug = slug
        if name is not None:
            self._asset.metadata.name = name
        if not self._asset.metadata.slug or not self._asset.metadata.name:
            raise ValueError("Writing a new geo output requires both slug and name.")
        registry = PluginRegistry.get(get_project_path())
        handler = registry.find_format_writer(str(path), fmt)
        if handler is None:
            raise ValueError(f"No format handler for {fmt!r} (install sunstone-py[geo]).")
        url_handler = registry.find_url_handler(str(path))
        if url_handler is None:
            raise ValueError(f"No URL handler for {path!r}.")
        with url_handler.open(str(path), "wb") as stream:
            handler.write(self._asset, stream, format=fmt, path=str(path))


def _read(slug_or_path: str, fmt: str, project_path: str | Path | None) -> GeoDataFrame:
    project = Path(project_path) if project_path is not None else get_project_path()
    manager = DatasetsManager(project)
    dataset = resolve_to_dataset(slug_or_path, manager)
    if dataset is None:
        raise DatasetNotFoundError(f"Dataset '{slug_or_path}' not found in datasets.yaml.")
    location = str(manager.get_absolute_path(dataset.location))
    registry = PluginRegistry.get(manager.project_path)
    handler = registry.find_format_reader(location, fmt)
    if handler is None:
        raise ValueError(f"No format handler for {fmt!r} (install sunstone-py[geo]).")
    url_handler = registry.find_url_handler(location)
    if url_handler is None:
        raise ValueError(f"No URL handler for {location!r}.")
    with url_handler.open(location, "rb") as stream:
        asset = cast(Asset, handler.read(stream, format=fmt, path=location))
    if not asset.metadata.slug:
        asset.metadata.slug = dataset.slug
        asset.metadata.name = dataset.name
    return GeoDataFrame(asset)


def read_geojson(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    return _read(slug_or_path, "geojson", project_path)


def read_topojson(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    return _read(slug_or_path, "topojson", project_path)


def read_file(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    """Auto-detect geojson vs topojson from the dataset's format/extension."""
    project = Path(project_path) if project_path is not None else get_project_path()
    manager = DatasetsManager(project)
    dataset = resolve_to_dataset(slug_or_path, manager)
    fmt = dataset.format if dataset and dataset.format else None
    if fmt is None and dataset is not None and dataset.location.endswith(".topojson"):
        fmt = "topojson"
    return _read(slug_or_path, fmt or "geojson", project_path)
