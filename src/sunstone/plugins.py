"""
Plugin system for extending sunstone with custom auth, URL handlers, and format handlers.
"""

from __future__ import annotations

import builtins
import importlib.metadata
import logging
import os
import shutil
import tomllib
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, TextIO, overload, runtime_checkable

import pandas as pd
from ruamel.yaml import YAML

from .lineage import DatasetMetadata

_config_yaml = YAML()


@runtime_checkable
class AuthProvider(Protocol):
    """Provides authentication for HTTP requests."""

    def authenticate(self, url: str, headers: dict[str, str], dataset: DatasetMetadata) -> dict[str, str]:
        """Return modified headers dict. Called before every HTTP fetch."""
        ...


@runtime_checkable
class URLHandler(Protocol):
    """Resolves URLs to readable/writable streams."""

    def can_handle(self, url: str) -> bool:
        """Return True if this handler can resolve the given URL."""
        ...

    @overload
    def open(self, url: str, mode: Literal["r"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"]) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"]) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO: ...


@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats."""

    def can_read(self, path: str, format: str | None) -> bool:
        """Return True if this handler can read the given format. path is used for extension detection."""
        ...

    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame:
        """Read stream into a pandas DataFrame."""
        ...

    def can_write(self, path: str, format: str | None) -> bool:
        """Return True if this handler can write the given format. path is used for extension detection."""
        ...

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        """Write DataFrame to stream."""
        ...


logger = logging.getLogger(__name__)


def _get_entry_points() -> list:
    """Get entry points for sunstone plugins. Separated for testability."""
    return list(importlib.metadata.entry_points(group="sunstone.plugins"))


def _load_cascading_config(name: str, project_path: Path) -> dict | None:
    """
    Load plugin config with cascading precedence:
    1. pyproject.toml [tool.sunstone.plugins.<name>]
    2. datasets.yaml plugins.<name>
    3. Environment variables SUNSTONE_PLUGIN_<NAME>_<KEY>

    Later sources override earlier ones. Returns None if no config found.
    """
    config: dict = {}

    # Source 1: datasets.yaml
    datasets_path = project_path / "datasets.yaml"
    if datasets_path.exists():
        with open(datasets_path) as f:
            data = _config_yaml.load(f) or {}
        plugins_section = data.get("plugins") or {}
        if name in plugins_section and plugins_section[name]:
            config.update(plugins_section[name])

    # Source 2: pyproject.toml (overrides datasets.yaml)
    pyproject_path = project_path / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
        plugin_config = pyproject.get("tool", {}).get("sunstone", {}).get("plugins", {}).get(name)
        if plugin_config:
            config.update(plugin_config)

    # Source 3: environment variables (override everything)
    env_prefix = f"SUNSTONE_PLUGIN_{name.upper().replace('-', '_')}_"
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            config_key = key[len(env_prefix) :].lower()
            config[config_key] = value

    return config if config else None


def _load_plugin_config(name: str, project_path: Path | None = None) -> dict | None:
    """Load config for a plugin using cascading lookup from the target project."""
    return _load_cascading_config(name, (project_path or Path.cwd()).resolve())


class PluginRegistry:
    """Discovers and manages plugins."""

    _instance: PluginRegistry | None = None
    _instances: dict[Path, "PluginRegistry"] = {}

    def __init__(self, project_path: Path | None = None) -> None:
        self.project_path = project_path.resolve() if project_path is not None else None
        self._auth_providers: list[AuthProvider] = []
        from .handlers import LocalFileHandler

        self._url_handlers: list[URLHandler] = [LocalFileHandler()]
        self._format_handlers: list[FormatHandler] = []

    @classmethod
    def get(cls, project_path: Path | str | None = None) -> PluginRegistry:
        """Return a cached registry instance, scoped to the target project when provided."""
        if project_path is None:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance._discover()
            return cls._instance

        project_key = Path(project_path).resolve()
        registry = cls._instances.get(project_key)
        if registry is None:
            registry = cls(project_key)
            registry._discover()
            cls._instances[project_key] = registry
        return registry

    def _discover(self) -> None:
        """Load plugins from entry points, then register internal handlers."""
        # External plugins first (they take priority)
        for ep in _get_entry_points():
            try:
                plugin_cls = ep.load()
                config = _load_plugin_config(ep.name, self.project_path)
                plugin = plugin_cls(config) if config else plugin_cls()
                self._register(ep.name, plugin)
            except Exception:
                logger.exception("Failed to load plugin '%s'", ep.name)

        # Optional cloud handlers
        try:
            from .handlers_gcs import GcsURLHandler

            self._url_handlers.append(GcsURLHandler())
        except ImportError:
            pass  # google-cloud-storage not installed

        try:
            from .handlers_s3 import S3URLHandler

            s3_config = _load_plugin_config("s3", self.project_path)
            self._url_handlers.append(S3URLHandler(config=s3_config))
        except ImportError:
            pass  # boto3 not installed

        # Internal handlers last (fallback)
        from .handlers import BuiltinFormatHandler, HttpURLHandler

        self._format_handlers.append(BuiltinFormatHandler())
        self._url_handlers.append(HttpURLHandler())
        # LocalFileHandler is always present (registered in __init__)

    def _register(self, name: str, plugin: object) -> None:
        """Classify plugin by protocol conformance."""
        registered = False
        if isinstance(plugin, AuthProvider):
            self._auth_providers.append(plugin)
            registered = True
        if isinstance(plugin, URLHandler):
            self._url_handlers.append(plugin)
            registered = True
        if isinstance(plugin, FormatHandler):
            self._format_handlers.append(plugin)
            registered = True
        if not registered:
            logger.warning("Plugin '%s' does not implement any known plugin protocol", name)

    def get_auth_providers(self) -> list[AuthProvider]:
        """Return all registered auth providers."""
        return self._auth_providers

    def get_url_handlers(self) -> list[URLHandler]:
        """Return all registered URL handlers."""
        return self._url_handlers

    def get_format_handlers(self) -> list[FormatHandler]:
        """Return all registered format handlers."""
        return self._format_handlers

    def find_url_handler(self, url: str) -> URLHandler | None:
        """Find the first URL handler that can handle the given URL."""
        for handler in self._url_handlers:
            if handler.can_handle(url):
                return handler
        return None

    def find_format_reader(self, path: Path | str, format: str | None) -> FormatHandler | None:
        """Find the first format handler that can read the given file."""
        path_str = str(path)
        for handler in self._format_handlers:
            if handler.can_read(path_str, format):
                return handler
        return None

    def find_format_writer(self, path: Path | str, format: str | None) -> FormatHandler | None:
        """Find the first format handler that can write the given file."""
        path_str = str(path)
        for handler in self._format_handlers:
            if handler.can_write(path_str, format):
                return handler
        return None

    def fetch(self, url: str, dest: Path) -> Path:
        """Convenience: download url to local file via open()."""
        handler = self.find_url_handler(url)
        if handler is None:
            raise ValueError(f"No URL handler found for: {url}")
        with handler.open(url, "rb") as src, builtins.open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return dest
