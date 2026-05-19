"""
Internal plugin implementations for built-in formats and HTTP fetching.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import socket
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Literal, TextIO, overload
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from http.client import HTTPMessage

from sunstone.lineage import CsvDialect
from sunstone.ssrf import is_public_url

import pandas as pd


def _apply_csv_dialect_read(kwargs: dict, dialect: CsvDialect | None) -> dict:
    """Translate a ``CsvDialect`` into pandas ``read_csv`` kwargs.

    Caller-supplied kwargs always win — the dialect only fills in keys the
    user didn't already set.
    """
    if dialect is None:
        return kwargs
    out = dict(kwargs)
    if "sep" not in out and "delimiter" not in out:
        out["sep"] = dialect.delimiter
    out.setdefault("quotechar", dialect.quote_char)
    if "header" not in out and not dialect.header:
        # pandas default is 'infer' (assumes a header row); only override when
        # the dialect explicitly says there isn't one.
        out["header"] = None
    return out


def _apply_csv_dialect_write(kwargs: dict, dialect: CsvDialect | None) -> dict:
    """Translate a ``CsvDialect`` into pandas ``to_csv`` kwargs.

    Caller-supplied kwargs always win.
    """
    if dialect is None:
        return kwargs
    out = dict(kwargs)
    if "sep" not in out:
        out["sep"] = dialect.delimiter
    out.setdefault("quotechar", dialect.quote_char)
    out.setdefault("header", dialect.header)
    return out


# Extension -> format string mapping
_EXTENSION_MAP: dict[str, str] = {
    ".csv": "csv",
    ".json": "json",
    ".xlsx": "excel",
    ".xls": "excel",
    ".tsv": "tsv",
    ".txt": "tsv",
}

# Format string -> pandas reader function
_READER_MAP: dict[str, Callable[..., pd.DataFrame]] = {
    "csv": pd.read_csv,
    "json": pd.read_json,
    "excel": pd.read_excel,
    "tsv": lambda path, **kw: pd.read_csv(path, sep="\t", **kw),
}

# Format string -> pandas writer method name on DataFrame
_WRITER_MAP: dict[str, str] = {
    "csv": "to_csv",
}


class BuiltinFormatHandler:
    """Handles CSV, JSON, Excel, and TSV formats using pandas."""

    def supports_metadata(self) -> bool:
        """Return False — these formats do not support embedded metadata."""
        return False

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

    def read(self, stream: BinaryIO | Path, **kwargs: object) -> pd.DataFrame:
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        dialect = kwargs.pop("dialect", None)
        # If stream is actually a Path (pre-Task-7 call site), use it for format detection
        if isinstance(stream, Path) and path is None:
            path = stream
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"  # safe default
        if fmt == "csv" and isinstance(dialect, CsvDialect):
            kwargs = _apply_csv_dialect_read(kwargs, dialect)
        reader = _READER_MAP[str(fmt)]
        return reader(stream, **kwargs)

    def can_write(self, path: str, format: str | None) -> bool:
        fmt = self._resolve_format(path, format)
        return fmt is not None and fmt in _WRITER_MAP

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        fmt = kwargs.pop("format", None)
        path = kwargs.pop("path", None)
        dialect = kwargs.pop("dialect", None)
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"
        if fmt == "csv" and isinstance(dialect, CsvDialect):
            kwargs = _apply_csv_dialect_write(kwargs, dialect)
        if fmt == "csv":
            kwargs.setdefault("lineterminator", "\n")
        method_name = _WRITER_MAP[str(fmt)]
        writer = getattr(df, method_name)
        writer(stream, **kwargs)


class ParquetFormatHandler:
    """Handles Parquet format with metadata embedding support via PyArrow."""

    def supports_metadata(self) -> bool:
        """Return True — Parquet supports embedded metadata in file footer."""
        return True

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        """Resolve format from explicit format or file extension."""
        if format is not None:
            return "parquet" if format == "parquet" else None
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        suffix = PurePosixPath(file_path).suffix.lower()
        return "parquet" if suffix == ".parquet" else None

    def can_read(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) == "parquet"

    def can_write(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) == "parquet"

    def read(self, stream: BinaryIO, **kwargs: object) -> pd.DataFrame:
        import json as _json

        import pyarrow.parquet as pq  # type: ignore[import-untyped]

        kwargs.pop("format", None)
        kwargs.pop("path", None)
        kwargs.pop("dialect", None)

        table = pq.read_table(stream, **kwargs)
        df: pd.DataFrame = table.to_pandas()

        # Extract sunstone metadata from Parquet schema metadata if present
        schema_meta = table.schema.metadata or {}
        raw = schema_meta.get(b"sunstone")
        if raw is not None:
            from .lineage import Metadata

            doc = _json.loads(raw)
            df.attrs["sunstone_metadata"] = Metadata.from_jsonld(doc)

        return df

    def write(self, df: pd.DataFrame, stream: BinaryIO, **kwargs: object) -> None:
        import json as _json

        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        # Pop metadata before from_pandas() — pyarrow tries to JSON-serialize attrs
        metadata_obj = df.attrs.pop("sunstone_metadata", None)

        table = pa.Table.from_pandas(df)

        # Embed sunstone metadata in Parquet schema metadata if present
        if metadata_obj is not None:
            existing_meta = table.schema.metadata or {}
            doc = metadata_obj.to_jsonld()
            existing_meta[b"sunstone"] = _json.dumps(doc).encode("utf-8")
            table = table.replace_schema_metadata(existing_meta)

        pq.write_table(table, stream, **kwargs)


logger = logging.getLogger(__name__)

# Maximum response size: 512 MB
MAX_RESPONSE_SIZE = 512 * 1024 * 1024

# Streaming read chunk size
_CHUNK_SIZE = 64 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    """Return redirect responses to the caller so they can be validated manually."""

    def http_error_302(self, req: Request, fp: Any, code: int, msg: str, headers: HTTPMessage) -> Any:
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _resolve_and_validate(hostname: str) -> list[tuple[Any, ...]]:
    """Resolve hostname to IPs and validate they are all public.

    Returns the addrinfo list on success, raises ValueError on failure.
    This reduces the DNS TOCTOU window by resolving once and reusing the result.
    """
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Unable to resolve hostname: {hostname}")

    for addrinfo in addrinfos:
        sockaddr = addrinfo[4]
        ip = sockaddr[0]
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            raise ValueError(f"URL hostname '{hostname}' resolves to restricted IP address: {ip}")
    return addrinfos


def _read_response_with_limit(response: Any, max_size: int = MAX_RESPONSE_SIZE) -> bytes:
    """Read an HTTP response body with size enforcement.

    Checks Content-Length header first (if present), then enforces the limit
    during streaming reads to handle chunked/missing Content-Length cases.
    """
    # Check Content-Length if declared
    content_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except (ValueError, TypeError):
            declared_size = -1
        if declared_size > max_size:
            raise ValueError(
                f"Response Content-Length ({declared_size} bytes) exceeds maximum allowed size ({max_size} bytes)"
            )

    # Stream with size enforcement
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise ValueError(f"Response body exceeds maximum allowed size ({max_size} bytes)")
        chunks.append(chunk)
    return b"".join(chunks)


class HttpURLHandler:
    """Fetches datasets from HTTP/HTTPS URLs with SSRF protection.

    Security features:
    - Blocks private/loopback/link-local IP addresses
    - Blocks cloud metadata endpoints (169.254.169.254, metadata.google.internal)
    - Enforces maximum response size (Content-Length check + streaming limit)
    - Strips Authorization headers on cross-origin redirects
    - Reduces DNS TOCTOU risk by resolving hostname once and connecting to the
      resolved IP directly while preserving the Host header

    Limitation: DNS rebinding during a long-lived connection is not fully
    prevented at the stdlib level. For high-security environments, consider
    a network-level control (firewall rules blocking metadata IPs).
    """

    def __init__(
        self,
        timeout: int = 30,
        max_redirects: int = 10,
        max_response_size: int = MAX_RESPONSE_SIZE,
    ) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_response_size = max_response_size

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")

    @overload
    def open(self, url: str, mode: Literal["r"], *, headers: dict[str, str] | None = ...) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"], *, headers: dict[str, str] | None = ...) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"], *, headers: dict[str, str] | None = ...) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"], *, headers: dict[str, str] | None = ...) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb", *, headers: dict[str, str] | None = None) -> BinaryIO | TextIO:
        if "w" in mode:
            raise NotImplementedError(
                "HTTP write is not supported. Use a cloud storage handler (gs://, s3://) for uploads."
            )

        if not is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
            )

        logger.info("Fetching dataset from URL: %s", url)

        current_url = url
        current_headers = dict(headers or {})
        opener = build_opener(_NoRedirectHandler())

        for redirect_count in range(self.max_redirects + 1):
            # Resolve hostname and rewrite URL to use IP directly to reduce
            # DNS TOCTOU window. Preserve the original Host header.
            parsed = urlparse(current_url)
            hostname = parsed.hostname or ""
            ip_url = current_url
            host_header: str | None = None

            if hostname and not _is_ip_literal(hostname):
                try:
                    addrinfos = _resolve_and_validate(hostname)
                    resolved_ip = addrinfos[0][4][0]
                    # Rewrite URL to use the resolved IP
                    ip_obj = ipaddress.ip_address(resolved_ip)
                    if ip_obj.version == 6:
                        ip_host = f"[{resolved_ip}]"
                    else:
                        ip_host = resolved_ip
                    port_part = f":{parsed.port}" if parsed.port else ""
                    ip_url = f"{parsed.scheme}://{ip_host}{port_part}{parsed.path}"
                    if parsed.query:
                        ip_url += f"?{parsed.query}"
                    if parsed.fragment:
                        ip_url += f"#{parsed.fragment}"
                    host_header = hostname
                    if parsed.port:
                        host_header += f":{parsed.port}"
                except ValueError:
                    raise ValueError(
                        f"URL '{current_url}' is not allowed. "
                        "Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
                    )

            request = Request(ip_url, headers=current_headers)
            if host_header:
                request.add_unredirected_header("Host", host_header)

            response = opener.open(request, timeout=self.timeout)  # noqa: S310
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()

            if status not in (301, 302, 303, 307, 308):
                data = _read_response_with_limit(response, self.max_response_size)
                logger.info("Fetched %d bytes from %s", len(data), current_url)
                break

            redirect_url = response.headers.get("Location")
            response.close()
            if not redirect_url:
                raise ValueError("Redirect response without Location header")

            redirect_url = urljoin(current_url, redirect_url)

            if not is_public_url(redirect_url):
                raise ValueError(f"Redirect URL '{redirect_url}' is not allowed.")

            redirect_parsed = urlparse(redirect_url)
            current_parsed = urlparse(current_url)
            if redirect_parsed.scheme != current_parsed.scheme or redirect_parsed.netloc != current_parsed.netloc:
                current_headers = {k: v for k, v in current_headers.items() if k.lower() != "authorization"}

            logger.info("Following redirect to: %s", redirect_url)
            current_url = redirect_url
        else:
            raise ValueError(f"Too many redirects (max: {self.max_redirects})")

        if "b" in mode:
            return io.BytesIO(data)
        else:
            return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")


def _is_ip_literal(hostname: str) -> bool:
    """Check if hostname is already an IP address literal."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


_REMOTE_SCHEMES = {"http", "https", "gs", "s3", "r2"}


class LocalFileHandler:
    """Handles local filesystem paths and file:// URLs."""

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        scheme = parsed.scheme
        # On Windows, urlparse treats drive letters (C:) as schemes
        if len(scheme) == 1 and scheme.isalpha():
            return True
        return scheme in ("", "file") and scheme not in _REMOTE_SCHEMES

    @overload
    def open(self, url: str, mode: Literal["r"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["rb"]) -> BinaryIO: ...
    @overload
    def open(self, url: str, mode: Literal["w"]) -> TextIO: ...
    @overload
    def open(self, url: str, mode: Literal["wb"]) -> BinaryIO: ...
    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        import builtins as _builtins
        from urllib.request import url2pathname

        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = Path(url2pathname(parsed.path))
        else:
            path = Path(url)

        if "w" in mode:
            path.parent.mkdir(parents=True, exist_ok=True)

        return _builtins.open(path, mode)  # type: ignore[return-value]
