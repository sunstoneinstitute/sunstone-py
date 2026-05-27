"""Zarr directory-store format handler.

Implements the :class:`~sunstone.resource.StoreFormatHandler` protocol for
``AssetKind.ARRAY`` payloads (``dict[str, numpy.ndarray]``).

Round-trip strategy:
- The full sunstone :class:`~sunstone.lineage.Metadata` blob is serialised as
  JSON-LD into the root group's ``.attrs`` under key ``"sunstone"``.
- Per-variable :class:`~sunstone.component.ComponentSchema` entries are also
  projected onto each array's ``.attrs`` as CF-convention attributes
  (``units``, ``long_name``, ``description``) — purely for ecosystem
  interoperability with xarray, Panoply, ncview, etc.

v1 supports local directory stores only. Remote stores (``gs://``, ``s3://``)
are tracked as follow-up work — see ``docs/tensors.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import numpy as np

if TYPE_CHECKING:
    from .handlers_meta import ContentDescriptor
    from .resource import ResourceLocation


_ZARR_V2_GROUP_MARKERS = (".zgroup", ".zarray")
_ZARR_V3_GROUP_MARKER = "zarr.json"


def _path_looks_like_zarr(path: str) -> bool:
    """Cheap path-suffix sniff. Does not require disk access."""
    parsed = urlparse(path)
    file_path = parsed.path if parsed.scheme else path
    return file_path.lower().rstrip("/").endswith(".zarr")


def _dir_has_zarr_marker(path: Path) -> bool:
    """True if ``path`` is a directory with a zarr v2 or v3 marker file."""
    if not path.is_dir():
        return False
    for marker in _ZARR_V2_GROUP_MARKERS:
        if (path / marker).exists():
            return True
    if (path / _ZARR_V3_GROUP_MARKER).exists():
        return True
    return False


class ZarrStoreHandler:
    """Read/write :class:`~sunstone.asset.Asset` of kind ``ARRAY`` against a
    Zarr directory store on the local filesystem.

    Compatible with both zarr v2 (``>=2.18``) and v3. v3 uses ``zarr.json``
    markers and ``create_array``; v2 uses ``.zgroup``/``.zarray`` and
    ``create_dataset``. This handler uses the version-agnostic ``g[name] =
    arr`` assignment shorthand for writes.
    """

    __sunstone_handler_protocol__ = 2
    _METADATA_KEY = "sunstone"

    def supports_native_metadata_extraction(self) -> bool:
        """Per-variable CF attrs are native metadata that this handler reads."""
        return True

    def supports_sunstone_metadata_embedding(self) -> bool:
        """Full sunstone metadata round-trips via the root group's ``sunstone`` attr."""
        return True

    def supports_metadata(self) -> bool:
        """Legacy alias for ``supports_sunstone_metadata_embedding()``."""
        return self.supports_sunstone_metadata_embedding()

    def supported_kinds(self) -> tuple:
        from .asset import AssetKind

        return (AssetKind.ARRAY,)

    def content_descriptors(self) -> tuple["ContentDescriptor", ...]:
        from .handlers_meta import ContentDescriptor

        return (ContentDescriptor(content_type="application/x-zarr", content_encoding=None),)

    def extensions(self) -> tuple[str, ...]:
        return (".zarr",)

    # --- store classification ---------------------------------------------

    def can_read_store(self, location: "ResourceLocation", format: str | None) -> bool:
        if format == "zarr":
            return True
        if _path_looks_like_zarr(location.path):
            return True
        return _dir_has_zarr_marker(location.as_path())

    def can_write_store(self, location: "ResourceLocation", format: str | None) -> bool:
        if format == "zarr":
            return True
        if _path_looks_like_zarr(location.path):
            return True
        # Allow existing zarr directories to be overwritten.
        return _dir_has_zarr_marker(location.as_path())

    # --- I/O --------------------------------------------------------------

    def read(self, location: "ResourceLocation", **kwargs: Any) -> Any:
        """Read a Zarr directory into an :class:`Asset` of kind ARRAY."""
        import zarr

        from .asset import Asset, AssetKind
        from .component import ComponentSchema
        from .lineage import Metadata

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        group = zarr.open_group(str(location.as_path()), mode="r")

        # 1. Read root attrs and hydrate sunstone metadata if present.
        root_attrs = dict(group.attrs)
        raw = root_attrs.get(self._METADATA_KEY)
        if raw is not None:
            try:
                doc = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(doc, dict):
                    meta = Metadata.from_jsonld(doc)
                else:
                    meta = Metadata()
            except Exception:
                meta = Metadata()
        else:
            meta = Metadata()

        # 2. Walk the immediate child arrays.
        payload: dict[str, np.ndarray] = {}
        for name, arr in group.arrays():
            payload[name] = np.asarray(arr[:])

            # 3. CF-style per-variable attrs — only populate ComponentSchema
            #    when nothing was already restored from the JSON-LD blob for
            #    this name (avoid clobbering richer info).
            if name in meta.component_metadata:
                continue
            var_attrs = dict(arr.attrs)
            raw_units = var_attrs.get("units")
            raw_long_name = var_attrs.get("long_name")
            raw_description = var_attrs.get("description") or raw_long_name
            units = raw_units if isinstance(raw_units, str) else None
            description = raw_description if isinstance(raw_description, str) else None
            if units is None and description is None:
                continue
            meta.component_metadata[name] = ComponentSchema(
                name=name,
                component_kind="variable",
                dtype=str(arr.dtype),
                units=units,
                description=description,
            )

        return Asset(payload=payload, kind=AssetKind.ARRAY, metadata=meta)

    def write(self, asset: Any, location: "ResourceLocation", **kwargs: Any) -> None:
        """Write an ARRAY-kind :class:`Asset` to a Zarr directory store."""
        import zarr

        from .asset import AssetKind
        from .errors import IncompatibleAssetKindError

        if not hasattr(asset, "kind") or asset.kind is not AssetKind.ARRAY:
            actual = getattr(asset, "kind", None)
            raise IncompatibleAssetKindError(
                expected=AssetKind.ARRAY,
                actual=actual if actual is not None else AssetKind.ARRAY,
            )

        kwargs.pop("format", None)
        kwargs.pop("path", None)

        arrays: dict[str, np.ndarray] = asset.as_array()
        component_meta = asset.metadata.component_metadata or {}

        target = Path(location.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        group = zarr.open_group(str(target), mode="w")

        for name, arr in arrays.items():
            np_arr = np.asarray(arr)
            # version-agnostic write: assignment shorthand works in v2 and v3.
            group[name] = np_arr
            cs = component_meta.get(name)
            if cs is None:
                continue
            # CF-convention attrs for ecosystem interop.
            written = group[name]
            if cs.units is not None:
                written.attrs["units"] = cs.units
            if cs.description is not None:
                written.attrs["long_name"] = cs.description
                written.attrs["description"] = cs.description

        # Embed the sunstone metadata blob as a JSON string at the root.
        doc = asset.metadata.to_jsonld()
        group.attrs[self._METADATA_KEY] = json.dumps(doc)
