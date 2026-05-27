# Plugin Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a plugin system to sunstone-py that supports auth providers, URL handlers, and format handlers, discovered via entry points and configured through cascading config.

**Architecture:** New `sunstone/plugins.py` module defines three `Protocol` types and a singleton `PluginRegistry` that discovers plugins via entry points and classifies them by protocol conformance. The existing `DataFrame.read_dataset()` and `to_csv()` methods are refactored to route through a pipeline that checks plugins before falling back to builtins. Config cascades from `pyproject.toml` → `datasets.yaml` → environment variables.

**Tech Stack:** Python 3.12+, `typing.Protocol`, `importlib.metadata`, `tomllib` (stdlib), existing `ruamel.yaml`

**Note on sidecar lineage:** The spec lists `.lineage.json` sidecar files as in-scope. However, the existing `update_output_lineage()` in `DatasetsManager` already persists lineage to `datasets.yaml` regardless of format — this works for any format handler because lineage is separate from the data file. The `.lineage.json` sidecar pattern (issue #8) is for intermediate files that aren't registered in `datasets.yaml` at all, which is a separate concern best addressed as a follow-up.

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `src/sunstone/plugins.py` | Protocol definitions, `PluginRegistry`, config loading, pipeline helpers |
| **Create:** `tests/test_plugins.py` | All plugin infrastructure tests |
| **Modify:** `src/sunstone/dataframe.py` | Refactor read/write methods to use plugin pipeline |
| **Modify:** `src/sunstone/datasets.py` | Add auth header support to `fetch_from_url()` |
| **Modify:** `src/sunstone/__init__.py` | Export plugin protocols and registry |

---

### Task 1: Protocol definitions

**Files:**
- Create: `src/sunstone/plugins.py`
- Create: `tests/test_plugins.py`

- [ ] **Step 1: Write test for protocol structural typing**

```python
# tests/test_plugins.py
"""Tests for the plugin infrastructure."""

from pathlib import Path

import pandas as pd

from sunstone.plugins import AuthProvider, FormatHandler, URLHandler


class FakeAuth:
    def authenticate(self, url, headers, dataset):
        headers["X-Test"] = "value"
        return headers


class FakeURLHandler:
    def can_handle(self, url):
        return url.startswith("fake://")

    def fetch(self, url, dest):
        dest.write_text("col1,col2\na,b\n")
        return dest


class FakeFormatHandler:
    def can_read(self, path, format):
        return path.suffix == ".fake"

    def read(self, path, **kwargs):
        return pd.DataFrame({"x": [1, 2, 3]})

    def can_write(self, path, format):
        return path.suffix == ".fake"

    def write(self, df, path, **kwargs):
        df.to_csv(path)


class PartialFormatHandler:
    """Only implements read, not write."""

    def can_read(self, path, format):
        return True

    def read(self, path, **kwargs):
        return pd.DataFrame()


class NotAPlugin:
    """Implements no protocol."""

    pass


def test_auth_provider_structural_typing():
    assert isinstance(FakeAuth(), AuthProvider)


def test_url_handler_structural_typing():
    assert isinstance(FakeURLHandler(), URLHandler)


def test_format_handler_structural_typing():
    assert isinstance(FakeFormatHandler(), FormatHandler)


def test_partial_format_handler_is_not_format_handler():
    """FormatHandler requires both read and write methods."""
    assert not isinstance(PartialFormatHandler(), FormatHandler)


def test_not_a_plugin():
    assert not isinstance(NotAPlugin(), AuthProvider)
    assert not isinstance(NotAPlugin(), URLHandler)
    assert not isinstance(NotAPlugin(), FormatHandler)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: FAIL — `sunstone.plugins` module does not exist

- [ ] **Step 3: Implement protocol definitions**

```python
# src/sunstone/plugins.py
"""
Plugin system for extending sunstone with custom auth, URL handlers, and format handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from .lineage import DatasetMetadata


@runtime_checkable
class AuthProvider(Protocol):
    """Provides authentication for HTTP requests."""

    def authenticate(
        self, url: str, headers: dict[str, str], dataset: DatasetMetadata
    ) -> dict[str, str]:
        """Return modified headers dict. Called before every HTTP fetch."""
        ...


@runtime_checkable
class URLHandler(Protocol):
    """Resolves custom URL schemes to local file paths."""

    def can_handle(self, url: str) -> bool:
        """Return True if this handler can resolve the given URL."""
        ...

    def fetch(self, url: str, dest: Path) -> Path:
        """Download/resolve URL to a local file. Return path to the file."""
        ...


@runtime_checkable
class FormatHandler(Protocol):
    """Reads and writes data formats not built into sunstone."""

    def can_read(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can read the given file/format."""
        ...

    def read(self, path: Path, **kwargs: object) -> pd.DataFrame:
        """Read file into a pandas DataFrame."""
        ...

    def can_write(self, path: Path, format: str | None) -> bool:
        """Return True if this handler can write the given file/format."""
        ...

    def write(self, df: pd.DataFrame, path: Path, **kwargs: object) -> None:
        """Write DataFrame to file."""
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Add plugin protocol definitions: AuthProvider, URLHandler, FormatHandler"
```

---

### Task 2: Plugin registry with discovery

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write tests for registry discovery and classification**

Append to `tests/test_plugins.py`:

```python
from unittest.mock import MagicMock, patch

from sunstone.plugins import PluginRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


def _make_entry_point(name, plugin_cls):
    """Create a mock entry point."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = plugin_cls
    return ep


def test_registry_discovers_auth_provider():
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-auth", FakeAuth)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 1
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0


def test_registry_discovers_url_handler():
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-url", FakeURLHandler)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_url_handlers()) == 1


def test_registry_discovers_format_handler():
    with patch(
        "sunstone.plugins._get_entry_points", return_value=[_make_entry_point("fake-fmt", FakeFormatHandler)]
    ):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_format_handlers()) == 1


def test_registry_multi_protocol_plugin():
    """A plugin implementing multiple protocols gets classified into all matching lists."""

    class MultiPlugin:
        def authenticate(self, url, headers, dataset):
            return headers

        def can_handle(self, url):
            return url.startswith("multi://")

        def fetch(self, url, dest):
            return dest

    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("multi", MultiPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 1
            assert len(registry.get_url_handlers()) == 1


def test_registry_ignores_non_plugin(caplog):
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("nope", NotAPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 0
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0
            assert "does not implement any known plugin protocol" in caplog.text


def test_registry_no_plugins():
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            assert len(registry.get_auth_providers()) == 0
            assert len(registry.get_url_handlers()) == 0
            assert len(registry.get_format_handlers()) == 0


def test_registry_passes_config_to_constructor():
    class ConfigPlugin:
        def __init__(self, config=None):
            self.config = config

        def authenticate(self, url, headers, dataset):
            return headers

    config = {"key": "value"}
    with patch("sunstone.plugins._get_entry_points", return_value=[_make_entry_point("cfg", ConfigPlugin)]):
        with patch("sunstone.plugins._load_plugin_config", return_value=config):
            registry = PluginRegistry.get()
            providers = registry.get_auth_providers()
            assert len(providers) == 1
            assert providers[0].config == config


def test_registry_singleton():
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            r1 = PluginRegistry.get()
            r2 = PluginRegistry.get()
            assert r1 is r2
```

Add `import pytest` at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "registry"`
Expected: FAIL — `PluginRegistry` not defined

- [ ] **Step 3: Implement PluginRegistry**

Add to `src/sunstone/plugins.py`:

```python
import importlib.metadata
import logging

logger = logging.getLogger(__name__)


def _get_entry_points() -> list:
    """Get entry points for sunstone plugins. Separated for testability."""
    return list(importlib.metadata.entry_points(group="sunstone.plugins"))


def _load_plugin_config(name: str) -> dict | None:
    """Load config for a plugin. Separated for testability. Implemented in Task 3."""
    return None


class PluginRegistry:
    """Discovers and manages plugins."""

    _instance: PluginRegistry | None = None

    def __init__(self) -> None:
        self._auth_providers: list[AuthProvider] = []
        self._url_handlers: list[URLHandler] = []
        self._format_handlers: list[FormatHandler] = []

    @classmethod
    def get(cls) -> PluginRegistry:
        """Singleton - lazy-loads plugins on first access."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._discover()
        return cls._instance

    def _discover(self) -> None:
        """Load plugins from entry points."""
        for ep in _get_entry_points():
            try:
                plugin_cls = ep.load()
                config = _load_plugin_config(ep.name)
                plugin = plugin_cls(config) if config else plugin_cls()
                self._register(ep.name, plugin)
            except Exception:
                logger.exception("Failed to load plugin '%s'", ep.name)

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

    def find_format_reader(self, path: Path, format: str | None) -> FormatHandler | None:
        """Find the first format handler that can read the given file."""
        for handler in self._format_handlers:
            if handler.can_read(path, format):
                return handler
        return None

    def find_format_writer(self, path: Path, format: str | None) -> FormatHandler | None:
        """Find the first format handler that can write the given file."""
        for handler in self._format_handlers:
            if handler.can_write(path, format):
                return handler
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Add PluginRegistry with entry point discovery and protocol classification"
```

---

### Task 3: Cascading config loading

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write tests for cascading config**

Append to `tests/test_plugins.py`:

```python
import os

from sunstone.plugins import _load_cascading_config


def test_config_from_pyproject(tmp_path):
    """Config loaded from pyproject.toml [tool.sunstone.plugins.<name>]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "eu-west-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}


def test_config_from_datasets_yaml(tmp_path):
    """Config loaded from datasets.yaml plugins section when no pyproject.toml."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}


def test_config_pyproject_overrides_datasets_yaml(tmp_path):
    """pyproject.toml takes precedence over datasets.yaml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "us-east-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "us-east-1"}


def test_config_env_var_override(tmp_path, monkeypatch):
    """Environment variables override file-based config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.sunstone.plugins.s3]\nregion = "eu-west-1"\n')
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    monkeypatch.setenv("SUNSTONE_PLUGIN_S3_REGION", "ap-southeast-1")
    config = _load_cascading_config("s3", tmp_path)
    assert config["region"] == "ap-southeast-1"


def test_config_env_var_hyphen_to_underscore(tmp_path, monkeypatch):
    """Plugin names with hyphens convert to underscores in env vars."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    monkeypatch.setenv("SUNSTONE_PLUGIN_BEARER_AUTH_TOKEN", "secret123")
    config = _load_cascading_config("bearer-auth", tmp_path)
    assert config == {"token": "secret123"}


def test_config_no_config_returns_none(tmp_path):
    """Returns None when no config found anywhere."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\n")

    config = _load_cascading_config("nonexistent", tmp_path)
    assert config is None


def test_config_no_pyproject_no_error(tmp_path):
    """Missing pyproject.toml doesn't cause an error."""
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("inputs: []\noutputs: []\nplugins:\n  s3:\n    region: eu-west-1\n")

    config = _load_cascading_config("s3", tmp_path)
    assert config == {"region": "eu-west-1"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "config"`
Expected: FAIL — `_load_cascading_config` not defined

- [ ] **Step 3: Implement cascading config loading**

Add to `src/sunstone/plugins.py`:

```python
import os
import tomllib

from ruamel.yaml import YAML

_config_yaml = YAML()


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
        plugins_section = data.get("plugins", {})
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
```

Update `_load_plugin_config` to delegate to `_load_cascading_config`:

```python
def _load_plugin_config(name: str) -> dict | None:
    """Load config for a plugin using cascading lookup from cwd."""
    return _load_cascading_config(name, Path.cwd())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Add cascading plugin config: pyproject.toml, datasets.yaml, env vars"
```

---

### Task 4: Pipeline helpers (find_url_handler, find_format_reader/writer)

**Files:**
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write tests for pipeline helper methods**

Append to `tests/test_plugins.py`:

```python
def test_find_url_handler_matching():
    registry = PluginRegistry()
    handler = FakeURLHandler()
    registry._url_handlers.append(handler)

    result = registry.find_url_handler("fake://bucket/file.csv")
    assert result is handler


def test_find_url_handler_no_match():
    registry = PluginRegistry()
    handler = FakeURLHandler()
    registry._url_handlers.append(handler)

    result = registry.find_url_handler("https://example.com/file.csv")
    assert result is None


def test_find_format_reader_matching():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_reader(Path("data.fake"), None)
    assert result is handler


def test_find_format_reader_no_match():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_reader(Path("data.csv"), None)
    assert result is None


def test_find_format_writer_matching():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_writer(Path("data.fake"), None)
    assert result is handler


def test_find_format_writer_no_match():
    registry = PluginRegistry()
    handler = FakeFormatHandler()
    registry._format_handlers.append(handler)

    result = registry.find_format_writer(Path("data.csv"), None)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they pass**

These methods are already implemented in Task 2. Run to confirm:

Run: `uv run pytest tests/test_plugins.py -v -k "find_"`
Expected: PASS (all 6 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_plugins.py
git commit -m "Add tests for pipeline helper methods (find_url_handler, find_format_reader/writer)"
```

---

### Task 5: Integrate auth providers into fetch_from_url

**Files:**
- Modify: `src/sunstone/datasets.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write test for auth header injection**

Append to `tests/test_plugins.py`:

```python
from unittest.mock import MagicMock, patch, PropertyMock
from sunstone.datasets import DatasetsManager
from sunstone.lineage import DatasetMetadata, Source, SourceLocation


@pytest.fixture
def dataset_with_url(tmp_path):
    """Create a minimal project with a dataset that has a source URL."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Test Dataset\n"
        "    slug: test-dataset\n"
        "    location: inputs/test.csv\n"
        "    source:\n"
        "      name: Test Source\n"
        "      location:\n"
        "        data: https://example.com/test.csv\n"
        "      attributedTo: Test Org\n"
        "      acquiredAt: '2026-01-01'\n"
        "      acquisitionMethod: manual-download\n"
        "      license: CC-BY-4.0\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    return tmp_path


def test_fetch_from_url_injects_auth_headers(dataset_with_url):
    class TestAuth:
        def authenticate(self, url, headers, dataset):
            headers["Authorization"] = "Bearer test-token"
            return headers

    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_fetch_from_url_stacks_auth_providers(dataset_with_url):
    class AuthA:
        def authenticate(self, url, headers, dataset):
            headers["X-Auth-A"] = "a"
            return headers

    class AuthB:
        def authenticate(self, url, headers, dataset):
            headers["X-Auth-B"] = "b"
            return headers

    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()
    registry._auth_providers.append(AuthA())
    registry._auth_providers.append(AuthB())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["X-Auth-A"] == "a"
        assert kwargs["headers"]["X-Auth-B"] == "b"


def test_fetch_from_url_no_auth_still_works(dataset_with_url):
    """Without auth plugins, fetch works exactly as before."""
    manager = DatasetsManager(dataset_with_url)
    dataset = manager.find_dataset_by_slug("test-dataset")

    registry = PluginRegistry()  # No auth providers

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.datasets._is_public_url", return_value=True),
        patch("sunstone.datasets.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "fetch_from_url"`
Expected: FAIL — `fetch_from_url` doesn't accept/pass headers

- [ ] **Step 3: Modify fetch_from_url to inject auth headers**

In `src/sunstone/datasets.py`, modify the `fetch_from_url` method. Add the import at the top of the method and inject headers from auth providers:

At the top of `datasets.py`, do NOT add an import of `PluginRegistry` at module level (to avoid circular imports). Instead, import it inside the method.

Replace the `fetch_from_url` method body (lines 721-811) with:

```python
    def fetch_from_url(
        self,
        dataset: DatasetMetadata,
        timeout: int = 30,
        force: bool = False,
        max_redirects: int = 10,
    ) -> Path:
        """
        Fetch a dataset from its source URL if available.

        Auth plugins are consulted to inject headers before each HTTP request.

        Args:
            dataset: The dataset metadata containing source URL.
            timeout: Request timeout in seconds.
            force: If True, fetch even if local file exists.
            max_redirects: Maximum number of redirects to follow (default: 10).

        Returns:
            Path to the local file (newly downloaded or existing).

        Raises:
            ValueError: If dataset has no source URL or URL is not allowed.
            requests.RequestException: If the fetch fails.
        """
        if not dataset.source or not dataset.source.location.data:
            raise ValueError(f"Dataset '{dataset.slug}' has no source URL")

        local_path = self.get_absolute_path(dataset.location)

        # Skip if file exists and not forcing
        if local_path.exists() and not force:
            logger.info("Using existing local file: %s", local_path)
            return local_path

        url = dataset.source.location.data

        # Check if a URL handler plugin can handle this URL
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        url_handler = registry.find_url_handler(url)

        if url_handler:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            return url_handler.fetch(url, local_path)

        # Fall back to built-in HTTP fetch
        # Validate URL points to public resource to prevent SSRF attacks
        if not _is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
            )

        # Collect auth headers from plugins
        headers: dict[str, str] = {}
        for auth in registry.get_auth_providers():
            headers = auth.authenticate(url, headers, dataset)

        logger.info("Fetching dataset from URL: %s", url)

        try:
            # Disable automatic redirects and handle them manually to prevent SSRF bypass
            # An attacker could use a public URL that redirects to a private IP
            current_url = url
            response = requests.get(current_url, timeout=timeout, allow_redirects=False, headers=headers)
            redirect_count = 0

            while response.is_redirect and redirect_count < max_redirects:
                redirect_url = response.headers.get("Location")
                if not redirect_url:
                    raise ValueError("Redirect response without Location header")

                # Resolve relative URLs against the current URL
                redirect_url = urljoin(current_url, redirect_url)

                # Validate the redirect target URL for SSRF protection
                if not _is_public_url(redirect_url):
                    raise ValueError(
                        f"Redirect URL '{redirect_url}' is not allowed. Only HTTP/HTTPS URLs "
                        "pointing to public internet addresses are permitted."
                    )

                logger.info("Following redirect to: %s", redirect_url)
                current_url = redirect_url
                response = requests.get(current_url, timeout=timeout, allow_redirects=False, headers=headers)
                redirect_count += 1

            if response.is_redirect:
                raise ValueError(f"Too many redirects (max: {max_redirects})")

            response.raise_for_status()

            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # Save to local file
            with open(local_path, "wb") as f:
                f.write(response.content)

            logger.info("✓ Successfully saved to %s (%d bytes)", local_path, len(response.content))
            return local_path

        except requests.Timeout:
            logger.error("Request timed out after %d seconds", timeout)
            raise
        except requests.RequestException as e:
            logger.error("Failed to fetch from URL: %s", e)
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "fetch_from_url"`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: PASS (all existing tests still pass)

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/datasets.py tests/test_plugins.py
git commit -m "Integrate auth providers and URL handlers into fetch_from_url"
```

---

### Task 6: Integrate format handlers into read_dataset

**Files:**
- Modify: `src/sunstone/dataframe.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write test for format handler in read_dataset**

Append to `tests/test_plugins.py`:

```python
from sunstone.dataframe import DataFrame


@pytest.fixture
def project_with_fake_format(tmp_path):
    """Create a project with a dataset using a custom format."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Fake Data\n"
        "    slug: fake-data\n"
        "    location: inputs/data.fake\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "data.fake").write_text("custom format content")
    return tmp_path


def test_read_dataset_uses_format_handler(project_with_fake_format):
    registry = PluginRegistry()
    registry._format_handlers.append(FakeFormatHandler())

    with patch.object(PluginRegistry, "get", return_value=registry):
        df = DataFrame.read_dataset("fake-data", project_path=project_with_fake_format)
        assert list(df.data.columns) == ["x"]
        assert len(df.data) == 3


def test_read_dataset_builtin_format_still_works(tmp_path):
    """CSV reading still works without any plugins."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: CSV Data\n"
        "    slug: csv-data\n"
        "    location: inputs/data.csv\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "data.csv").write_text("a,b\n1,2\n3,4\n")

    registry = PluginRegistry()  # No format handlers

    with patch.object(PluginRegistry, "get", return_value=registry):
        df = DataFrame.read_dataset("csv-data", project_path=tmp_path)
        assert list(df.data.columns) == ["a", "b"]
        assert len(df.data) == 2


def test_read_dataset_plugin_overrides_builtin(tmp_path):
    """A plugin that handles .csv overrides the builtin CSV reader."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: CSV Data\n"
        "    slug: csv-data\n"
        "    location: inputs/data.csv\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "data.csv").write_text("a,b\n1,2\n")

    class CustomCSVHandler:
        def can_read(self, path, format):
            return path.suffix == ".csv"

        def read(self, path, **kwargs):
            return pd.DataFrame({"custom": [True]})

        def can_write(self, path, format):
            return False

        def write(self, df, path, **kwargs):
            pass

    registry = PluginRegistry()
    registry._format_handlers.append(CustomCSVHandler())

    with patch.object(PluginRegistry, "get", return_value=registry):
        df = DataFrame.read_dataset("csv-data", project_path=tmp_path)
        assert list(df.data.columns) == ["custom"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "read_dataset"`
Expected: FAIL — `read_dataset` doesn't consult format handlers

- [ ] **Step 3: Refactor read_dataset to use plugin pipeline**

In `src/sunstone/dataframe.py`, modify the `read_dataset` classmethod. Replace lines 160-194 (the format detection and reading section) with:

```python
        # Determine format from extension (for builtin fallback)
        extension = absolute_path.suffix.lower()
        if format is None:
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

        # Check plugin format handlers first
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        format_handler = registry.find_format_reader(absolute_path, format)

        if format_handler:
            df = format_handler.read(absolute_path, **kwargs)
        else:
            # Fall back to built-in readers
            if format is None:
                raise ValueError(
                    f"Cannot auto-detect format for file extension '{extension}'. "
                    f"Supported extensions: .csv, .json, .xlsx, .xls, .parquet, .tsv, .txt. "
                    f"Please specify format explicitly using the 'format' parameter."
                )

            reader_map: dict[str, Callable[..., pd.DataFrame]] = {
                "csv": pd.read_csv,
                "json": pd.read_json,
                "excel": pd.read_excel,
                "parquet": pd.read_parquet,
                "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
            }

            reader = reader_map.get(format)
            if reader is None:
                raise ValueError(
                    f"Unsupported format '{format}'. Supported formats: {', '.join(reader_map.keys())}"
                )

            df = reader(absolute_path, **kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "read_dataset"`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_plugins.py
git commit -m "Integrate format handler plugins into read_dataset pipeline"
```

---

### Task 7: Integrate format handlers into to_csv (write path)

**Files:**
- Modify: `src/sunstone/dataframe.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write test for format handler in write path**

Append to `tests/test_plugins.py`:

```python
def test_to_csv_uses_format_writer(tmp_path):
    """When a format handler matches, it handles the write."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs: []\n"
        "outputs:\n"
        "  - name: Fake Output\n"
        "    slug: fake-output\n"
        "    location: outputs/data.fake\n"
        "    fields:\n"
        "      - name: x\n"
        "        type: integer\n"
    )
    (tmp_path / "outputs").mkdir()

    write_called = []

    class TrackingFormatHandler:
        def can_read(self, path, format):
            return path.suffix == ".fake"

        def read(self, path, **kwargs):
            return pd.DataFrame()

        def can_write(self, path, format):
            return path.suffix == ".fake"

        def write(self, df, path, **kwargs):
            write_called.append(path)
            df.to_csv(path)

    registry = PluginRegistry()
    registry._format_handlers.append(TrackingFormatHandler())

    df = DataFrame(data=pd.DataFrame({"x": [1, 2, 3]}), project_path=tmp_path)

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.dataframe.compute_dataframe_hash", return_value="abc123"),
        patch("sunstone.session.detect_execution_context", return_value={}),
    ):
        df.to_csv("outputs/data.fake", index=False)

    assert len(write_called) == 1
    assert write_called[0].name == "data.fake"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py -v -k "to_csv_uses_format_writer"`
Expected: FAIL — `to_csv` doesn't consult format handlers

- [ ] **Step 3: Modify to_csv to check format handlers**

In `src/sunstone/dataframe.py`, in the `to_csv` method, replace the line `self.data.to_csv(absolute_path, **pandas_kwargs)` (line 486) with:

```python
        # Check if a format handler plugin can write this file
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        format_writer = registry.find_format_writer(absolute_path, None)

        if format_writer:
            format_writer.write(self.data, absolute_path, **pandas_kwargs)
        else:
            self.data.to_csv(absolute_path, **pandas_kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v -k "to_csv"`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_plugins.py
git commit -m "Integrate format handler plugins into to_csv write pipeline"
```

---

### Task 8: Export plugins from __init__.py and add CHANGELOG entry

**Files:**
- Modify: `src/sunstone/__init__.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add plugin exports to __init__.py**

In `src/sunstone/__init__.py`, add after the existing lineage imports:

```python
# Plugin system
from .plugins import AuthProvider, FormatHandler, PluginRegistry, URLHandler
```

And add to `__all__`:

```python
    # Plugin system
    "AuthProvider",
    "URLHandler",
    "FormatHandler",
    "PluginRegistry",
```

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from sunstone import AuthProvider, URLHandler, FormatHandler, PluginRegistry; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Add CHANGELOG entry**

Add to the `[Unreleased]` section of `CHANGELOG.md`:

```
- Added: Plugin system with AuthProvider, URLHandler, and FormatHandler protocols
- Added: Plugin discovery via Python entry points (`sunstone.plugins` group)
- Added: Cascading plugin config from pyproject.toml, datasets.yaml, and environment variables
- Added: Auth header injection in dataset URL fetching
- Added: Format handler integration in read and write pipelines
```

- [ ] **Step 4: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/__init__.py CHANGELOG.md
git commit -m "Export plugin protocols and add CHANGELOG entries"
```
