"""NumPy ``.npz`` format handler for ``AssetKind.ARRAY`` assets.

Reads and writes a single-file zip of ``.npy`` arrays (``numpy.savez`` /
``numpy.load``) into and out of the unified :class:`~sunstone.asset.Asset`
envelope. Round-trips a sunstone :class:`~sunstone.lineage.Metadata` blob by
storing the JSON-LD payload inside the archive under a reserved key.
"""

from __future__ import annotations

import json as _json
from dataclasses import asdict, fields as _dc_fields
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .asset import Asset


class NpzFormatHandler:
    """Handles NumPy ``.npz`` archives for ``AssetKind.ARRAY`` assets.

    Stream-based ``FormatHandler`` (protocol v2). The archive stores one
    ``.npy`` per variable plus an optional reserved entry,
    ``__sunstone_metadata__``, carrying a uint8 array of the JSON-LD-encoded
    sunstone ``Metadata`` blob (including any ``component_metadata`` for
    per-variable schemas).
    """

    __sunstone_handler_protocol__ = 2

    _METADATA_KEY = "__sunstone_metadata__"
    """Reserved npz archive key used to embed the sunstone Metadata blob."""

    _COMPONENT_METADATA_DOC_KEY = "si:components"
    """Reserved JSON-LD doc key carrying serialised ``component_metadata``.

    ``Metadata.to_jsonld()`` does not (yet) emit ``component_metadata``; we
    piggy-back it on the doc here and restore it in :meth:`read` so the
    handler round-trips losslessly today and degrades cleanly once a future
    ``Metadata`` revision learns to emit components natively.
    """

    # --- capability predicates ---------------------------------------------

    def supports_native_metadata_extraction(self) -> bool:
        """The archive can carry an embedded JSON-LD sidecar."""
        return True

    def supports_sunstone_metadata_embedding(self) -> bool:
        """Full sunstone ``Metadata`` round-trips via the reserved key."""
        return True

    def supports_metadata(self) -> bool:
        """Legacy alias for ``supports_sunstone_metadata_embedding()``."""
        return self.supports_sunstone_metadata_embedding()

    def supported_kinds(self) -> tuple:
        from .asset import AssetKind

        return (AssetKind.ARRAY,)

    # --- dispatch helpers --------------------------------------------------

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        if format is not None:
            return "npz" if format == "npz" else None
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        suffix = PurePosixPath(file_path).suffix.lower()
        return "npz" if suffix == ".npz" else None

    def can_read(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) == "npz"

    def can_write(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) == "npz"

    # --- read --------------------------------------------------------------

    def read(self, stream: BinaryIO, **kwargs: object) -> "Asset":
        import numpy as np

        from .asset import Asset, AssetKind
        from .lineage import Metadata

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        npz = np.load(stream, allow_pickle=False)
        try:
            arrays: dict[str, np.ndarray] = {}
            meta_blob: bytes | None = None
            for key in npz.files:
                if key == self._METADATA_KEY:
                    raw = npz[key]
                    # JSON-LD bytes were stored as a uint8 array.
                    meta_blob = bytes(raw.tobytes())
                else:
                    # Materialise so the array stays usable after the
                    # underlying zip closes.
                    arrays[key] = np.array(npz[key])
        finally:
            npz.close()

        meta = Metadata()
        if meta_blob is not None:
            try:
                doc = _json.loads(meta_blob.decode("utf-8"))
            except Exception:
                doc = None
            if isinstance(doc, dict):
                component_doc = doc.pop(self._COMPONENT_METADATA_DOC_KEY, None)
                try:
                    meta = Metadata.from_jsonld(doc)
                except Exception:
                    meta = Metadata()
                if isinstance(component_doc, dict):
                    meta.component_metadata = _deserialise_component_metadata(component_doc)

        return Asset(payload=arrays, kind=AssetKind.ARRAY, metadata=meta)

    # --- write -------------------------------------------------------------

    def write(self, asset: object, stream: BinaryIO, **kwargs: object) -> None:
        import numpy as np

        from .asset import AssetKind
        from .errors import IncompatibleAssetKindError

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        kind = getattr(asset, "kind", None)
        if kind is not AssetKind.ARRAY:
            raise IncompatibleAssetKindError(
                expected=AssetKind.ARRAY,
                actual=kind if isinstance(kind, AssetKind) else AssetKind.TABULAR,
            )

        payload = asset.as_array()  # type: ignore[attr-defined]
        if not isinstance(payload, dict):
            raise TypeError(f"ARRAY asset payload must be dict[str, ndarray], got {type(payload).__name__}")
        for key, arr in payload.items():
            if key == self._METADATA_KEY:
                raise ValueError(f"Variable name {key!r} is reserved for sunstone metadata embedding.")

        to_write: dict[str, np.ndarray] = {name: np.asarray(arr) for name, arr in payload.items()}

        metadata = getattr(asset, "metadata", None)
        if metadata is not None and _metadata_has_content(metadata):
            doc = metadata.to_jsonld()
            component_doc = _serialise_component_metadata(metadata.component_metadata)
            if component_doc:
                doc[self._COMPONENT_METADATA_DOC_KEY] = component_doc
            blob = _json.dumps(doc).encode("utf-8")
            to_write[self._METADATA_KEY] = np.frombuffer(blob, dtype=np.uint8)

        np.savez_compressed(stream, **to_write)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metadata_has_content(metadata: Any) -> bool:
    """Return True if ``metadata`` carries anything worth serialising.

    The empty ``Metadata()`` produced by a bare read is skipped so we don't
    pollute the archive with an empty JSON-LD blob.
    """
    if metadata is None:
        return False
    if metadata.slug or metadata.name or metadata.description:
        return True
    if metadata.rdf_prefixes:
        return True
    if metadata.custom_properties:
        return True
    if metadata.field_metadata:
        return True
    if metadata.component_metadata:
        return True
    if metadata.identity:
        return True
    lineage = getattr(metadata, "lineage", None)
    if lineage is not None:
        if lineage.sources:
            return True
        if lineage.activity is not None:
            return True
        if lineage.field_derivations:
            return True
        if lineage.created_at is not None:
            return True
        if lineage.data_hash is not None:
            return True
    return False


def _serialise_component_metadata(components: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Serialise ``Metadata.component_metadata`` into a JSON-safe dict."""
    if not components:
        return {}
    from .component import ComponentSchema

    out: dict[str, dict[str, Any]] = {}
    for name, comp in components.items():
        if not isinstance(comp, ComponentSchema):
            continue
        entry: dict[str, Any] = {}
        for f in _dc_fields(comp):
            value = getattr(comp, f.name)
            if value is None:
                continue
            if f.name == "derived_from" and value is not None:
                entry[f.name] = [asdict(d) for d in value]
            else:
                entry[f.name] = value
        out[name] = entry
    return out


def _deserialise_component_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`_serialise_component_metadata`."""
    from .component import ComponentSchema
    from .lineage import FieldDerivation

    out: dict[str, ComponentSchema] = {}
    for name, entry in doc.items():
        if not isinstance(entry, dict):
            continue
        derived_raw = entry.get("derived_from")
        derived_from = None
        if isinstance(derived_raw, list):
            derived_from = [FieldDerivation(**d) for d in derived_raw if isinstance(d, dict)]
        out[name] = ComponentSchema(
            name=entry.get("name", name),
            component_kind=entry.get("component_kind", "variable"),
            dtype=entry.get("dtype"),
            units=entry.get("units"),
            description=entry.get("description"),
            custom_properties=entry.get("custom_properties"),
            derived_from=derived_from,
        )
    return out
