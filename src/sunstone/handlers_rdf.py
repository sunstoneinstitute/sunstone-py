"""RDF format handler (Turtle, N-Triples, JSON-LD) for AssetKind.GRAPH.

rdflib is imported lazily inside read() to keep import time down.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

from .asset import AssetKind

if TYPE_CHECKING:
    from .handlers_meta import ContentDescriptor

# short format -> (rdflib format name, media type)
_FORMATS: dict[str, tuple[str, str]] = {
    "ttl": ("turtle", "text/turtle"),
    "nt": ("nt", "application/n-triples"),
    "jsonld": ("json-ld", "application/ld+json"),
}
_ALIASES = {
    "turtle": "ttl",
    "ntriples": "nt",
    "n-triples": "nt",
    "json-ld": "jsonld",
    "text/turtle": "ttl",
    "application/n-triples": "nt",
    "application/ld+json": "jsonld",
}


class RdfFormatHandler:
    __sunstone_handler_protocol__ = 2

    def supports_native_metadata_extraction(self) -> bool:
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        return False

    def supports_metadata(self) -> bool:
        return False

    def supported_kinds(self) -> tuple:
        return (AssetKind.GRAPH,)

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        if format is not None:
            key = format.lower().lstrip(".")
            key = _ALIASES.get(key, key)
            return key if key in _FORMATS else None
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        suffix = PurePosixPath(file_path).suffix.lower().lstrip(".")
        return suffix if suffix in _FORMATS else None

    def can_read(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def can_write(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def read(self, stream: BinaryIO, **kwargs: object) -> Any:
        import rdflib

        from .asset import Asset
        from .lineage import Metadata

        fmt = self._resolve_format(str(kwargs.pop("path", None) or ""), kwargs.pop("format", None)) or "ttl"  # type: ignore[arg-type]
        kwargs.pop("dialect", None)
        rdflib_format, media_type = _FORMATS[fmt]

        raw = stream.read()
        graph = rdflib.Graph()
        graph.parse(data=raw.decode("utf-8") if isinstance(raw, bytes) else raw, format=rdflib_format)
        return Asset(payload=graph, kind=AssetKind.GRAPH, metadata=Metadata(), extras={"media_type": media_type})

    def write(self, asset: object, stream: BinaryIO, **kwargs: object) -> None:
        fmt = self._resolve_format(str(kwargs.pop("path", None) or ""), kwargs.pop("format", None)) or "ttl"  # type: ignore[arg-type]
        kwargs.pop("dialect", None)
        graph: Any = asset.as_graph() if hasattr(asset, "as_graph") else asset
        stream.write(graph.serialize(format=_FORMATS[fmt][0], encoding="utf-8"))

    def content_descriptors(self) -> tuple[ContentDescriptor, ...]:
        from .handlers_meta import ContentDescriptor

        return tuple(ContentDescriptor(content_type=media, content_encoding=None) for _, media in _FORMATS.values())

    def extensions(self) -> tuple[str, ...]:
        return tuple(f".{ext}" for ext in _FORMATS)
