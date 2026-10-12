# Stream-Based Plugin IO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace path-based plugin IO with stream-based `open()` protocol so all data reads/writes (local, HTTP, GCS, S3/R2) go through a uniform file-like interface.

**Architecture:** URLHandler gets `open(url, mode) -> BinaryIO | TextIO` as its core method. FormatHandler shifts from `Path` to `BinaryIO` streams. A new `LocalFileHandler` makes even local paths go through the plugin system. Cloud handlers (GCS, S3/R2) become optional extras. The CLI's GCS upload logic moves into a `packaging.py` library module that uses URLHandler for uploads. `requests` is replaced by `urllib.request`.

**Tech Stack:** Python 3.12+ typing (`BinaryIO`, `TextIO`, `Literal`, `overload`), `urllib.request`, `io` module, `google-cloud-storage` (optional), `boto3` (optional)

---

### Task 1: Update URLHandler protocol to stream-based `open()`

**Files:**
- Modify: `src/sunstone/plugins.py:22-42` (URLHandler protocol)
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Write failing test for new URLHandler protocol**

In `tests/test_plugins.py`, replace `FakeURLHandler` and add a test for the new protocol shape:

```python
class FakeURLHandler:
    def can_handle(self, url):
        return url.startswith("fake://")

    def open(self, url, mode="rb"):
        import io
        if "b" in mode:
            return io.BytesIO(b"col1,col2\na,b\n")
        else:
            return io.StringIO("col1,col2\na,b\n")


def test_url_handler_structural_typing():
    assert isinstance(FakeURLHandler(), URLHandler)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py::test_url_handler_structural_typing -v`
Expected: FAIL — FakeURLHandler has `open()` but protocol still expects `fetch()`

- [ ] **Step 3: Update URLHandler protocol in plugins.py**

Replace the URLHandler protocol definition in `src/sunstone/plugins.py`:

```python
from typing import BinaryIO, Literal, TextIO, Protocol, overload, runtime_checkable

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

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        """Open a URL for reading or writing. Returns a file-like object."""
        ...
```

- [ ] **Step 4: Add `fetch()` convenience method to PluginRegistry**

In `src/sunstone/plugins.py`, add to PluginRegistry:

```python
import builtins
import shutil

class PluginRegistry:
    # ... existing methods ...

    def fetch(self, url: str, dest: Path) -> Path:
        """Convenience: download url to local file via open()."""
        handler = self.find_url_handler(url)
        if handler is None:
            raise ValueError(f"No URL handler found for: {url}")
        with handler.open(url, "rb") as src, builtins.open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return dest
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_plugins.py::test_url_handler_structural_typing -v`
Expected: PASS

- [ ] **Step 6: Write test for PluginRegistry.fetch() convenience**

```python
def test_registry_fetch_convenience(tmp_path):
    registry = PluginRegistry()
    registry._url_handlers.append(FakeURLHandler())

    dest = tmp_path / "out.csv"
    result = registry.fetch("fake://data.csv", dest)
    assert result == dest
    assert dest.read_bytes() == b"col1,col2\na,b\n"


def test_registry_fetch_no_handler():
    registry = PluginRegistry()
    with pytest.raises(ValueError, match="No URL handler found"):
        registry.fetch("unknown://data.csv", Path("/tmp/out"))
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_plugins.py::test_registry_fetch_convenience tests/test_plugins.py::test_registry_fetch_no_handler -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Change URLHandler protocol to stream-based open()"
```

---

### Task 2: Update FormatHandler protocol to stream-based IO

**Files:**
- Modify: `src/sunstone/plugins.py:44-62` (FormatHandler protocol)
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Update FakeFormatHandler and write failing test**

In `tests/test_plugins.py`, update the fake handlers to use streams:

```python
class FakeFormatHandler:
    def can_read(self, path, format):
        return str(path).endswith(".fake")

    def read(self, stream, **kwargs):
        import io
        return pd.read_csv(stream)

    def can_write(self, path, format):
        return str(path).endswith(".fake")

    def write(self, df, stream, **kwargs):
        df.to_csv(stream)


class PartialFormatHandler:
    """Only implements read, not write."""

    def can_read(self, path, format):
        return True

    def read(self, stream, **kwargs):
        return pd.DataFrame()


def test_format_handler_structural_typing():
    assert isinstance(FakeFormatHandler(), FormatHandler)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py::test_format_handler_structural_typing -v`
Expected: FAIL — protocol still expects `Path` parameters

- [ ] **Step 3: Update FormatHandler protocol in plugins.py**

Replace the FormatHandler protocol definition:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugins.py::test_format_handler_structural_typing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "Change FormatHandler protocol to use BinaryIO streams"
```

---

### Task 3: Implement LocalFileHandler

**Files:**
- Modify: `src/sunstone/handlers.py` (add LocalFileHandler)
- Test: `tests/test_handlers.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_handlers.py`:

```python
from sunstone.handlers import LocalFileHandler


@pytest.fixture
def local_handler():
    return LocalFileHandler()


class TestLocalFileHandlerCanHandle:
    def test_bare_relative_path(self, local_handler):
        assert local_handler.can_handle("data.csv")

    def test_bare_absolute_path(self, local_handler):
        assert local_handler.can_handle("/tmp/data.csv")

    def test_file_scheme(self, local_handler):
        assert local_handler.can_handle("file:///tmp/data.csv")

    def test_http_scheme(self, local_handler):
        assert not local_handler.can_handle("http://example.com/data.csv")

    def test_gs_scheme(self, local_handler):
        assert not local_handler.can_handle("gs://bucket/data.csv")

    def test_s3_scheme(self, local_handler):
        assert not local_handler.can_handle("s3://bucket/data.csv")

    def test_r2_scheme(self, local_handler):
        assert not local_handler.can_handle("r2://bucket/data.csv")


class TestLocalFileHandlerOpen:
    def test_read_binary(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_bytes(b"a,b\n1,2\n")
        with local_handler.open(str(f), "rb") as stream:
            assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        with local_handler.open(str(f), "r") as stream:
            assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, local_handler, tmp_path):
        f = tmp_path / "out.csv"
        with local_handler.open(str(f), "wb") as stream:
            stream.write(b"a,b\n1,2\n")
        assert f.read_bytes() == b"a,b\n1,2\n"

    def test_write_text(self, local_handler, tmp_path):
        f = tmp_path / "out.csv"
        with local_handler.open(str(f), "w") as stream:
            stream.write("a,b\n1,2\n")
        assert f.read_text() == "a,b\n1,2\n"

    def test_file_scheme(self, local_handler, tmp_path):
        f = tmp_path / "data.csv"
        f.write_bytes(b"a,b\n1,2\n")
        with local_handler.open(f"file://{f}", "rb") as stream:
            assert stream.read() == b"a,b\n1,2\n"

    def test_creates_parent_dirs_on_write(self, local_handler, tmp_path):
        f = tmp_path / "sub" / "dir" / "out.csv"
        with local_handler.open(str(f), "wb") as stream:
            stream.write(b"data")
        assert f.read_bytes() == b"data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestLocalFileHandlerCanHandle tests/test_handlers.py::TestLocalFileHandlerOpen -v`
Expected: FAIL — LocalFileHandler doesn't exist yet

- [ ] **Step 3: Implement LocalFileHandler**

Add to `src/sunstone/handlers.py`:

```python
import builtins
from typing import BinaryIO, TextIO
from urllib.parse import urlparse


_REMOTE_SCHEMES = {"http", "https", "gs", "s3", "r2"}


class LocalFileHandler:
    """Handles local filesystem paths and file:// URLs."""

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("", "file") and parsed.scheme not in _REMOTE_SCHEMES

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = Path(parsed.path)
        else:
            path = Path(url)

        if "w" in mode:
            path.parent.mkdir(parents=True, exist_ok=True)

        return builtins.open(path, mode)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestLocalFileHandlerCanHandle tests/test_handlers.py::TestLocalFileHandlerOpen -v`
Expected: PASS

- [ ] **Step 5: Register LocalFileHandler as last fallback in PluginRegistry._discover()**

In `src/sunstone/plugins.py`, update `_discover()`:

```python
def _discover(self) -> None:
    """Load plugins from entry points, then register internal handlers."""
    for ep in _get_entry_points():
        try:
            plugin_cls = ep.load()
            config = _load_plugin_config(ep.name)
            plugin = plugin_cls(config) if config else plugin_cls()
            self._register(ep.name, plugin)
        except Exception:
            logger.exception("Failed to load plugin '%s'", ep.name)

    from .handlers import BuiltinFormatHandler, HttpURLHandler, LocalFileHandler

    self._format_handlers.append(BuiltinFormatHandler())
    self._url_handlers.append(HttpURLHandler())
    self._url_handlers.append(LocalFileHandler())  # last fallback
```

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers.py src/sunstone/plugins.py tests/test_handlers.py
git commit -m "Add LocalFileHandler for local paths and file:// URLs"
```

---

### Task 4: Refactor BuiltinFormatHandler to use streams

**Files:**
- Modify: `src/sunstone/handlers.py:44-69` (BuiltinFormatHandler)
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Update tests to use streams**

Replace the read/write test classes in `tests/test_handlers.py`:

```python
import io


class TestBuiltinFormatHandlerCanRead:
    def test_csv(self, handler):
        assert handler.can_read("data.csv", None)

    def test_csv_with_format(self, handler):
        assert handler.can_read("data.whatever", "csv")

    def test_json(self, handler):
        assert handler.can_read("data.json", None)

    def test_excel_xlsx(self, handler):
        assert handler.can_read("data.xlsx", None)

    def test_excel_xls(self, handler):
        assert handler.can_read("data.xls", None)

    def test_parquet(self, handler):
        assert handler.can_read("data.parquet", None)

    def test_tsv(self, handler):
        assert handler.can_read("data.tsv", None)

    def test_txt_as_tsv(self, handler):
        assert handler.can_read("data.txt", None)

    def test_unknown_extension(self, handler):
        assert not handler.can_read("data.hdf5", None)

    def test_unknown_format_string(self, handler):
        assert not handler.can_read("data.whatever", "hdf5")

    def test_url_path(self, handler):
        assert handler.can_read("gs://bucket/data.csv", None)

    def test_url_path_with_format(self, handler):
        assert handler.can_read("gs://bucket/data.whatever", "csv")


class TestBuiltinFormatHandlerCanWrite:
    def test_csv(self, handler):
        assert handler.can_write("data.csv", None)

    def test_csv_with_format(self, handler):
        assert handler.can_write("data.whatever", "csv")

    def test_unknown(self, handler):
        assert not handler.can_write("data.hdf5", None)


class TestBuiltinFormatHandlerRead:
    def test_read_csv(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_tsv(self, handler):
        stream = io.BytesIO(b"a\tb\n1\t2\n3\t4\n")
        df = handler.read(stream, sep="\t")
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 2

    def test_read_json(self, handler):
        stream = io.BytesIO(b'[{"a": 1, "b": 2}]')
        df = handler.read(stream)
        assert list(df.columns) == ["a", "b"]

    def test_read_parquet(self, handler, tmp_path):
        # Parquet needs real bytes, create via file
        f = tmp_path / "data.parquet"
        pd.DataFrame({"a": [1], "b": [2]}).to_parquet(f)
        stream = io.BytesIO(f.read_bytes())
        df = handler.read(stream)
        assert list(df.columns) == ["a", "b"]

    def test_read_passes_kwargs(self, handler):
        stream = io.BytesIO(b"a,b\n1,2\n3,4\n")
        df = handler.read(stream, usecols=["a"])
        assert list(df.columns) == ["a"]


class TestBuiltinFormatHandlerWrite:
    def test_write_csv(self, handler):
        stream = io.BytesIO()
        df = pd.DataFrame({"x": [1, 2]})
        handler.write(df, stream, index=False)
        stream.seek(0)
        result = pd.read_csv(stream)
        assert list(result.columns) == ["x"]
        assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestBuiltinFormatHandlerRead tests/test_handlers.py::TestBuiltinFormatHandlerWrite -v`
Expected: FAIL — handler still expects Path, not stream

- [ ] **Step 3: Refactor BuiltinFormatHandler**

Note: `can_read`/`can_write` now take a `str` (path or URL) for extension detection. `read`/`write` take `BinaryIO` streams. The handler needs to know the format for `read()` — this is passed via a `format` kwarg or stored when `can_read` is called. Simplest approach: `read()` receives a `format` kwarg from the caller (the pipeline in dataframe.py).

Actually, the cleaner design: `BuiltinFormatHandler` stores the resolved format from `can_read`/`can_write` as instance state. But since the registry might call `can_read` and then `read` on the same instance, this creates coupling. Better: the pipeline passes format explicitly, or the handler re-resolves from a path string.

Simplest: add an optional `format` kwarg to `read()` and `write()` and pass the path string so the handler can re-resolve:

```python
from typing import BinaryIO
from pathlib import PurePosixPath
from urllib.parse import urlparse


class BuiltinFormatHandler:
    """Handles CSV, JSON, Excel, Parquet, and TSV formats using pandas."""

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        """Resolve a format string from explicit format or file extension."""
        if format is not None:
            return format if format in _READER_MAP or format in _WRITER_MAP else None
        # Extract extension from path or URL
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        suffix = PurePosixPath(file_path).suffix.lower()
        return _EXTENSION_MAP.get(suffix)

    def can_read(self, path: str, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _READER_MAP

    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame:
        # The caller must pass format= or path= so we know which reader to use.
        # Convention: pipeline passes format= when calling read().
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"  # safe default for BinaryIO
        reader = _READER_MAP[fmt]
        return reader(stream, **kwargs)

    def can_write(self, path: str, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _WRITER_MAP

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"
        method_name = _WRITER_MAP[fmt]
        writer = getattr(df, method_name)
        writer(stream, **kwargs)
```

Also update the `_READER_MAP` to remove the old tsv lambda (since TSV is now just `pd.read_csv` with `sep="\t"` passed by the caller or by the pipeline):

Actually, keep TSV in the reader map — it's cleaner:

```python
_READER_MAP: dict[str, Callable[..., pd.DataFrame]] = {
    "csv": pd.read_csv,
    "json": pd.read_json,
    "excel": pd.read_excel,
    "parquet": pd.read_parquet,
    "tsv": lambda stream, **kw: pd.read_csv(stream, sep="\t", **kw),
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestBuiltinFormatHandlerCanRead tests/test_handlers.py::TestBuiltinFormatHandlerCanWrite tests/test_handlers.py::TestBuiltinFormatHandlerRead tests/test_handlers.py::TestBuiltinFormatHandlerWrite -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "Refactor BuiltinFormatHandler to use BinaryIO streams"
```

---

### Task 5: Refactor HttpURLHandler to use `urllib.request` and `open()`

**Files:**
- Modify: `src/sunstone/handlers.py:72-175` (HttpURLHandler)
- Modify: `tests/test_handlers.py`

- [ ] **Step 1: Write new tests for stream-based HttpURLHandler**

Replace `TestHttpURLHandlerFetch` in `tests/test_handlers.py`:

```python
import io
from urllib.error import HTTPError


class TestHttpURLHandlerOpen:
    def test_read_binary(self, http_handler):
        mock_response = MagicMock()
        mock_response.read.return_value = b"a,b\n1,2\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", return_value=mock_response),
        ):
            stream = http_handler.open("https://example.com/data.csv", "rb")
            assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, http_handler):
        mock_response = MagicMock()
        mock_response.read.return_value = b"a,b\n1,2\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", return_value=mock_response),
        ):
            stream = http_handler.open("https://example.com/data.csv", "r")
            assert stream.read() == "a,b\n1,2\n"

    def test_write_raises(self, http_handler):
        with pytest.raises(NotImplementedError):
            http_handler.open("https://example.com/data.csv", "wb")

    def test_rejects_private_url(self, http_handler):
        with patch("sunstone.handlers._is_public_url", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                http_handler.open("http://192.168.1.1/data.csv", "rb")

    def test_strips_auth_on_cross_origin_redirect(self, http_handler):
        # First request returns redirect
        redirect_error = HTTPError(
            "https://example.com/data.csv", 302, "Redirect",
            {"Location": "https://other.com/data.csv"}, io.BytesIO(b"")
        )
        final_response = MagicMock()
        final_response.read.return_value = b"data"
        final_response.__enter__ = MagicMock(return_value=final_response)
        final_response.__exit__ = MagicMock(return_value=False)

        http_handler.headers = {"Authorization": "Bearer secret"}

        with (
            patch("sunstone.handlers._is_public_url", return_value=True),
            patch("sunstone.handlers.urlopen", side_effect=[redirect_error, final_response]) as mock_urlopen,
        ):
            http_handler.open("https://example.com/data.csv", "rb")
            second_call = mock_urlopen.call_args_list[1]
            request = second_call[0][0]
            assert "Authorization" not in request.headers
```

Note: The redirect handling with `urllib` differs from `requests` — we'll use a custom opener with redirect handling disabled, or handle `HTTPError` for redirects. The implementation will clarify the exact mock shape. Tests may need minor adjustments during implementation.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestHttpURLHandlerOpen -v`
Expected: FAIL

- [ ] **Step 3: Implement stream-based HttpURLHandler**

Replace HttpURLHandler in `src/sunstone/handlers.py`:

```python
import io
from typing import BinaryIO, TextIO
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class HttpURLHandler:
    """Fetches datasets from HTTP/HTTPS URLs with SSRF protection."""

    def __init__(self, timeout: int = 30, max_redirects: int = 10) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.headers: dict[str, str] = {}

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        if "w" in mode:
            raise NotImplementedError(
                "HTTP write is not supported. Use a cloud storage handler (gs://, s3://) for uploads."
            )

        if not _is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to "
                "public internet addresses are permitted."
            )

        logger.info("Fetching dataset from URL: %s", url)

        current_url = url
        current_headers = dict(self.headers)
        redirect_count = 0

        while redirect_count <= self.max_redirects:
            request = Request(current_url, headers=current_headers)
            try:
                response = urlopen(request, timeout=self.timeout)  # noqa: S310
                break
            except HTTPError as e:
                if e.status in (301, 302, 303, 307, 308):
                    redirect_url = e.headers.get("Location")
                    if not redirect_url:
                        raise ValueError("Redirect response without Location header") from e

                    redirect_url = urljoin(current_url, redirect_url)

                    if not _is_public_url(redirect_url):
                        raise ValueError(
                            f"Redirect URL '{redirect_url}' is not allowed. Only HTTP/HTTPS URLs "
                            "pointing to public internet addresses are permitted."
                        ) from e

                    # Strip auth headers on cross-origin redirects
                    redirect_parsed = urlparse(redirect_url)
                    original_parsed = urlparse(url)
                    if (redirect_parsed.scheme != original_parsed.scheme
                            or redirect_parsed.netloc != original_parsed.netloc):
                        current_headers = {
                            k: v for k, v in current_headers.items()
                            if k.lower() != "authorization"
                        }

                    logger.info("Following redirect to: %s", redirect_url)
                    current_url = redirect_url
                    redirect_count += 1
                else:
                    raise
        else:
            raise ValueError(f"Too many redirects (max: {self.max_redirects})")

        data = response.read()
        logger.info("Fetched %d bytes from %s", len(data), current_url)

        if "b" in mode:
            return io.BytesIO(data)
        else:
            return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
```

Also add `from urllib.error import HTTPError` to the imports and remove `import requests`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestHttpURLHandlerOpen tests/test_handlers.py::TestHttpURLHandlerCanHandle -v`
Expected: PASS (may need to adjust mocks for urllib vs requests patterns — fix as needed)

- [ ] **Step 5: Update the auth integration test**

Update `test_fetch_from_url_delegates_auth_to_http_handler` in `tests/test_handlers.py` to use the new `open()` and `registry.fetch()` flow:

```python
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
    from sunstone.plugins import PluginRegistry

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_slug("test-dataset")

    class TestAuth:
        def authenticate(self, url, headers, dataset):
            headers["Authorization"] = "Bearer test-token"
            return headers

    handler = HttpURLHandler()
    registry = PluginRegistry()
    registry._auth_providers.append(TestAuth())
    registry._url_handlers.append(handler)

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        patch("sunstone.handlers._is_public_url", return_value=True),
        patch("sunstone.handlers.urlopen") as mock_urlopen,
    ):
        mock_response = MagicMock()
        mock_response.read.return_value = b"col1,col2\na,b\n"
        mock_urlopen.return_value = mock_response

        manager.fetch_from_url(dataset, force=True)

        request_obj = mock_urlopen.call_args[0][0]
        assert request_obj.get_header("Authorization") == "Bearer test-token"
```

- [ ] **Step 6: Run all handler tests**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/sunstone/handlers.py tests/test_handlers.py
git commit -m "Refactor HttpURLHandler to use urllib.request and open()"
```

---

### Task 6: Update fetch_from_url to use registry.fetch()

**Files:**
- Modify: `src/sunstone/datasets.py:656-708`
- Test: `tests/test_datasets.py`

- [ ] **Step 1: Write test for deprecated fetch_from_url using registry.fetch()**

Check existing tests in `tests/test_datasets.py` that call `fetch_from_url`. Update them to work with the new flow if needed. Add a deprecation test:

```python
import warnings

def test_fetch_from_url_emits_deprecation_warning(tmp_path):
    """fetch_from_url should emit a DeprecationWarning."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Test\n"
        "    slug: test\n"
        "    location: inputs/test.csv\n"
        "    source:\n"
        "      name: Source\n"
        "      location:\n"
        "        data: https://example.com/test.csv\n"
        "      attributedTo: Org\n"
        "      acquiredAt: '2026-01-01'\n"
        "      acquisitionMethod: manual-download\n"
        "      license: CC-BY-4.0\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()

    from sunstone.datasets import DatasetsManager
    from sunstone.plugins import PluginRegistry

    manager = DatasetsManager(tmp_path)
    dataset = manager.find_dataset_by_slug("test")

    registry = PluginRegistry()
    mock_handler = MagicMock()
    mock_handler.can_handle.return_value = True
    mock_handler.open.return_value = io.BytesIO(b"data")
    registry._url_handlers.append(mock_handler)

    with (
        patch.object(PluginRegistry, "get", return_value=registry),
        warnings.catch_warnings(record=True) as w,
    ):
        warnings.simplefilter("always")
        manager.fetch_from_url(dataset, force=True)
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
```

- [ ] **Step 2: Refactor fetch_from_url**

Replace the body of `fetch_from_url` in `src/sunstone/datasets.py`:

```python
import warnings

def fetch_from_url(
    self,
    dataset: DatasetMetadata,
    timeout: int = 30,
    force: bool = False,
    max_redirects: int = 10,
) -> Path:
    """Fetch a dataset from its source URL. Deprecated: use PluginRegistry.fetch() directly."""
    warnings.warn(
        "fetch_from_url is deprecated. Use PluginRegistry.get().fetch(url, dest) instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    if not dataset.source or not dataset.source.location.data:
        raise ValueError(f"Dataset '{dataset.slug}' has no source URL")

    local_path = self.get_absolute_path(dataset.location)

    if local_path.exists() and not force:
        logger.info("Using existing local file: %s", local_path)
        return local_path

    url = dataset.source.location.data

    from .plugins import PluginRegistry

    registry = PluginRegistry.get()

    # Inject auth into the URL handler if applicable
    url_handler = registry.find_url_handler(url)
    if url_handler is None:
        raise ValueError(f"No URL handler found for '{url}'.")

    if hasattr(url_handler, "headers"):
        for auth in registry.get_auth_providers():
            url_handler.headers = auth.authenticate(url, url_handler.headers, dataset)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    return registry.fetch(url, local_path)
```

- [ ] **Step 3: Remove unused imports from datasets.py**

Remove `import requests`, `import ipaddress`, `import socket`, `from urllib.parse import urljoin, urlparse` if no longer used elsewhere in the file. Check carefully before removing.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_datasets.py tests/test_handlers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/datasets.py tests/test_datasets.py
git commit -m "Deprecate fetch_from_url, delegate to registry.fetch()"
```

---

### Task 7: Update dataframe.py read pipeline to use streams

**Files:**
- Modify: `src/sunstone/dataframe.py` (read_dataset, read_csv, read_excel)
- Test: `tests/test_plugins.py`, `tests/test_dataframe.py`

- [ ] **Step 1: Write test for stream-based read pipeline**

Add to `tests/test_plugins.py`:

```python
def test_read_dataset_uses_stream_pipeline(tmp_path):
    """read_dataset should open a stream via URLHandler and pass to FormatHandler."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs:\n"
        "  - name: Test\n"
        "    slug: test\n"
        "    location: inputs/test.csv\n"
        "outputs: []\n"
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "test.csv").write_text("a,b\n1,2\n")

    df = DataFrame.read_dataset("test", project_path=tmp_path)
    assert list(df.data.columns) == ["a", "b"]
    assert len(df.data) == 1
```

This test should already pass with the current code, but serves as a regression test. The real validation is that the internal flow uses `handler.open()` → `format_handler.read(stream)`.

- [ ] **Step 2: Update read_dataset to use stream pipeline**

In `src/sunstone/dataframe.py`, update the read_dataset method's format handling section (around line 160-176):

```python
        # Open stream via URL handler and read via format handler
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()

        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, format)

        if format_handler is None:
            extension = absolute_path.suffix.lower()
            raise ValueError(
                f"No format handler found for '{absolute_path.name}'"
                + (f" (format='{format}')" if format else f" (extension='{extension}')")
                + ". Install a plugin or check the file extension."
            )

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            raise ValueError(f"No URL handler found for '{location}'")

        with url_handler.open(location, "rb") as stream:
            df = format_handler.read(stream, format=format, path=location, **kwargs)
```

- [ ] **Step 3: Update read_csv by-path branch similarly**

In the file-path branch of `read_csv` (around line 277-284):

```python
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        location = str(absolute_path)
        format_handler = registry.find_format_reader(location, "csv")
        if format_handler is None:
            raise ValueError("No format handler found for CSV files")

        url_handler = registry.find_url_handler(location)
        if url_handler is None:
            raise ValueError(f"No URL handler found for '{location}'")

        with url_handler.open(location, "rb") as stream:
            df = format_handler.read(stream, format="csv", path=location, **kwargs)
```

- [ ] **Step 4: Update read_excel by-path branch similarly**

Same pattern as read_csv, with `"excel"` format.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/dataframe.py
git commit -m "Update read pipeline to use URL handler streams"
```

---

### Task 8: Update dataframe.py write pipeline to use streams

**Files:**
- Modify: `src/sunstone/dataframe.py` (to_csv)
- Test: `tests/test_dataframe.py`

- [ ] **Step 1: Write test for stream-based write**

Add to `tests/test_dataframe.py` or `tests/test_plugins.py`:

```python
def test_to_csv_uses_stream_pipeline(tmp_path):
    """to_csv should open a stream via URLHandler and pass to FormatHandler."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text("inputs: []\noutputs: []\n")

    df = DataFrame(
        data=pd.DataFrame({"a": [1, 2]}),
        project_path=tmp_path,
    )
    df.to_csv("outputs/test.csv", slug="test", name="Test", index=False)
    result = pd.read_csv(tmp_path / "outputs" / "test.csv")
    assert list(result.columns) == ["a"]
    assert len(result) == 2
```

- [ ] **Step 2: Update to_csv tracked write path**

In `src/sunstone/dataframe.py`, replace the write section (around line 477-490):

```python
        # Write the data via URL handler + format handler
        from .plugins import PluginRegistry

        registry = PluginRegistry.get()
        location = str(absolute_path)

        url_handler = registry.find_url_handler(location)
        format_writer = registry.find_format_writer(location, None)

        if url_handler and format_writer:
            with url_handler.open(location, "wb") as stream:
                format_writer.write(self.data, stream, format=None, path=location, **pandas_kwargs)
        elif format_writer:
            with open(absolute_path, "wb") as stream:
                format_writer.write(self.data, stream, format=None, path=location, **pandas_kwargs)
        else:
            self.data.to_csv(absolute_path, **pandas_kwargs)
```

- [ ] **Step 3: Update to_csv untracked write path (track=False)**

Replace the untracked path (around line 445-449):

```python
        if not track:
            from .plugins import PluginRegistry

            registry = PluginRegistry.get()
            location = str(path_or_buf)

            url_handler = registry.find_url_handler(location)
            if url_handler:
                with url_handler.open(location, "wb") as stream:
                    self.data.to_csv(stream, **pandas_kwargs)
            else:
                path = Path(path_or_buf)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.data.to_csv(path, **pandas_kwargs)
            return
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/dataframe.py
git commit -m "Update write pipeline to use URL handler streams"
```

---

### Task 9: Remove `requests` dependency, add optional extras

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sunstone/handlers.py` (remove requests import if still present)

- [ ] **Step 1: Update pyproject.toml**

Remove `requests` from dependencies. Add optional extras. Move `google-cloud-storage` to optional:

```toml
dependencies = [
    "typer>=0.15",
    "frictionless>=5.18.1",
    "google-auth>=2.43.0",
    "openpyxl>=3.1.0",
    "pandas>=2.0.0",
    "pyyaml>=6.0",
    "ruamel-yaml>=0.18",
    "pyarrow>=23.0.1",
]

[project.optional-dependencies]
gcs = ["google-cloud-storage>=2.0"]
s3 = ["boto3>=1.28"]
```

- [ ] **Step 2: Verify no remaining `import requests` in source**

Run: `grep -r "import requests" src/sunstone/`
Expected: No matches

- [ ] **Step 3: Run uv sync and full test suite**

```bash
uv sync
uv run pytest tests/ -v
```

Expected: PASS (if tests mock requests, those mocks need to be updated to urllib — should already be done in Task 5)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/sunstone/handlers.py
git commit -m "Remove requests dependency, add gcs and s3 optional extras"
```

---

### Task 10: Implement GcsURLHandler

**Files:**
- Create: `src/sunstone/handlers_gcs.py`
- Test: `tests/test_handlers_gcs.py`

- [ ] **Step 1: Write tests**

Create `tests/test_handlers_gcs.py`:

```python
"""Tests for GCS URL handler (mocked — no real GCS calls)."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def gcs_handler():
    with patch.dict("sys.modules", {"google.cloud": MagicMock(), "google.cloud.storage": MagicMock()}):
        from sunstone.handlers_gcs import GcsURLHandler
        return GcsURLHandler()


class TestGcsURLHandlerCanHandle:
    def test_gs_scheme(self, gcs_handler):
        assert gcs_handler.can_handle("gs://bucket/path/data.csv")

    def test_http_scheme(self, gcs_handler):
        assert not gcs_handler.can_handle("http://example.com/data.csv")

    def test_s3_scheme(self, gcs_handler):
        assert not gcs_handler.can_handle("s3://bucket/data.csv")

    def test_local_path(self, gcs_handler):
        assert not gcs_handler.can_handle("data.csv")


class TestGcsURLHandlerOpen:
    def test_read_binary(self, gcs_handler):
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"a,b\n1,2\n"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client = MagicMock()
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/data.csv", "rb")
        assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, gcs_handler):
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"a,b\n1,2\n"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client = MagicMock()
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/data.csv", "r")
        assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, gcs_handler):
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client = MagicMock()
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/out.csv", "wb")
        stream.write(b"a,b\n1,2\n")
        stream.close()

        mock_blob.upload_from_file.assert_called_once()

    def test_write_text(self, gcs_handler):
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        gcs_handler._client = MagicMock()
        gcs_handler._client.bucket.return_value = mock_bucket

        stream = gcs_handler.open("gs://my-bucket/out.csv", "w")
        stream.write("a,b\n1,2\n")
        stream.close()

        mock_blob.upload_from_file.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers_gcs.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement GcsURLHandler**

Create `src/sunstone/handlers_gcs.py`:

```python
"""GCS URL handler. Requires google-cloud-storage (install with sunstone-py[gcs])."""

from __future__ import annotations

import io
import logging
from typing import BinaryIO, TextIO
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class _GcsWriteStream(io.BytesIO):
    """A BytesIO that uploads to GCS on close()."""

    def __init__(self, blob: object) -> None:
        super().__init__()
        self._blob = blob

    def close(self) -> None:
        if not self.closed:
            self.seek(0)
            self._blob.upload_from_file(self)  # type: ignore[union-attr]
        super().close()


class GcsURLHandler:
    """Handles gs:// URLs using google-cloud-storage."""

    def __init__(self, config: dict | None = None) -> None:
        from google.cloud import storage  # type: ignore[import-untyped]

        self._client = storage.Client()

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme == "gs"

    def _get_blob(self, url: str) -> object:
        parsed = urlparse(url)
        bucket = self._client.bucket(parsed.netloc)
        blob_path = parsed.path.lstrip("/")
        return bucket.blob(blob_path)

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        blob = self._get_blob(url)

        if "w" in mode:
            stream = _GcsWriteStream(blob)
            if "b" not in mode:
                return io.TextIOWrapper(stream, encoding="utf-8")
            return stream

        data = blob.download_as_bytes()
        logger.info("Downloaded %d bytes from %s", len(data), url)
        binary_stream = io.BytesIO(data)

        if "b" in mode:
            return binary_stream
        return io.TextIOWrapper(binary_stream, encoding="utf-8")
```

- [ ] **Step 4: Register GcsURLHandler in PluginRegistry._discover()**

In `src/sunstone/plugins.py`, add conditional registration in `_discover()`:

```python
        # Optional cloud handlers
        try:
            from .handlers_gcs import GcsURLHandler
            self._url_handlers.append(GcsURLHandler())
        except ImportError:
            pass  # google-cloud-storage not installed
```

Add this before the LocalFileHandler registration (cloud handlers should have higher priority than local fallback).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_handlers_gcs.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers_gcs.py src/sunstone/plugins.py tests/test_handlers_gcs.py
git commit -m "Add GcsURLHandler for gs:// URLs with optional gcs extra"
```

---

### Task 11: Implement S3URLHandler (covers S3 and R2)

**Files:**
- Create: `src/sunstone/handlers_s3.py`
- Test: `tests/test_handlers_s3.py`

- [ ] **Step 1: Write tests**

Create `tests/test_handlers_s3.py`:

```python
"""Tests for S3/R2 URL handler (mocked — no real AWS calls)."""

import io
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def s3_handler():
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        from sunstone.handlers_s3 import S3URLHandler
        return S3URLHandler()


@pytest.fixture
def r2_handler():
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        from sunstone.handlers_s3 import S3URLHandler
        return S3URLHandler(config={"endpoint_url": "https://abc123.r2.cloudflarestorage.com"})


class TestS3URLHandlerCanHandle:
    def test_s3_scheme(self, s3_handler):
        assert s3_handler.can_handle("s3://bucket/data.csv")

    def test_r2_scheme(self, s3_handler):
        assert s3_handler.can_handle("r2://bucket/data.csv")

    def test_gs_scheme(self, s3_handler):
        assert not s3_handler.can_handle("gs://bucket/data.csv")

    def test_http_scheme(self, s3_handler):
        assert not s3_handler.can_handle("http://example.com/data.csv")


class TestS3URLHandlerOpen:
    def test_read_binary(self, s3_handler):
        mock_body = MagicMock()
        mock_body.read.return_value = b"a,b\n1,2\n"
        s3_handler._client = MagicMock()
        s3_handler._client.get_object.return_value = {"Body": mock_body}

        stream = s3_handler.open("s3://my-bucket/data.csv", "rb")
        assert stream.read() == b"a,b\n1,2\n"

    def test_read_text(self, s3_handler):
        mock_body = MagicMock()
        mock_body.read.return_value = b"a,b\n1,2\n"
        s3_handler._client = MagicMock()
        s3_handler._client.get_object.return_value = {"Body": mock_body}

        stream = s3_handler.open("s3://my-bucket/data.csv", "r")
        assert stream.read() == "a,b\n1,2\n"

    def test_write_binary(self, s3_handler):
        s3_handler._client = MagicMock()

        stream = s3_handler.open("s3://my-bucket/out.csv", "wb")
        stream.write(b"a,b\n1,2\n")
        stream.close()

        s3_handler._client.upload_fileobj.assert_called_once()

    def test_r2_uses_s3_scheme_internally(self, r2_handler):
        """r2:// URLs should be converted to s3:// bucket/key internally."""
        mock_body = MagicMock()
        mock_body.read.return_value = b"data"
        r2_handler._client = MagicMock()
        r2_handler._client.get_object.return_value = {"Body": mock_body}

        r2_handler.open("r2://my-bucket/data.csv", "rb")
        r2_handler._client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="data.csv"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers_s3.py -v`
Expected: FAIL

- [ ] **Step 3: Implement S3URLHandler**

Create `src/sunstone/handlers_s3.py`:

```python
"""S3/R2 URL handler. Requires boto3 (install with sunstone-py[s3])."""

from __future__ import annotations

import io
import logging
from typing import BinaryIO, TextIO
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class _S3WriteStream(io.BytesIO):
    """A BytesIO that uploads to S3 on close()."""

    def __init__(self, client: object, bucket: str, key: str) -> None:
        super().__init__()
        self._client = client
        self._bucket = bucket
        self._key = key

    def close(self) -> None:
        if not self.closed:
            self.seek(0)
            self._client.upload_fileobj(self, self._bucket, self._key)  # type: ignore[union-attr]
        super().close()


class S3URLHandler:
    """Handles s3:// and r2:// URLs using boto3."""

    def __init__(self, config: dict | None = None) -> None:
        import boto3  # type: ignore[import-untyped]

        config = config or {}
        endpoint_url = config.get("endpoint_url")
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme in ("s3", "r2")

    def _parse_url(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        return bucket, key

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        bucket, key = self._parse_url(url)

        if "w" in mode:
            stream = _S3WriteStream(self._client, bucket, key)
            if "b" not in mode:
                return io.TextIOWrapper(stream, encoding="utf-8")
            return stream

        response = self._client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        logger.info("Downloaded %d bytes from %s", len(data), url)
        binary_stream = io.BytesIO(data)

        if "b" in mode:
            return binary_stream
        return io.TextIOWrapper(binary_stream, encoding="utf-8")
```

- [ ] **Step 4: Register S3URLHandler in PluginRegistry._discover()**

In `src/sunstone/plugins.py`, add conditional registration:

```python
        try:
            from .handlers_s3 import S3URLHandler
            s3_config = _load_plugin_config("s3")
            self._url_handlers.append(S3URLHandler(config=s3_config))
        except ImportError:
            pass  # boto3 not installed
```

Add this after GcsURLHandler and before LocalFileHandler.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_handlers_s3.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/handlers_s3.py src/sunstone/plugins.py tests/test_handlers_s3.py
git commit -m "Add S3URLHandler for s3:// and r2:// URLs with optional s3 extra"
```

---

### Task 12: Extract packaging library from CLI

**Files:**
- Create: `src/sunstone/packaging.py`
- Modify: `src/sunstone/cli.py`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Write tests for packaging library functions**

Create `tests/test_packaging.py`:

```python
"""Tests for packaging library functions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sunstone.datasets import DatasetsManager


def test_push_datapackage_uses_url_handler(tmp_path):
    """push_datapackage should use URLHandler for uploads."""
    datasets_yaml = tmp_path / "datasets.yaml"
    datasets_yaml.write_text(
        "inputs: []\n"
        "outputs:\n"
        "  - name: Test Output\n"
        "    slug: test-output\n"
        "    location: outputs/data.csv\n"
        "    publish:\n"
        "      enabled: true\n"
        "      to: gs://test-bucket/\n"
    )
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "data.csv").write_text("a,b\n1,2\n")

    from sunstone.packaging import push_datapackage
    from sunstone.plugins import PluginRegistry

    mock_handler = MagicMock()
    mock_handler.can_handle.return_value = True
    mock_stream = MagicMock()
    mock_handler.open.return_value.__enter__ = MagicMock(return_value=mock_stream)
    mock_handler.open.return_value.__exit__ = MagicMock(return_value=False)

    registry = PluginRegistry()
    registry._url_handlers.append(mock_handler)

    with patch.object(PluginRegistry, "get", return_value=registry):
        push_datapackage(project_path=tmp_path)

    assert mock_handler.open.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Extract packaging functions from cli.py**

Create `src/sunstone/packaging.py` with the core logic extracted from `push_group_to_gcs` and `package_build`, rewritten to use URLHandler:

```python
"""Library functions for building and pushing data packages."""

from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .datasets import DatasetsManager, DatasetMetadata, PublishConfig
from .plugins import PluginRegistry

logger = logging.getLogger(__name__)


def is_lfs_pointer(file_path: Path) -> bool:
    """Check if a file is a Git LFS pointer."""
    try:
        if file_path.stat().st_size > 1024:
            return False
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content.startswith("version https://git-lfs.github.com/spec/v1\n")
    except (OSError, UnicodeDecodeError):
        return False


def push_group(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
    build_resource_dict_fn: Any,
    package_metadata_fn: Any,
    rdf_prefixes: dict[str, str],
    top_level_props: dict[str, Any],
    methodology_files: list[tuple[Path, str]],
) -> list[str]:
    """
    Push a group of datasets to a remote destination via URLHandler.

    Returns list of uploaded paths for reporting.
    """
    registry = PluginRegistry.get()
    uploaded: list[str] = []

    # Resolve datapackage.json path
    if not dest_url.endswith(".json"):
        if not dest_url.endswith("/"):
            dest_url += "/"
        datapackage_url = dest_url + "datapackage.json"
    else:
        datapackage_url = dest_url

    parsed = urlparse(datapackage_url)
    base_dir = str(PurePosixPath(parsed.path.lstrip("/")).parent)
    if base_dir and base_dir != ".":
        base_dir = base_dir + "/"
    else:
        base_dir = ""

    resources = []
    data_files: list[tuple[Path, str, str]] = []

    for ds in datasets:
        resource_dict = build_resource_dict_fn(ds, manager, publish_config)
        if not resource_dict:
            continue

        data_path = manager.get_absolute_path(ds.location)
        if publish_config.flatten:
            remote_path = base_dir + data_path.name
            resource_path = data_path.name
        else:
            remote_path = base_dir + ds.location
            resource_path = ds.location

        resources.append(resource_dict)
        data_files.append((data_path, remote_path, resource_path))

    if not resources:
        return []

    # Guard: check for LFS pointer files
    lfs_pointers = [rp for lp, _, rp in data_files if is_lfs_pointer(lp)]
    if lfs_pointers:
        raise ValueError(
            "Git LFS pointer files detected (run 'git lfs pull'): "
            + ", ".join(lfs_pointers)
        )

    # Build datapackage
    datapackage: dict[str, Any] = {
        "name": project_slug,
        "resources": resources,
    }

    pkg_meta = manager.get_package_metadata()
    if pkg_meta:
        datapackage.update(package_metadata_fn(pkg_meta))

    if top_level_props:
        datapackage.update(top_level_props)

    # Upload datapackage.json
    handler = registry.find_url_handler(datapackage_url)
    if handler is None:
        raise ValueError(f"No URL handler for: {datapackage_url}")

    with handler.open(datapackage_url, "w") as f:
        json.dump(datapackage, f, indent=2)
    uploaded.append(str(PurePosixPath(parsed.path.lstrip("/"))))

    # Upload data files
    for local_path, remote_path, resource_path in data_files:
        scheme = parsed.scheme
        remote_url = f"{scheme}://{parsed.netloc}/{remote_path}"
        file_handler = registry.find_url_handler(remote_url)
        if file_handler is None:
            raise ValueError(f"No URL handler for: {remote_url}")

        with open(local_path, "rb") as src, file_handler.open(remote_url, "wb") as dst:
            dst.write(src.read())
        uploaded.append(resource_path)

    # Upload methodology files
    for abs_path, _resolved_uri in methodology_files:
        if publish_config.flatten:
            methodology_remote = base_dir + abs_path.name
        else:
            methodology_remote = base_dir + abs_path.relative_to(manager.project_path).as_posix()
        remote_url = f"{parsed.scheme}://{parsed.netloc}/{methodology_remote}"
        meth_handler = registry.find_url_handler(remote_url)
        if meth_handler is None:
            raise ValueError(f"No URL handler for: {remote_url}")

        with open(abs_path, "rb") as src, meth_handler.open(remote_url, "wb") as dst:
            dst.write(src.read())
        uploaded.append(methodology_remote)

    return uploaded
```

- [ ] **Step 4: Update cli.py to use packaging.push_group**

Replace the body of `push_group_to_gcs` in `cli.py` to delegate to `packaging.push_group`, keeping the CLI output (typer.echo) in the CLI layer:

```python
def push_group_to_gcs(
    dest_url: str,
    datasets: list[DatasetMetadata],
    manager: DatasetsManager,
    project_slug: str,
    publish_config: PublishConfig,
) -> None:
    from .packaging import push_group

    uploaded = push_group(
        dest_url=dest_url,
        datasets=datasets,
        manager=manager,
        project_slug=project_slug,
        publish_config=publish_config,
        build_resource_dict_fn=build_resource_dict,
        package_metadata_fn=_package_metadata_to_dict,
        rdf_prefixes={**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()},
        top_level_props=expand_custom_properties(
            manager.get_top_level_custom_properties(),
            {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()},
            base_url=publish_config.as_url,
            flatten=publish_config.flatten,
        ),
        methodology_files=collect_methodology_files(
            datasets,
            manager.get_top_level_custom_properties(),
            {**STANDARD_RDF_PREFIXES, **manager.get_default_rdf_prefixes()},
            manager,
            publish_config.as_url,
        ),
    )

    for path in uploaded:
        typer.echo(f"✓ Uploaded {path}")

    parsed = urlparse(dest_url)
    typer.echo(f"✓ Package pushed to: {parsed.scheme}://{parsed.netloc}/")
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/packaging.py src/sunstone/cli.py tests/test_packaging.py
git commit -m "Extract packaging library, use URLHandler for uploads"
```

---

### Task 13: Update exports and documentation

**Files:**
- Modify: `src/sunstone/__init__.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update __init__.py exports**

Add the new handlers and packaging module to `__init__.py`:

```python
# Plugin system
from .plugins import AuthProvider, FormatHandler, PluginRegistry, URLHandler

# Import packaging for library usage
from . import packaging
```

Add `"packaging"` to `__all__`.

- [ ] **Step 2: Update CLAUDE.md package structure**

Add `handlers_gcs.py`, `handlers_s3.py`, and `packaging.py` to the tree. Add `test_handlers_gcs.py`, `test_handlers_s3.py`, and `test_packaging.py` to the tests tree.

- [ ] **Step 3: Update README.md**

Update the URLHandler protocol example in the Plugin System section to show `open()` instead of `fetch()`. Update the API reference for the new protocol signatures.

- [ ] **Step 4: Update CHANGELOG.md**

Add to `[Unreleased]`:

```markdown
- Changed: URLHandler protocol now uses `open(url, mode)` returning file-like streams instead of `fetch(url, dest)`
- Changed: FormatHandler protocol now uses `BinaryIO` streams instead of `Path`
- Added: `LocalFileHandler` for local filesystem paths and `file://` URLs
- Added: `GcsURLHandler` for `gs://` URLs (install with `sunstone-py[gcs]`)
- Added: `S3URLHandler` for `s3://` and `r2://` URLs (install with `sunstone-py[s3]`)
- Added: `sunstone.packaging` module with library functions for building and pushing data packages
- Changed: HTTP fetching uses `urllib.request` instead of `requests`
- Removed: `requests` dependency
- Changed: `google-cloud-storage` moved to optional `[gcs]` extra
- Deprecated: `DatasetsManager.fetch_from_url()` — use `PluginRegistry.get().fetch()` instead
```

- [ ] **Step 5: Run full test suite one final time**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/__init__.py CLAUDE.md README.md CHANGELOG.md
git commit -m "Update exports, docs, and changelog for stream-based plugin IO"
```
