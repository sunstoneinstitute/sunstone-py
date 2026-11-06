# Stream-Based Plugin IO Design

**Date:** 2026-04-03
**Status:** Draft
**Supersedes:** Portions of 2026-03-29-plugin-architecture-design.md (URLHandler and FormatHandler protocols)

## Problem

The plugin system introduced in v1.3.1+ handles local-file IO well but has no abstraction
for remote IO. Specific gaps:

1. **GCS upload logic is hardcoded** in `cli.py` (`push_group_to_gcs`). Adding S3 or R2
   support means editing the CLI directly.
2. **No universal file-like interface.** URLHandler only supports `fetch(url, dest) -> Path`
   (download to local file). There's no way to `open()` a remote URL and get a stream
   that works with `print(..., file=)`, `json.dump(..., f)`, or other standard Python IO.
3. **Two-step fetch-then-read** is wasteful for large files. Streaming directly from URL
   to pandas avoids the temp file.

## Design Decisions

- **Approach C (stream-first with fetch convenience):** `open()` is the core protocol
  method. `fetch()` becomes a default utility on `PluginRegistry` implemented in terms of
  `open()`. Plugin authors only implement `open()`.
- **Mirror Python's `open()` semantics:** `open(url, "rb") -> BinaryIO`,
  `open(url, "r") -> TextIO`, and write modes likewise.
- **AuthProvider stays separate.** HTTP-oriented handlers call auth providers internally.
  Cloud-native handlers (GCS, S3) use their own credential systems.
- **Optional extras for cloud dependencies:** `sunstone-py[gcs]` and `sunstone-py[s3]`.
- **Drop `requests` dependency.** `HttpURLHandler` uses `urllib.request` from the stdlib.

## Protocol Definitions

### URLHandler

```python
from typing import BinaryIO, Literal, TextIO, Protocol, overload, runtime_checkable

@runtime_checkable
class URLHandler(Protocol):
    def can_handle(self, url: str) -> bool: ...

    @overload
    def open(self, url: str, mode: Literal["r"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"]) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"]) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO: ...
```

Plugin authors implement `can_handle()` and `open()`. That's the full contract.

### FormatHandler

```python
@runtime_checkable
class FormatHandler(Protocol):
    def can_read(self, path: str, format: str | None) -> bool: ...
    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame: ...

    def can_write(self, path: str, format: str | None) -> bool: ...
    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None: ...
```

- `path` in `can_read`/`can_write` is a string (URL or path) used for format detection
  via extension sniffing. It is not the data source.
- `read()` and `write()` operate on `BinaryIO` streams.
- FormatHandler wraps with `io.TextIOWrapper` internally if the underlying pandas
  function needs text.

### AuthProvider (unchanged)

```python
@runtime_checkable
class AuthProvider(Protocol):
    def authenticate(self, url: str, headers: dict[str, str],
                     dataset: DatasetMetadata) -> dict[str, str]: ...
```

HTTP-oriented URLHandlers call `registry.get_auth_providers()` inside their `open()`
before making requests. Cloud-native handlers ignore AuthProvider and use their own
credential systems.

### PluginRegistry additions

```python
class PluginRegistry:
    # Existing methods unchanged...

    def fetch(self, url: str, dest: Path) -> Path:
        """Convenience: download url to local file via open()."""
        handler = self.find_url_handler(url)
        if handler is None:
            raise ValueError(f"No URL handler found for: {url}")
        with handler.open(url, "rb") as src, builtins.open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return dest
```

## Built-in Handlers

### LocalFileHandler (new)

Handles local filesystem paths and `file://` URLs.

- `can_handle(url)` — True for `file://` scheme and bare paths. Detection: parse with
  `urllib.parse.urlparse()`; if scheme is empty or `file`, it's local. This means relative
  paths like `outputs/data.csv` and absolute paths like `/tmp/data.csv` are both handled.
- `open(url, mode)` — returns `builtins.open(resolved_path, mode)`
- Registered as the last fallback (after all other handlers)

This is key: even local file IO goes through the plugin system. Changing a location in
`datasets.yaml` from `outputs/data.csv` to `gs://bucket/data.csv` just works.

### HttpURLHandler (refactored)

Handles `http://` and `https://` URLs. Uses `urllib.request` from the stdlib (no
`requests` dependency).

- `open(url, "rb")` — fetches URL, returns `io.BytesIO(response_body)`
- `open(url, "r")` — wraps the above with `io.TextIOWrapper`
- Write modes (`"w"`, `"wb"`) — raise `NotImplementedError` (HTTP upload semantics are
  too protocol-specific for a sensible default)
- SSRF protection: validates all URLs (including redirect targets) against private/loopback
  IPs before connecting
- Redirect handling: follows redirects manually, re-validates each target, strips
  `Authorization` header on cross-origin redirects
- Auth: calls `registry.get_auth_providers()` inside `open()` before the request

### GcsURLHandler (new, requires `[gcs]` extra)

Handles `gs://` URLs. Uses `google-cloud-storage`.

- `can_handle(url)` — True for `gs://` scheme
- `open(url, "rb")` — downloads blob into `BytesIO`, returns it
- `open(url, "wb")` — returns a `GcsWriteStream` (a `BytesIO` subclass that calls
  `blob.upload_from_file()` on `close()`)
- `open(url, "r"/"w")` — text wrappers around the binary modes
- Auth: uses Application Default Credentials via `google-cloud-storage`

Only registered if `google-cloud-storage` is importable.

### S3URLHandler (new, requires `[s3]` extra)

Handles `s3://` and `r2://` URLs. Uses `boto3`.

- `can_handle(url)` — True for `s3://` and `r2://` schemes
- For `r2://`, resolves endpoint URL from plugin config (Cloudflare account ID ->
  `https://<account_id>.r2.cloudflarestorage.com`)
- Same `open()` semantics as GcsURLHandler
- Auth: uses `boto3` default credential chain (env vars, `~/.aws/credentials`, IAM role)
- Config via cascading system: `SUNSTONE_PLUGIN_S3_ENDPOINT_URL`, etc.

Only registered if `boto3` is importable.

## pyproject.toml Changes

```toml
[project.optional-dependencies]
gcs = ["google-cloud-storage>=2.0"]
s3 = ["boto3>=1.28"]
```

`requests` is removed as a dependency. `urllib.request` from the stdlib replaces it.

## Integration Points

### Read path (dataframe.py)

`read_dataset`, `read_csv`, `read_excel` all follow this flow:

1. Resolve the location string (path or URL)
2. `registry.find_url_handler(location)` -> handler
3. `handler.open(location, "rb")` -> stream
4. `registry.find_format_reader(location, format)` -> format handler
5. `format_handler.read(stream, **kwargs)` -> DataFrame

### Write path (dataframe.py)

`to_csv` (and future `to_parquet`, etc.):

1. Resolve the location string
2. `registry.find_url_handler(location)` -> handler
3. `handler.open(location, "wb")` -> stream
4. `registry.find_format_writer(location, format)` -> format handler
5. `format_handler.write(df, stream, **kwargs)`

The `track=False` path also goes through the handler system so remote URLs work for
untracked writes too.

### fetch_from_url (datasets.py)

Becomes a thin deprecated wrapper around `registry.fetch(url, dest)`. Existing callers
keep working. Remove in a future release.

### package build/push (cli.py -> packaging.py)

Extract orchestration logic into a new `packaging.py` library module:

- `build_datapackage(project_path, ...) -> dict` — builds the datapackage.json structure
- `push_datapackage(project_path, ...) -> None` — iterates datasets, opens remote streams
  via URLHandler, writes data

The CLI becomes a thin shell calling these library functions. The actual upload calls
become `handler.open(gs_url, "wb")` writes. LFS pointer detection stays as a pre-upload
check in the orchestration logic.

`package push` flow:
1. Build datapackage.json
2. For each dataset to push:
   - Check for LFS pointer (reject if found)
   - `handler.open(remote_url, "wb")` -> stream
   - Write data to stream
3. Write datapackage.json to remote via `handler.open(remote_url, "w")`

## Migration and Backward Compatibility

### Breaking changes

Both `URLHandler` and `FormatHandler` protocols change signatures. This is acceptable
because:
- The plugin system is unreleased (all changes are in `[Unreleased]` in CHANGELOG)
- No known external plugins exist yet

### Deprecations

- `DatasetsManager.fetch_from_url()` — deprecated, calls `registry.fetch()` internally
- `requests` dependency — removed entirely

### Dependency changes

- `google-cloud-storage` moves from hard dependency to `[gcs]` extra
- `boto3` added as `[s3]` extra
- `requests` removed (replaced by `urllib.request`)

## Testing Strategy

- Unit tests for each handler with mocked IO (no real network/cloud calls)
- `HttpURLHandler`: mock `urllib.request.urlopen`, test SSRF protection, redirect
  handling, auth injection, text/binary modes
- `GcsURLHandler`: mock `google.cloud.storage.Client`, test read/write/text modes
- `S3URLHandler`: mock `boto3.client`, test S3 and R2 URL schemes, endpoint config
- `LocalFileHandler`: test with real temp files, both path formats and `file://` URLs
- Integration tests for the full read/write pipeline through PluginRegistry
- Test that `registry.fetch()` convenience works correctly
- Test that `package push` library function uses URLHandler (mock the handler)
