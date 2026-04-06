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
        # If stream is actually a Path (pre-Task-7 call site), use it for format detection
        if isinstance(stream, Path) and path is None:
            path = stream
        if fmt is None and path is not None:
            fmt = self._resolve_format(str(path), None)
        if fmt is None:
            fmt = "csv"  # safe default
        reader = _READER_MAP[str(fmt)]
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
        method_name = _WRITER_MAP[str(fmt)]
        writer = getattr(df, method_name)
        writer(stream, **kwargs)


logger = logging.getLogger(__name__)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Return redirect responses to the caller so they can be validated manually."""

    def http_error_302(self, req: Request, fp: Any, code: int, msg: str, headers: HTTPMessage) -> Any:
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


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


class HttpURLHandler:
    """Fetches datasets from HTTP/HTTPS URLs with SSRF protection."""

    def __init__(self, timeout: int = 30, max_redirects: int = 10) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects

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

        if not _is_public_url(url):
            raise ValueError(
                f"URL '{url}' is not allowed. Only HTTP/HTTPS URLs pointing to public internet addresses are permitted."
            )

        logger.info("Fetching dataset from URL: %s", url)

        current_url = url
        current_headers = dict(headers or {})
        opener = build_opener(_NoRedirectHandler())

        for redirect_count in range(self.max_redirects + 1):
            request = Request(current_url, headers=current_headers)
            response = opener.open(request, timeout=self.timeout)  # noqa: S310
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()

            if status not in (301, 302, 303, 307, 308):
                data = response.read()
                logger.info("Fetched %d bytes from %s", len(data), current_url)
                break

            redirect_url = response.headers.get("Location")
            response.close()
            if not redirect_url:
                raise ValueError("Redirect response without Location header")

            redirect_url = urljoin(current_url, redirect_url)

            if not _is_public_url(redirect_url):
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
