"""
Internal plugin implementations for built-in formats and HTTP fetching.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from pathlib import Path
from typing import BinaryIO, Callable, TextIO
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests


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


_REMOTE_SCHEMES = {"http", "https", "gs", "s3", "r2"}


class LocalFileHandler:
    """Handles local filesystem paths and file:// URLs."""

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("", "file") and parsed.scheme not in _REMOTE_SCHEMES

    def open(self, url: str, mode: str = "rb") -> BinaryIO | TextIO:
        import builtins as _builtins

        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = Path(parsed.path)
        else:
            path = Path(url)

        if "w" in mode:
            path.parent.mkdir(parents=True, exist_ok=True)

        return _builtins.open(path, mode)  # type: ignore[return-value]
