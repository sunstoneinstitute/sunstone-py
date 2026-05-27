"""HDF5 / NetCDF-4 store-format handler.

Reads and writes ``AssetKind.ARRAY`` assets (a ``dict[str, numpy.ndarray]``
payload) backed by an HDF5 file. Embeds sunstone :class:`Metadata` as a
JSON-LD blob in the file root's ``sunstone`` attribute, and writes
CF-convention per-variable attributes (``units``, ``long_name``,
``description``) for ecosystem interop with xarray, ncdump, Panoply, etc.

NetCDF-4 files (``.nc`` / ``.nc4``) are HDF5 underneath and are handled
through the same code path. NetCDF-3 (classic) is out of scope.

This is a :class:`~sunstone.resource.StoreFormatHandler` (protocol v2)
because h5py needs a real filesystem path, not a stream.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from .asset import Asset, AssetKind
from .component import ComponentSchema
from .errors import IncompatibleAssetKindError
from .lineage import Metadata

if TYPE_CHECKING:
    from .handlers_meta import ContentDescriptor
    from .resource import ResourceLocation


class Hdf5StoreHandler:
    """HDF5 / NetCDF-4 store-format handler for ``AssetKind.ARRAY`` payloads."""

    __sunstone_handler_protocol__ = 2

    _METADATA_KEY = "sunstone"
    _EXTENSIONS = (".h5", ".hdf5", ".he5", ".nc", ".nc4")

    # ---- Capability predicates --------------------------------------------------

    def supports_native_metadata_extraction(self) -> bool:
        """CF-convention per-variable attrs (``units``, ``long_name``) are
        treated as native sidecar metadata."""
        return True

    def supports_sunstone_metadata_embedding(self) -> bool:
        """The full sunstone :class:`Metadata` is round-tripped as JSON-LD in
        the file root's ``sunstone`` attribute."""
        return True

    def supports_metadata(self) -> bool:
        """Legacy alias for :meth:`supports_sunstone_metadata_embedding`."""
        return self.supports_sunstone_metadata_embedding()

    def supported_kinds(self) -> tuple[AssetKind, ...]:
        return (AssetKind.ARRAY,)

    def content_descriptors(self) -> tuple["ContentDescriptor", ...]:
        from .handlers_meta import ContentDescriptor

        return (
            ContentDescriptor(content_type="application/x-hdf5", content_encoding=None),
            ContentDescriptor(content_type="application/x-netcdf", content_encoding=None),
        )

    def extensions(self) -> tuple[str, ...]:
        return (".h5", ".hdf5", ".nc", ".nc4")

    # ---- Format detection -------------------------------------------------------

    def _matches(self, location: "ResourceLocation", format: str | None) -> bool:
        if format is not None:
            return format.lower() in ("hdf5", "h5", "netcdf4", "netcdf", "nc")
        suffix = PurePosixPath(location.path).suffix.lower()
        return suffix in self._EXTENSIONS

    def can_read_store(self, location: "ResourceLocation", format: str | None) -> bool:
        if not self._matches(location, format):
            return False
        # The file must exist for a read.
        return location.as_path().is_file()

    def can_write_store(self, location: "ResourceLocation", format: str | None) -> bool:
        # Writes do not require the file to exist yet.
        return self._matches(location, format)

    # ---- Read -------------------------------------------------------------------

    def read(self, location: "ResourceLocation", **kwargs: Any) -> Asset:
        import h5py  # type: ignore[import-untyped]
        import numpy as np

        # Drop dispatch-only kwargs we forward from sunstone.read/write.
        kwargs.pop("format", None)
        kwargs.pop("path", None)

        payload: dict[str, np.ndarray] = {}
        metadata = Metadata()

        with h5py.File(location.path, "r") as f:
            # Root-level sunstone metadata blob (JSON-LD).
            raw = f.attrs.get(self._METADATA_KEY)
            if raw is not None:
                try:
                    if isinstance(raw, (bytes, bytearray)):
                        doc = json.loads(raw.decode("utf-8"))
                    elif isinstance(raw, np.ndarray):
                        # h5py may return scalar string attrs as 0-d arrays.
                        item = raw.item()
                        if isinstance(item, bytes):
                            item = item.decode("utf-8")
                        doc = json.loads(item)
                    else:
                        doc = json.loads(str(raw))
                    metadata = Metadata.from_jsonld(doc)
                except Exception:
                    metadata = Metadata()

            # Walk top-level datasets only (v1 — no nested groups).
            for name, obj in f.items():
                if isinstance(obj, h5py.Dataset):
                    payload[name] = np.asarray(obj[()])

                    # Synthesize ComponentSchema from CF attrs if the JSON-LD
                    # blob didn't already restore one.
                    if name not in metadata.component_metadata:
                        cs = _component_from_attrs(name, obj.attrs)
                        if cs is not None:
                            metadata.component_metadata[name] = cs

        return Asset(payload=payload, kind=AssetKind.ARRAY, metadata=metadata)

    # ---- Write ------------------------------------------------------------------

    def write(self, asset: Asset, location: "ResourceLocation", **kwargs: Any) -> None:
        import h5py  # type: ignore[import-untyped]

        # Drop dispatch-only kwargs.
        kwargs.pop("format", None)
        kwargs.pop("path", None)

        if asset.kind is not AssetKind.ARRAY:
            raise IncompatibleAssetKindError(expected=AssetKind.ARRAY, actual=asset.kind)

        payload = asset.as_array()

        # Ensure parent directory exists for nested write locations.
        target = location.as_path()
        if target.parent:
            target.parent.mkdir(parents=True, exist_ok=True)

        with h5py.File(target, "w") as f:
            for name, arr in payload.items():
                ds = f.create_dataset(name, data=arr, **kwargs)
                cs = asset.metadata.component_metadata.get(name)
                if cs is not None:
                    _write_cf_attrs(ds, cs)

            # Root attr: full sunstone metadata as JSON-LD.
            doc = asset.metadata.to_jsonld()
            f.attrs[self._METADATA_KEY] = json.dumps(doc)


def _component_from_attrs(name: str, attrs: Any) -> ComponentSchema | None:
    """Build a :class:`ComponentSchema` from CF-style HDF5 attrs.

    Returns ``None`` if no recognised attrs are present.
    """
    units = _str_attr(attrs.get("units"))
    long_name = _str_attr(attrs.get("long_name"))
    description = _str_attr(attrs.get("description"))
    if units is None and long_name is None and description is None:
        return None
    # Prefer description over long_name when both are present.
    desc = description if description is not None else long_name
    return ComponentSchema(
        name=name,
        component_kind="variable",
        units=units,
        description=desc,
    )


def _write_cf_attrs(dataset: Any, cs: ComponentSchema) -> None:
    """Write CF-convention per-variable attributes to an HDF5 dataset."""
    if cs.units is not None:
        dataset.attrs["units"] = cs.units
    if cs.description is not None:
        # CF convention: long_name is the human-readable label.
        dataset.attrs["long_name"] = cs.description
        # Also mirror to "description" for tools that prefer that key.
        dataset.attrs["description"] = cs.description


def _str_attr(value: Any) -> str | None:
    """Decode an h5py attribute value into a plain ``str`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a hard dep
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        if value.shape == ():
            item = value.item()
            if isinstance(item, bytes):
                return item.decode("utf-8")
            return str(item)
        return None
    return str(value)
