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
from urllib.parse import urlparse
from typing import (
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Callable,
    Iterator,
    Literal,
    Protocol,
    TextIO,
    overload,
    runtime_checkable,
)

import typer
from ruamel.yaml import YAML

from .lineage import DatasetMetadata

if TYPE_CHECKING:
    from .resource import ResourceLocation, StoreFormatHandler

from .handlers_meta import ContentDescriptor

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
    """Reads and writes data formats from/to a single byte stream.

    A handler may carry the class attribute ``__sunstone_handler_protocol__ = 2``
    to declare that ``read()`` returns a sunstone ``Asset`` rather than a
    ``pd.DataFrame``. Plugins without the marker are wrapped by
    ``TabularDataFrameAdapter`` and return ``Asset(kind=AssetKind.TABULAR, ...)``.
    """

    def supports_native_metadata_extraction(self) -> bool:
        """True if this handler can extract format-native metadata (e.g.,
        CRS/transform from a GeoTIFF, schema from a Parquet, EXIF from a PNG)
        and populate the resulting Asset's metadata with it."""
        ...

    def supports_sunstone_metadata_embedding(self) -> bool:
        """True if this handler can round-trip a full sunstone ``Metadata`` blob
        into and out of the file format (e.g., Parquet: yes; PNG: no)."""
        ...

    # Legacy predicate kept as an optional alias for adapter compatibility.
    def supports_metadata(self) -> bool:
        """Legacy alias for ``supports_sunstone_metadata_embedding()``.

        Older handlers may only expose this method. The adapter layer maps
        old answers onto the new capability predicates.
        """
        ...

    def can_read(self, path: str, format: str | None) -> bool:
        """Return True if this handler can read the given format. path is used for extension detection."""
        ...

    def read(self, stream: BinaryIO, **kwargs: object) -> object:
        """Read stream into either a ``pd.DataFrame`` (legacy) or a sunstone
        ``Asset`` (new). The registry normalises both via the adapter layer."""
        ...

    def can_write(self, path: str, format: str | None) -> bool:
        """Return True if this handler can write the given format. path is used for extension detection."""
        ...

    def write(self, payload: object, stream: BinaryIO, **kwargs: object) -> None:
        """Write payload to stream. The payload is either a ``pd.DataFrame``
        (legacy) or a sunstone ``Asset`` (new)."""
        ...


# NOTE: ``content_descriptors`` and ``extensions`` are intentionally NOT part
# of the ``@runtime_checkable`` ``FormatHandler`` surface above. ``runtime_checkable``
# Protocols verify member existence via ``hasattr`` for *every* declared method,
# so adding them there would break ``isinstance(handler, FormatHandler)`` for
# legacy v1/v2 handlers that lack them — violating the spec's "Optional;
# default treated as empty tuple by the registry" guarantee. Instead, the
# registry uses this dedicated, separately-checkable Protocol via ``isinstance``
# or ``getattr`` with a ``()`` fallback.
@runtime_checkable
class ContentDescriptorAware(Protocol):
    """Optional Protocol that handlers may implement to advertise the
    content types and file extensions they natively read/write.

    Handlers without these methods continue to work; the registry treats
    a missing implementation as "no advertised descriptors / extensions".
    """

    def content_descriptors(self) -> tuple["ContentDescriptor", ...]:
        """Return (content_type, content_encoding) pairs this handler reads/writes.

        Optional; default treated as empty tuple by the registry. A handler may
        return multiple descriptors if it natively handles several encodings of
        the same payload type (e.g. tar both raw and gzip-compressed).
        """
        ...

    def extensions(self) -> tuple[str, ...]:
        """Return file extensions (including the leading dot) this handler
        recognises, including compound extensions (e.g. ``".tar.gz"``).
        Optional; default empty.
        """
        ...


@runtime_checkable
class CLIProvider(Protocol):
    """Provides CLI subcommand groups to mount on the main sunstone CLI."""

    def cli_groups(self) -> list[tuple[str, typer.Typer]]:
        """Return (name, typer_app) tuples to mount as CLI subcommand groups."""
        ...


@runtime_checkable
class EnvSectionProvider(Protocol):
    """Owns a typed slice of environment configuration.

    Plugins implement this to claim a TOML subtable name and return a
    callable (dataclass/Pydantic class/factory) that validates the
    subtable's keys and returns a typed model.
    """

    def env_section_name(self) -> str:
        """Return the TOML subtable key (e.g. 'data-platform')."""
        ...

    def env_section_model(self) -> Callable[..., Any]:
        """Return a callable that accepts the subtable as **kwargs."""
        ...


logger = logging.getLogger(__name__)


# URL schemes whose handlers ship in optional extras. Used to turn the opaque
# "No URL handler found" miss into actionable guidance: the handler is silently
# skipped during discovery when its dependency is missing, so the most common
# cause of a miss on these schemes is a not-installed extra.
_SCHEME_EXTRAS: dict[str, str] = {
    "gs": "gcs",
    "s3": "s3",
    "r2": "s3",
}


def no_url_handler_error(url: str) -> ValueError:
    """Build a ValueError for an unresolvable URL, pointing at the optional
    extra that provides the scheme's handler when one is known."""
    scheme = urlparse(url).scheme
    extra = _SCHEME_EXTRAS.get(scheme)
    if extra:
        return ValueError(
            f"No URL handler found for '{url}'. The '{scheme}://' scheme requires the "
            f"optional '{extra}' extra; install it with: uv add 'sunstone-py[{extra}]'"
        )
    return ValueError(f"No URL handler found for '{url}'. Install a plugin that handles this URL scheme.")


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
        self._store_format_handlers: list[object] = []
        from .field_types import FieldTypeRegistry

        self.field_types = FieldTypeRegistry()
        self._cli_providers: list[CLIProvider] = []
        self._env_section_providers: list[EnvSectionProvider] = []

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

        # Optional store-format handlers. The handler modules import their
        # heavy dep (zarr / h5py) lazily inside read(), so a successful module
        # import does NOT guarantee the dep is installed. Probe the dep
        # directly before registering, otherwise the handler shows up in
        # known_content_types() / handler_for_content() but blows up with
        # ImportError on first use.
        try:
            import zarr  # noqa: F401
            from .handlers_zarr import ZarrStoreHandler

            self._store_format_handlers.append(ZarrStoreHandler())
        except ImportError:
            pass  # zarr not installed

        try:
            import h5py  # noqa: F401
            from .handlers_hdf5 import Hdf5StoreHandler

            self._store_format_handlers.append(Hdf5StoreHandler())
        except ImportError:
            pass  # h5py extra not installed

        # Internal handlers last (fallback)
        from .handlers import (
            BlobFormatHandler,
            BuiltinFormatHandler,
            HttpURLHandler,
            ParquetFormatHandler,
        )

        # Legacy handlers narrow `write` to `pd.DataFrame`; they are still
        # callable as FormatHandler at runtime via duck typing. Task 2.2 wraps
        # these in the TabularDataFrameAdapter, which conforms to the wider
        # Protocol exactly.
        self._format_handlers.append(ParquetFormatHandler())  # type: ignore[arg-type]
        try:
            from .handlers_npz import NpzFormatHandler

            self._format_handlers.append(NpzFormatHandler())  # type: ignore[arg-type]
        except ImportError:
            pass  # numpy not installed (shouldn't normally happen — pandas pulls it in)
        # Optional geo handler (GeoJSON/TopoJSON). Registered before the
        # catch-all BuiltinFormatHandler so .geojson/.topojson resolve here.
        try:
            import geopandas  # noqa: F401

            from .handlers_geo import GeoFeaturesFormatHandler

            geo_handler = GeoFeaturesFormatHandler()
            self._format_handlers.append(geo_handler)  # type: ignore[arg-type]
            for descriptor in geo_handler.field_types():
                self.field_types.register(descriptor)
        except ImportError:
            pass  # [geo] extra not installed
        self._format_handlers.append(BuiltinFormatHandler())  # type: ignore[arg-type]
        # BlobFormatHandler is the residual fallback — registered LAST so more
        # specific handlers (Parquet, BuiltinFormatHandler for CSV/XLSX/etc.)
        # claim their extensions first.
        self._format_handlers.append(BlobFormatHandler())  # type: ignore[arg-type]
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
        # NOTE: legacy external FormatHandler plugins (those without the new
        # supports_native_metadata_extraction / supports_sunstone_metadata_embedding
        # predicates) fail this isinstance check. They will be picked up by
        # Task 2.2's TabularDataFrameAdapter, which wraps them at the
        # registry boundary before downstream code consults them.
        if isinstance(plugin, FormatHandler):
            self._format_handlers.append(plugin)
            registered = True
        from .resource import StoreFormatHandler

        if isinstance(plugin, StoreFormatHandler):
            self._store_format_handlers.append(plugin)
            registered = True
        if isinstance(plugin, CLIProvider):
            self._cli_providers.append(plugin)
            registered = True
        if isinstance(plugin, EnvSectionProvider):
            self._env_section_providers.append(plugin)
            registered = True
        if hasattr(plugin, "field_types") and callable(plugin.field_types):
            for descriptor in plugin.field_types():
                self.field_types.register(descriptor)
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

    def get_asset_format_handlers(self) -> list[object]:
        """Return all registered format handlers normalised to the
        `Asset`-returning shape.

        Native-style handlers (those carrying
        `__sunstone_handler_protocol__ = 2`) are returned as-is. Legacy
        DataFrame-returning handlers are wrapped in `TabularDataFrameAdapter`.
        """
        from .adapter import TabularDataFrameAdapter

        out: list[object] = []
        for h in self._format_handlers:
            protocol = getattr(h, "__sunstone_handler_protocol__", None)
            if isinstance(protocol, int) and protocol >= 2:
                out.append(h)
            else:
                out.append(TabularDataFrameAdapter(h))
        return out

    def get_store_format_handlers(self) -> list[object]:
        return self._store_format_handlers

    def _iter_descriptor_aware_handlers(self) -> "Iterator[FormatHandler | StoreFormatHandler]":
        """Yield every registered format and store handler in lookup order.

        Format handlers come first so they win on conflict with store handlers.
        """
        yield from self._format_handlers
        yield from self._store_format_handlers  # type: ignore[misc]

    def known_content_descriptors(self) -> set[ContentDescriptor]:
        """Union of content_descriptors() across all registered format and store
        handlers that declare them. Handlers without the method contribute nothing.
        """
        out: set[ContentDescriptor] = set()
        for handler in self._iter_descriptor_aware_handlers():
            descriptors = getattr(handler, "content_descriptors", lambda: ())()
            out.update(descriptors)
        return out

    def known_content_types(self) -> set[str]:
        """Convenience projection — the set of content_type strings present in
        known_content_descriptors(), regardless of encoding.
        """
        return {d.content_type for d in self.known_content_descriptors()}

    def known_extensions(self) -> dict[str, "FormatHandler | StoreFormatHandler"]:
        """Map of declared extension -> handler. First-registered wins, matching
        dispatch priority: external plugins (registered before internals) win
        over built-ins on overlapping extensions.
        """
        out: dict[str, FormatHandler | StoreFormatHandler] = {}
        for handler in self._iter_descriptor_aware_handlers():
            exts = getattr(handler, "extensions", lambda: ())()
            for ext in exts:
                out.setdefault(ext, handler)  # type: ignore[arg-type]
        return out

    def handler_for_content(
        self,
        content_type: str,
        content_encoding: str | None = None,
    ) -> "FormatHandler | StoreFormatHandler | None":
        """First handler whose declared content_descriptors() contains a matching
        (content_type, content_encoding) pair. content_type lookup strips
        parameters; e.g. "text/csv; charset=utf-8" matches "text/csv".
        Returns None if no handler claims the pair.
        """
        # Strip parameters from incoming content_type (e.g. "text/csv; charset=utf-8" -> "text/csv")
        bare_type = content_type.split(";", 1)[0].strip()
        for handler in self._iter_descriptor_aware_handlers():
            descriptors: tuple[ContentDescriptor, ...] = getattr(handler, "content_descriptors", lambda: ())()
            for descriptor in descriptors:
                if descriptor.content_type == bare_type and descriptor.content_encoding == content_encoding:
                    return handler
        return None

    def find_store_format_reader(self, location: "ResourceLocation", format: str | None) -> object | None:
        for h in self._store_format_handlers:
            if h.can_read_store(location, format):  # type: ignore[attr-defined]
                return h
        return None

    def find_store_format_writer(self, location: "ResourceLocation", format: str | None) -> object | None:
        for h in self._store_format_handlers:
            if h.can_write_store(location, format):  # type: ignore[attr-defined]
                return h
        return None

    def get_cli_groups(self) -> list[tuple[str, typer.Typer]]:
        """Return all (name, typer_app) tuples from registered CLIProviders."""
        groups: list[tuple[str, typer.Typer]] = []
        for provider in self._cli_providers:
            try:
                groups.extend(provider.cli_groups())
            except Exception:
                logger.exception("Failed to get CLI groups from provider %r", provider)
        return groups

    def get_env_section_providers(self) -> list[EnvSectionProvider]:
        """Return all registered env section providers."""
        return self._env_section_providers

    def handler_supports_metadata(self, handler: FormatHandler) -> bool:
        """Check if a format handler supports metadata embedding.

        Returns False for legacy plugins that don't implement supports_metadata().
        """
        try:
            return handler.supports_metadata()
        except AttributeError:
            return False

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
            raise no_url_handler_error(url)
        with handler.open(url, "rb") as src, builtins.open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return dest
