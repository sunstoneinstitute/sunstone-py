# Internal Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert built-in format readers/writers and HTTP fetching into internal plugins that register through the same `PluginRegistry`, eliminating the separate fallback code paths in `dataframe.py` and `datasets.py`.

**Architecture:** Create two internal plugin classes (`BuiltinFormatHandler` and `HttpURLHandler`) that implement the existing protocols. Register them in `PluginRegistry._discover()` as defaults that external plugins can override. Then simplify the consumer code in `dataframe.py` and `datasets.py` to just ask the registry — no more inline `reader_map`/`format_map` dicts or inline HTTP fetch logic.

**Tech Stack:** Python 3.12+, existing `plugins.py` protocols, `requests`, `pandas`

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `src/sunstone/handlers.py` | `BuiltinFormatHandler` and `HttpURLHandler` implementations |
| **Create:** `tests/test_handlers.py` | Tests for internal handler classes |
| **Modify:** `src/sunstone/plugins.py` | Register internal handlers as defaults in `_discover()` |
| **Modify:** `src/sunstone/dataframe.py` | Remove inline format maps and fallback readers |
| **Modify:** `src/sunstone/datasets.py` | Remove inline HTTP fetch code, move to `HttpURLHandler` |
| **Modify:** `tests/test_plugins.py` | Update tests that relied on fallback behavior |

---

### Task 1: BuiltinFormatHandler

**Files:**
- Create: `src/sunstone/handlers.py`
- Create: `tests/test_handlers.py`

- [ ] **Step 1: Write tests for BuiltinFormatHandler**

```python
# tests/test_handlers.py
"""Tests for internal plugin handlers."""

from pathlib import Path

import pandas as pd
import pytest

from sunstone.handlers import BuiltinFormatHandler


@pytest.fixture
def handler():
    return BuiltinFormatHandler()


class TestBuiltinFormatHandlerCanRead:
    def test_csv(self, handler):
        assert handler.can_read(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_read(Path("data.whatever"), "csv")

    def test_json(self, handler):
        assert handler.can_read(Path("data.json"), None)

    def test_excel_xlsx(self, handler):
        assert handler.can_read(Path("data.xlsx"), None)

    def test_excel_xls(self, handler):
        assert handler.can_read(Path("data.xls"), None)

    def test_parquet(self, handler):
        assert handler.can_read(Path("data.parquet"), None)

    def test_tsv(self, handler):
        assert handler.can_read(Path("data.tsv"), None)

    def test_txt_as_tsv(self, handler):
        assert handler.can_read(Path("data.txt"), None)

    def test_unknown_extension(self, handler):
        assert not handler.can_read(Path("data.hdf5"), None)

    def test_unknown_format_string(self, handler):
        assert not handler.can_read(Path("data.whatever"), "hdf5")


class TestBuiltinFormatHandlerCanWrite:
    def test_csv(self, handler):
        assert handler.can_write(Path("data.csv"), None)

    def test_csv_with_format(self, handler):
        assert handler.can_write(Path("data.whatever"), "csv")

    def test_unknown(self, handler):
        assert not handler.can_write(Path("data.hdf5"), None)


class TestBuiltinFormatHandlerRead:
    def test_read_csv(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_tsv(self, handler, tmp_path):
        f = tmp_path / "data.tsv"
        f.write_text("a\tb\n1\t2\n3\t4\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_txt_as_tsv(self, handler, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("a\tb\n1\t2\n")
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_json(self, handler, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('[{"a": 1, "b": 2}]')
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_parquet(self, handler, tmp_path):
        f = tmp_path / "data.parquet"
        pd.DataFrame({"a": [1], "b": [2]}).to_parquet(f)
        df = handler.read(f)
        assert list(df.columns) == ["a", "b"]

    def test_read_passes_kwargs(self, handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        df = handler.read(f, usecols=["a"])
        assert list(df.columns) == ["a"]


class TestBuiltinFormatHandlerWrite:
    def test_write_csv(self, handler, tmp_path):
        f = tmp_path / "out.csv"
        df = pd.DataFrame({"x": [1, 2]})
        handler.write(df, f, index=False)
        result = pd.read_csv(f)
        assert list(result.columns) == ["x"]
        assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: FAIL — `sunstone.handlers` module does not exist

- [ ] **Step 3: Implement BuiltinFormatHandler**

```python
# src/sunstone/handlers.py
"""
Internal plugin implementations for built-in formats and HTTP fetching.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


# Extension -> format string mapping
_EXTENSION_MAP: dict[str, str] = {
    ".csv": "csv",
    ".json": "json",
    ".xlsx": "excel",
    ".xls": "excel",
    ".parquet": "parquet",
    ".tsv": "tsv",
    ".txt": "tsv",
}

# Format string -> pandas reader function
_READER_MAP: dict[str, Callable[..., pd.DataFrame]] = {
    "csv": pd.read_csv,
    "json": pd.read_json,
    "excel": pd.read_excel,
    "parquet": pd.read_parquet,
    "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
}

# Format string -> pandas writer method name on DataFrame
_WRITER_MAP: dict[str, str] = {
    "csv": "to_csv",
}


class BuiltinFormatHandler:
    """Handles CSV, JSON, Excel, Parquet, and TSV formats using pandas."""

    def _resolve_format(self, path: Path, format: str | None) -> str | None:
        """Resolve a format string from explicit format or file extension."""
        if format is not None:
            return format if format in _READER_MAP or format in _WRITER_MAP else None
        return _EXTENSION_MAP.get(path.suffix.lower())

    def can_read(self, path: Path, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _READER_MAP

    def read(self, path: Path, **kwargs: object) -> pd.DataFrame:
        fmt = self._resolve_format(path, None)
        reader = _READER_MAP[fmt]  # type: ignore[index]
        return reader(path, **kwargs)

    def can_write(self, path: Path, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _WRITER_MAP

    def write(self, df: pd.DataFrame, path: Path, **kwargs: object) -> None:
        fmt = self._resolve_format(path, None)
        writer = getattr(df, _WRITER_MAP[fmt])  # type: ignore[index]
        writer(path, **kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "Add BuiltinFormatHandler for CSV, JSON, Excel, Parquet, TSV"
```

---

### Task 2: HttpURLHandler

**Files:**
- Modify: `src/sunstone/handlers.py`
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Write tests for HttpURLHandler**

Append to `tests/test_handlers.py`:

```python
from unittest.mock import MagicMock, patch

from sunstone.handlers import HttpURLHandler
from sunstone.lineage import DatasetMetadata


@pytest.fixture
def http_handler():
    return HttpURLHandler()


class TestHttpURLHandlerCanHandle:
    def test_http(self, http_handler):
        assert http_handler.can_handle("http://example.com/data.csv")

    def test_https(self, http_handler):
        assert http_handler.can_handle("https://example.com/data.csv")

    def test_s3(self, http_handler):
        assert not http_handler.can_handle("s3://bucket/data.csv")

    def test_gs(self, http_handler):
        assert not http_handler.can_handle("gs://bucket/data.csv")

    def test_ftp(self, http_handler):
        assert not http_handler.can_handle("ftp://example.com/data.csv")

    def test_bare_path(self, http_handler):
        assert not http_handler.can_handle("/local/path/data.csv")

    def test_relative_path(self, http_handler):
        assert not http_handler.can_handle("data.csv")


class TestHttpURLHandlerFetch:
    def test_fetches_to_dest(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.content = b"a,b\n1,2\n"
        mock_response.raise_for_status = MagicMock()

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", return_value=mock_response),
        ):
            result = http_handler.fetch("https://example.com/data.csv", dest)
            assert result == dest
            assert dest.read_bytes() == b"a,b\n1,2\n"

    def test_rejects_private_url(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        with patch("sunstone.handlers._is_public_url", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                http_handler.fetch("http://192.168.1.1/data.csv", dest)

    def test_follows_redirects(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://cdn.example.com/data.csv"}

        final_response = MagicMock()
        final_response.is_redirect = False
        final_response.content = b"a,b\n1,2\n"
        final_response.raise_for_status = MagicMock()

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", side_effect=[redirect_response, final_response]),
        ):
            result = http_handler.fetch("https://example.com/redirect", dest)
            assert result == dest

    def test_strips_auth_on_cross_origin_redirect(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"

        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://other.com/data.csv"}

        final_response = MagicMock()
        final_response.is_redirect = False
        final_response.content = b"data"
        final_response.raise_for_status = MagicMock()

        http_handler.headers = {"Authorization": "Bearer secret"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", side_effect=[redirect_response, final_response]) as mock_get,
        ):
            http_handler.fetch("https://example.com/data.csv", dest)
            # Second call (redirect) should not have Authorization header
            second_call_headers = mock_get.call_args_list[1][1]["headers"]
            assert "Authorization" not in second_call_headers

    def test_too_many_redirects(self, http_handler, tmp_path):
        dest = tmp_path / "data.csv"
        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"Location": "https://example.com/loop"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.requests.get", return_value=redirect_response),
        ):
            with pytest.raises(ValueError, match="Too many redirects"):
                http_handler.fetch("https://example.com/data.csv", dest)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py -v -k "Http"`
Expected: FAIL — `HttpURLHandler` not defined

- [ ] **Step 3: Implement HttpURLHandler**

Add these imports to the top of `src/sunstone/handlers.py`:

```python
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests
```

Add `_is_public_url` function (move from `datasets.py` — we'll do the actual move in Task 4, for now copy it):

```python
logger = logging.getLogger(__name__)


def _is_public_url(url: str) -> bool:
    """
    Validate that a URL points to a public (non-private) resource.

    Prevents SSRF attacks by blocking non-HTTP(S) schemes, private IPs,
    localhost, loopback, and link-local addresses.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning("URL scheme '%s' not allowed (only http/https permitted)", parsed.scheme)
            return False
        if not parsed.hostname:
            logger.warning("URL has no hostname")
            return False
        addrinfos = socket.getaddrinfo(parsed.hostname, None)
        for addrinfo in addrinfos:
            sockaddr = addrinfo[4]
            ip = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                logger.warning(
                    "URL hostname '%s' resolves to restricted IP address: %s",
                    parsed.hostname,
                    ip,
                )
                return False
        return True
    except socket.gaierror:
        logger.warning("Unable to resolve hostname: %s", parsed.hostname)
        return False
    except ValueError as e:
        logger.warning("Error validating URL '%s': %s", url, e)
        return False
    except Exception as e:
        logger.exception("Unexpected error validating URL '%s': %s", url, e)
        raise
```

Add the `HttpURLHandler` class:

```python
class HttpURLHandler:
    """Fetches datasets from HTTP/HTTPS URLs with SSRF protection."""

    def __init__(self, timeout: int = 30, max_redirects: int = 10) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.headers: dict[str, str] = {}

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")

    def fetch(self, url: str, dest: Path) -> Path:
        if not _is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
            )

        logger.info("Fetching dataset from URL: %s", url)

        current_url = url
        response = requests.get(current_url, timeout=self.timeout, allow_redirects=False, headers=self.headers)
        redirect_count = 0

        while response.is_redirect and redirect_count < self.max_redirects:
            redirect_url = response.headers.get("Location")
            if not redirect_url:
                raise ValueError("Redirect response without Location header")

            redirect_url = urljoin(current_url, redirect_url)

            if not _is_public_url(redirect_url):
                raise ValueError(
                    f"Redirect URL '{redirect_url}' is not allowed. Only HTTP/HTTPS URLs "
                    "pointing to public internet addresses are permitted."
                )

            # Strip auth headers on cross-origin redirects
            redirect_parsed = urlparse(redirect_url)
            original_parsed = urlparse(url)
            if redirect_parsed.scheme != original_parsed.scheme or redirect_parsed.netloc != original_parsed.netloc:
                redirect_headers = {k: v for k, v in self.headers.items() if k.lower() != "authorization"}
            else:
                redirect_headers = self.headers

            logger.info("Following redirect to: %s", redirect_url)
            current_url = redirect_url
            response = requests.get(current_url, timeout=self.timeout, allow_redirects=False, headers=redirect_headers)
            redirect_count += 1

        if response.is_redirect:
            raise ValueError(f"Too many redirects (max: {self.max_redirects})")

        response.raise_for_status()

        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(response.content)

        logger.info("Successfully saved to %s (%d bytes)", dest, len(response.content))
        return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "Add HttpURLHandler with SSRF protection and redirect handling"
```

---

### Task 3: Register internal handlers in PluginRegistry

**Files:**
- Modify: `src/sunstone/plugins.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write tests for internal handler registration**

Add to `tests/test_plugins.py`:

```python
from sunstone.handlers import BuiltinFormatHandler, HttpURLHandler


def test_registry_registers_builtin_format_handler():
    """BuiltinFormatHandler is registered as a default."""
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            handlers = registry.get_format_handlers()
            assert any(isinstance(h, BuiltinFormatHandler) for h in handlers)


def test_registry_registers_http_url_handler():
    """HttpURLHandler is registered as a default."""
    with patch("sunstone.plugins._get_entry_points", return_value=[]):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            handlers = registry.get_url_handlers()
            assert any(isinstance(h, HttpURLHandler) for h in handlers)


def test_external_plugin_takes_priority_over_builtin():
    """External plugins registered via entry points come before builtins."""

    class ExternalCSVHandler:
        def can_read(self, path, format):
            return path.suffix == ".csv"

        def read(self, path, **kwargs):
            return pd.DataFrame({"external": [True]})

        def can_write(self, path, format):
            return path.suffix == ".csv"

        def write(self, df, path, **kwargs):
            pass

    with patch(
        "sunstone.plugins._get_entry_points",
        return_value=[_make_entry_point("ext-csv", ExternalCSVHandler)],
    ):
        with patch("sunstone.plugins._load_plugin_config", return_value=None):
            registry = PluginRegistry.get()
            handler = registry.find_format_reader(Path("data.csv"), None)
            # External plugin should win because it's registered first
            assert isinstance(handler, ExternalCSVHandler)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plugins.py -v -k "builtin or http_url or priority"`
Expected: FAIL — builtins not registered

- [ ] **Step 3: Register internal handlers in _discover**

In `src/sunstone/plugins.py`, modify the `_discover` method to register internal handlers AFTER external plugins (so externals take priority via `find_format_reader` which returns the first match):

```python
    def _discover(self) -> None:
        """Load plugins from entry points, then register internal handlers."""
        # External plugins first (they take priority)
        for ep in _get_entry_points():
            try:
                plugin_cls = ep.load()
                config = _load_plugin_config(ep.name)
                plugin = plugin_cls(config) if config else plugin_cls()
                self._register(ep.name, plugin)
            except Exception:
                logger.exception("Failed to load plugin '%s'", ep.name)

        # Internal handlers last (fallback)
        from .handlers import BuiltinFormatHandler, HttpURLHandler

        self._format_handlers.append(BuiltinFormatHandler())
        self._url_handlers.append(HttpURLHandler())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins.py -v`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS — existing behavior unchanged since builtins now serve as fallback through the registry

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Register BuiltinFormatHandler and HttpURLHandler as default plugins"
```

---

### Task 4: Simplify read_dataset — remove inline format fallback

**Files:**
- Modify: `src/sunstone/dataframe.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Write test confirming the registry handles everything**

Add to `tests/test_plugins.py`:

```python
def test_read_dataset_unknown_format_without_plugin(tmp_path):
    """Unknown format raises ValueError when no handler matches."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Unknown Data\n"
        "    slug: unknown-data\n"
        "    location: inputs/data.xyz\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "data.xyz").write_text("stuff")

    with pytest.raises(ValueError, match="No format handler found"):
        DataFrame.read_dataset("unknown-data", project_path=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py::test_read_dataset_unknown_format_without_plugin -v`
Expected: FAIL — current error message says "Cannot auto-detect format"

- [ ] **Step 3: Simplify read_dataset**

In `src/sunstone/dataframe.py`, replace lines 160-203 (the format detection, plugin check, and builtin fallback) with:

```python
        # Find a format handler (plugin or builtin) for this file
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()

        # Try explicit format string first, then extension-based detection
        format_handler = registry.find_format_reader(absolute_path, format)

        if format_handler is None:
            extension = absolute_path.suffix.lower()
            raise ValueError(
                f"No format handler found for '{absolute_path.name}'"
                + (f" (format='{format}')" if format else f" (extension='{extension}')")
                + ". Install a plugin or check the file extension."
            )

        df = format_handler.read(absolute_path, **kwargs)
```

Also remove the now-unused `Callable` import from the `typing` import line at the top of the file (line 7). Change:
```python
from typing import Any, Callable, List, Optional, Union
```
to:
```python
from typing import Any, List, Optional, Union
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — builtins in registry handle all existing formats, new test passes with new error message

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_plugins.py
git commit -m "Simplify read_dataset: delegate all format handling to plugin registry"
```

---

### Task 5: Simplify read_csv and read_excel by-path to use registry

**Files:**
- Modify: `src/sunstone/dataframe.py`

- [ ] **Step 1: Write test for read_csv by-path using format handler**

Add to `tests/test_plugins.py`:

```python
def test_read_csv_by_path_uses_registry(tmp_path):
    """read_csv with a file path routes through the format handler registry."""
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

    # This should work via the builtin format handler in the registry
    df = DataFrame.read_csv("inputs/data.csv", project_path=tmp_path)
    assert list(df.data.columns) == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it passes (it already works)**

Run: `uv run pytest tests/test_plugins.py::test_read_csv_by_path_uses_registry -v`
Expected: PASS (current code already works, this test locks the behavior)

- [ ] **Step 3: Refactor read_csv by-path to use registry**

In `src/sunstone/dataframe.py`, in the `read_csv` method, replace line 304-305:

```python
        # Read the CSV using pandas
        df = pd.read_csv(absolute_path, **kwargs)
```

with:

```python
        # Read via format handler registry
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        format_handler = registry.find_format_reader(absolute_path, "csv")
        if format_handler is None:
            raise ValueError(f"No format handler found for CSV files")
        df = format_handler.read(absolute_path, **kwargs)
```

- [ ] **Step 4: Do the same for read_excel by-path**

In `src/sunstone/dataframe.py`, in the `read_excel` method, replace line 404-405:

```python
        # Read the Excel file using pandas
        df = pd.read_excel(absolute_path, **kwargs)
```

with:

```python
        # Read via format handler registry
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        format_handler = registry.find_format_reader(absolute_path, "excel")
        if format_handler is None:
            raise ValueError(f"No format handler found for Excel files")
        df = format_handler.read(absolute_path, **kwargs)
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py tests/test_plugins.py
git commit -m "Route read_csv and read_excel by-path through format handler registry"
```

---

### Task 6: Simplify fetch_from_url — delegate to registry

**Files:**
- Modify: `src/sunstone/datasets.py`
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Write test for auth header injection via HttpURLHandler**

Add to `tests/test_handlers.py`:

```python
from sunstone.plugins import PluginRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


def test_fetch_from_url_delegates_auth_to_http_handler(tmp_path):
    """Auth providers set headers on the HttpURLHandler before fetch."""
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

    from sunstone.datasets import DatasetsManager

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_slug("test-dataset")

    class TestAuth:
        def authenticate(self, url, headers, dataset):
            headers["Authorization"] = "Bearer test-token"
            return headers

    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())
    registry._url_handlers.append(HttpURLHandler())

    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.content = b"col1,col2\na,b\n"
    mock_response.raise_for_status = MagicMock()

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.handlers._is_public_url", return_value=True),
        patch("sunstone.handlers.requests.get", return_value=mock_response) as mock_get,
    ):
        manager.fetch_from_url(dataset, force=True)
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py::test_fetch_from_url_delegates_auth_to_http_handler -v`
Expected: FAIL — fetch_from_url still has inline HTTP code

- [ ] **Step 3: Simplify fetch_from_url**

In `src/sunstone/datasets.py`, replace the `fetch_from_url` method (lines 721-837) with:

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

        Delegates to URL handler plugins. Auth plugins inject headers
        into the handler before fetching.

        Args:
            dataset: The dataset metadata containing source URL.
            timeout: Request timeout in seconds.
            force: If True, fetch even if local file exists.
            max_redirects: Maximum number of redirects to follow (default: 10).

        Returns:
            Path to the local file (newly downloaded or existing).

        Raises:
            ValueError: If dataset has no source URL or no handler matches.
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

        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        url_handler = registry.find_url_handler(url)

        if url_handler is None:
            raise ValueError(
                f"No URL handler found for '{url}'. Install a plugin that handles this URL scheme."
            )

        # Inject auth headers if the handler supports it
        if hasattr(url_handler, "headers"):
            for auth in registry.get_auth_providers():
                url_handler.headers = auth.authenticate(url, url_handler.headers, dataset)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        return url_handler.fetch(url, local_path)
```

- [ ] **Step 4: Remove now-unused imports from datasets.py**

Remove the following imports that are no longer needed in `datasets.py` since the HTTP logic moved to `handlers.py`:

From the top of `datasets.py`, remove: `import ipaddress`, `import socket`, `from urllib.parse import urljoin, urlparse`. Keep `from urllib.parse import urljoin` if used elsewhere — check first with grep. Also remove the `_is_public_url` function (lines 52-110) and the `import requests` (line 14).

**Important:** Check that `urljoin` and `urlparse` are still used in `datasets.py` before removing. `requests` may still be imported elsewhere. Only remove imports that are truly unused after the `fetch_from_url` simplification.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/datasets.py tests/test_handlers.py
git commit -m "Simplify fetch_from_url: delegate entirely to URL handler plugins"
```

---

### Task 7: Clean up old tests and update CHANGELOG

**Files:**
- Modify: `tests/test_plugins.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update tests that tested the old inline fallback**

In `tests/test_plugins.py`, the following tests tested the old inline fallback behavior and need updating:

1. `test_fetch_from_url_injects_auth_headers` — now auth goes through the handler's `headers` attribute, not `requests.get` kwargs directly. Update to patch `sunstone.handlers.requests.get` instead of `sunstone.datasets.requests.get`.

2. `test_fetch_from_url_stacks_auth_providers` — same change.

3. `test_fetch_from_url_no_auth_still_works` — same change.

4. `test_fetch_from_url_uses_url_handler` — this should still pass as-is.

5. `test_read_dataset_builtin_format_still_works` — remove the `patch.object(PluginRegistry, "get")` since the registry now always has builtins. The test should just work without mocking.

6. `test_read_dataset_plugin_overrides_builtin` — keep as-is but the plugin must be registered before builtins in the registry.

Review each test, run the suite, and fix any failures. The key change: `requests.get` is now called from `sunstone.handlers`, not `sunstone.datasets`.

- [ ] **Step 2: Run full test suite and fix failures**

Run: `uv run pytest tests/ -v`
Fix any failing tests by updating mock paths and assertions.

- [ ] **Step 3: Add CHANGELOG entry**

Add under `## [Unreleased]` in `CHANGELOG.md`:

```
- Changed: Built-in format handlers (CSV, JSON, Excel, Parquet, TSV) now registered as internal plugins
- Changed: HTTP URL fetching now handled by internal HttpURLHandler plugin
```

- [ ] **Step 4: Run full test suite one final time**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_plugins.py CHANGELOG.md
git commit -m "Update tests for internal plugin architecture and add CHANGELOG entries"
```
