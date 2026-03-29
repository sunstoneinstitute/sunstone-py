# Plugin Architecture Design

## Overview

A plugin system for sunstone-py that supports three plugin types: authentication providers, URL handlers, and format handlers. Plugins are discovered via Python entry points, configured in `pyproject.toml`, and composed in a pipeline that extends sunstone's read/write operations.

## Design Decisions

- **Typed Protocols** (structural typing) for plugin contracts — no inheritance required
- **Entry point discovery** via `sunstone.plugins` group in `pyproject.toml`
- **Pipeline composition** with defined phases: resolve URL -> authenticate -> fetch -> read format
- **Plugin config** in `[tool.sunstone.plugins.<name>]` sections of the data project's `pyproject.toml`
- **Plugins take priority** over builtins — a custom CSV handler overrides the default
- **Zero overhead** when no plugins installed — existing code paths run unchanged

## Plugin Discovery & Registry

Plugins are discovered via Python entry points and managed by a central `PluginRegistry`.

### Entry point registration

```toml
# In a plugin's pyproject.toml
[project.entry-points."sunstone.plugins"]
s3 = "sunstone_s3:S3Plugin"
```

### Registry

```python
# sunstone/plugins.py
class PluginRegistry:
    """Discovers and manages plugins."""

    _instance: PluginRegistry | None = None

    @classmethod
    def get(cls) -> PluginRegistry:
        """Singleton - lazy-loads plugins on first access."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._discover()
        return cls._instance

    def _discover(self) -> None:
        """Load plugins from entry points."""
        for ep in importlib.metadata.entry_points(group="sunstone.plugins"):
            plugin_cls = ep.load()
            config = self._load_config(ep.name)
            plugin = plugin_cls(config) if config else plugin_cls()
            self._register(ep.name, plugin)

    def _register(self, name: str, plugin: object) -> None:
        """Classify plugin by protocol conformance."""
        if isinstance(plugin, AuthProvider):
            self._auth_providers.append(plugin)
        if isinstance(plugin, URLHandler):
            self._url_handlers.append(plugin)
        if isinstance(plugin, FormatHandler):
            self._format_handlers.append(plugin)
```

### Config loading

Plugin-specific configuration lives in the data project's `pyproject.toml`:

```toml
[tool.sunstone.plugins.s3]
region = "eu-west-1"
role_arn = "arn:aws:iam::123:role/data-reader"
```

The config dict is passed to the plugin constructor. Plugins that need no config accept no arguments.

## Protocol Definitions

Three `@runtime_checkable` protocols define plugin contracts.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AuthProvider(Protocol):
    """Provides authentication for HTTP requests."""

    def authenticate(self, url: str, headers: dict[str, str],
                     dataset: DatasetMetadata) -> dict[str, str]:
        """Return modified headers dict. Called before every HTTP fetch."""
        ...

@runtime_checkable
class URLHandler(Protocol):
    """Resolves custom URL schemes to local file paths."""

    def can_handle(self, url: str) -> bool:
        """Return True if this handler can resolve the given URL."""
        ...

    def fetch(self, url: str, dest: Path, config: dict) -> Path:
        """Download/resolve URL to a local file. Return path to the file."""
        ...

@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats not built into sunstone."""

    def can_read(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can read the given file/format."""
        ...

    def read(self, path: Path, **kwargs) -> pd.DataFrame:
        """Read file into a pandas DataFrame."""
        ...

    def can_write(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can write the given file/format."""
        ...

    def write(self, df: pd.DataFrame, path: Path, **kwargs) -> None:
        """Write DataFrame to file."""
        ...
```

Design notes:

- `@runtime_checkable` enables `isinstance()` checks in the registry for structural typing at runtime.
- `AuthProvider` returns headers (not a requests object) to stay transport-agnostic. URL handlers that use non-HTTP transports (e.g. boto3 for S3) handle their own auth by also implementing `AuthProvider`.
- `URLHandler.fetch` takes a `dest` path so the caller decides file location (consistent with existing `fetch_from_url` behavior).
- `FormatHandler` splits `can_read`/`can_write` because a plugin might support reading but not writing a format (or vice versa).
- `FormatHandler` does not handle lineage. Sidecar `.lineage.json` is a core feature, not a plugin responsibility.

## The Pipeline

### Read pipeline

```
resolve URL -> authenticate -> fetch -> read format -> (lineage tracking)
```

```python
def _resolve_and_fetch(self, dataset: DatasetMetadata, dest: Path) -> Path:
    url = dataset.source.location.data
    registry = PluginRegistry.get()

    # Find a URL handler for this scheme
    handler = registry.find_url_handler(url)

    if handler:
        # Plugin handles fetch (e.g. s3://, gs://, sftp://)
        return handler.fetch(url, dest, config=registry.get_config(handler))

    # Fall back to built-in HTTP fetch
    if not _is_public_url(url):
        raise ValueError(...)

    headers = {}
    # Run all auth providers for HTTP URLs
    for auth in registry.get_auth_providers():
        headers = auth.authenticate(url, headers, dataset)

    return self._http_fetch(url, dest, headers=headers)
```

```python
def _read_file(self, path: Path, format: str | None, **kwargs) -> pd.DataFrame:
    registry = PluginRegistry.get()

    # Check plugin format handlers first
    handler = registry.find_format_handler(path, format, mode="read")
    if handler:
        return handler.read(path, **kwargs)

    # Fall back to built-in readers (csv, json, excel, parquet, tsv)
    reader = self._builtin_readers.get(format)
    if reader is None:
        raise ValueError(f"Unsupported format '{format}'...")
    return reader(path, **kwargs)
```

### Key behaviors

- **Plugins take priority over builtins** — registering a custom CSV handler overrides the default.
- **Auth providers stack** — all matching auth providers run, each adding/modifying headers.
- **URL handlers are exclusive** — first handler where `can_handle(url)` returns `True` wins.
- **Write pipeline mirrors read** — same pattern: find format handler, plugin or builtin, then lineage/sidecar tracking (always core).
- **No plugins installed = no overhead** — `PluginRegistry.get()` finds no entry points and existing code paths run unchanged.

## Integration Points

Changes to existing code are minimal:

### `dataframe.py:read_dataset()` (line ~149-194)

Currently has inline format detection and reader dispatch. Refactor to:
- Extract `_resolve_and_fetch()` — replaces the direct `manager.fetch_from_url()` call
- Extract `_read_file()` — replaces the `format_map` / `reader_map` dicts

### `dataframe.py:read_csv()` (line ~264 onward)

Currently calls `pd.read_csv()` directly after resolving the path. Route through `_read_file()` so format plugins can intercept.

### `datasets.py:fetch_from_url()` (line ~721)

Becomes the `_http_fetch()` fallback inside `_resolve_and_fetch()`, with auth provider headers injected. SSRF protection stays exactly where it is — it only applies to HTTP fetches, not plugin-handled URLs (S3/GCS plugins handle their own security).

### `dataframe.py:to_csv()` and future write methods

Mirror the read pipeline: check for format handler plugin, fall back to builtin. Sidecar `.lineage.json` is written by core after the format handler's `write()` returns.

### What doesn't change

- `DatasetsManager` — still owns `datasets.yaml`, lineage persistence, strict/relaxed mode
- `LineageSession` — still accumulates reads and flushes on write
- `pandas.py` — still the user-facing API, delegates to `DataFrame` methods
- SSRF protection — stays in `datasets.py`, untouched

## Example Plugins

### Auth plugin — Bearer token from environment

```python
# sunstone_auth_bearer/plugin.py
class BearerAuthPlugin:
    def __init__(self, config: dict | None = None):
        self.env_var = (config or {}).get("env_var", "SUNSTONE_API_TOKEN")
        self.url_pattern = (config or {}).get("url_pattern", None)

    def authenticate(self, url: str, headers: dict[str, str],
                     dataset: DatasetMetadata) -> dict[str, str]:
        if self.url_pattern and self.url_pattern not in url:
            return headers
        token = os.environ.get(self.env_var)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
```

```toml
# Project's pyproject.toml
[tool.sunstone.plugins.bearer-auth]
env_var = "DATA_PORTAL_TOKEN"
url_pattern = "data.sunstone.institute"
```

### URL handler — S3

```python
# sunstone_s3/plugin.py
class S3Plugin:
    def __init__(self, config: dict | None = None):
        self.region = (config or {}).get("region", "us-east-1")

    def can_handle(self, url: str) -> bool:
        return url.startswith("s3://")

    def fetch(self, url: str, dest: Path, config: dict) -> Path:
        import boto3
        bucket, key = self._parse_s3_url(url)
        s3 = boto3.client("s3", region_name=self.region)
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))
        return dest
```

### Format handler — HDF5 (addresses issue #8)

```python
# sunstone_hdf5/plugin.py
class HDF5Plugin:
    def __init__(self, config: dict | None = None):
        self.default_key = (config or {}).get("key", "data")

    def can_read(self, path: Path, format: str | None) -> bool:
        return format == "hdf5" or path.suffix in (".h5", ".hdf5")

    def read(self, path: Path, **kwargs) -> pd.DataFrame:
        key = kwargs.pop("key", self.default_key)
        return pd.read_hdf(path, key=key, **kwargs)

    def can_write(self, path: Path, format: str | None) -> bool:
        return format == "hdf5" or path.suffix in (".h5", ".hdf5")

    def write(self, df: pd.DataFrame, path: Path, **kwargs) -> None:
        key = kwargs.pop("key", self.default_key)
        df.to_hdf(path, key=key, **kwargs)
```

## Testing Strategy

### Core infrastructure tests (in sunstone-py)

- **Registry discovery** — mock entry points, verify plugins classified by protocol
- **Pipeline fallback** — no plugins installed, existing behavior unchanged
- **Plugin priority** — plugin format handler beats builtin for same extension
- **Auth stacking** — two auth providers both modify headers
- **URL handler routing** — correct handler selected by `can_handle()`
- **Config loading** — `[tool.sunstone.plugins.foo]` passed to constructor correctly
- **Bad plugins** — plugin implementing no protocol logs warning, doesn't crash

### Test doubles

```python
class FakeAuthProvider:
    def authenticate(self, url, headers, dataset):
        headers["X-Test"] = "injected"
        return headers

class FakeURLHandler:
    def can_handle(self, url): return url.startswith("fake://")
    def fetch(self, url, dest, config):
        dest.write_text("col1,col2\na,b\n")
        return dest

class FakeFormatHandler:
    def can_read(self, path, format): return path.suffix == ".fake"
    def read(self, path, **kwargs): return pd.DataFrame({"x": [1, 2, 3]})
    def can_write(self, path, format): return path.suffix == ".fake"
    def write(self, df, path, **kwargs): df.to_csv(path)
```

These live in sunstone-py's test suite. Plugin packages have their own tests for actual S3/GCS/HDF5 behavior.

## Scope

### In scope (v1)

- `sunstone/plugins.py` module — `PluginRegistry`, three `Protocol` definitions, pipeline helpers
- Refactor `dataframe.py` read/write methods to call through the pipeline
- Add auth header injection to `datasets.py` HTTP fetch
- Config loading from `pyproject.toml` `[tool.sunstone.plugins.*]`
- Test suite for plugin infrastructure with test doubles
- Sidecar `.lineage.json` for plugin-handled formats (core feature, not plugin)

### Deferred — future plugin types

- Lineage enrichers (`on_write` hooks)
- License rule providers (issue #13)
- Validation hooks (pre-read / post-write)
- Publishing destinations (issue #33)
- Reference data providers (issue #9)
- Attribution generators (issue #14)
- Event hook system (generic version of the above)

### Deferred — ecosystem

- Actual S3/GCS/HDF5 plugin packages (infrastructure first, plugins later)
- Plugin versioning / compatibility checks
- CLI commands for listing installed plugins (`sunstone plugin list`)
- Sandboxing or permission model for untrusted plugins

The deferred plugin types all follow the same pattern: add a new `Protocol`, add a phase to the pipeline, add `isinstance` check in the registry. The architecture supports this without breaking existing plugins.
