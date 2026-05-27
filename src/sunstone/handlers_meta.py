"""Metadata types used by the FormatHandler / StoreFormatHandler discovery protocol."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentDescriptor:
    """What a handler reads/writes. Mirrors HTTP Content-Type + Content-Encoding.

    Identity is two-dimensional: the payload's canonical MIME (``content_type``),
    and how it has been encoded for transport/storage (``content_encoding``).
    A ``.tar.gz`` archive is ``ContentDescriptor("application/x-tar", "gzip")``;
    a plain ``.csv`` is ``ContentDescriptor("text/csv")``.

    ``content_type`` should be the bare canonical MIME with no parameters;
    callers strip parameters (e.g. ``"text/csv; charset=utf-8"``) before lookup.
    """

    content_type: str
    content_encoding: str | None = None
