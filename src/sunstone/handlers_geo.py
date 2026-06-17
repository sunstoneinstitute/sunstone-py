"""GeoJSON/TopoJSON format handler for AssetKind.GEOFEATURES.

geopandas/shapely/topojson are imported lazily inside read()/write() so that
importing this module (and resolving handlers) is dependency-free. Registered
only when the [geo] extra is importable — see PluginRegistry._discover.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlparse

from .asset import AssetKind
from .field_types import FieldTypeDescriptor

_EXTENSION_MAP = {".geojson": "geojson", ".topojson": "topojson"}
_FORMATS = frozenset({"geojson", "topojson"})
_SUNSTONE_KEY = "sunstone"


def _is_geometry(value: Any) -> bool:
    """Cell contract for the `geometry` field type: a shapely geometry."""
    return hasattr(value, "geom_type") or value is None


def _require_geo() -> None:
    try:
        import geopandas  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised via message test
        raise ImportError(
            "Reading/writing GeoJSON/TopoJSON requires the geo extra. Install it with: pip install sunstone-py[geo]"
        ) from exc


class GeoFeaturesFormatHandler:
    __sunstone_handler_protocol__ = 2

    def supports_native_metadata_extraction(self) -> bool:
        return False

    def supports_sunstone_metadata_embedding(self) -> bool:
        return True

    def supports_metadata(self) -> bool:
        return True

    def supported_kinds(self) -> tuple:
        return (AssetKind.GEOFEATURES,)

    def field_types(self) -> tuple[FieldTypeDescriptor, ...]:
        return (
            FieldTypeDescriptor(
                name="geometry",
                validate=_is_geometry,
                description="A geographic geometry (shapely) with a CRS.",
            ),
        )

    def _resolve_format(self, path: str, format: str | None) -> str | None:
        if format is not None:
            return format if format in _FORMATS else None
        parsed = urlparse(path)
        file_path = parsed.path if parsed.scheme else path
        return _EXTENSION_MAP.get(PurePosixPath(file_path).suffix.lower())

    def can_read(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def can_write(self, path: str, format: str | None) -> bool:
        return self._resolve_format(path, format) is not None

    def read(self, stream: BinaryIO, **kwargs: object) -> Any:
        _require_geo()
        import geopandas as gpd

        from .asset import Asset
        from .lineage import Metadata

        fmt = self._resolve_format(str(kwargs.get("path") or ""), kwargs.get("format"))  # type: ignore[arg-type]
        kwargs.pop("format", None)
        kwargs.pop("path", None)
        kwargs.pop("dialect", None)

        raw = stream.read()
        doc = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)

        meta = Metadata()
        sunstone_blob = doc.pop(_SUNSTONE_KEY, None) if isinstance(doc, dict) else None
        if sunstone_blob is not None:
            try:
                meta = Metadata.from_jsonld(sunstone_blob)
            except Exception:
                meta = Metadata()

        if fmt == "topojson":
            doc = self._topojson_to_featurecollection(doc)

        features = doc.get("features", []) if isinstance(doc, dict) else []
        if features:
            gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        else:
            gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

        return Asset(
            payload=gdf,
            kind=AssetKind.GEOFEATURES,
            metadata=meta,
            extras={"crs": gdf.crs},
        )

    def write(self, asset: object, stream: BinaryIO, **kwargs: object) -> None:
        _require_geo()
        fmt = self._resolve_format(str(kwargs.get("path") or ""), kwargs.get("format"))  # type: ignore[arg-type]
        kwargs.pop("format", None)
        kwargs.pop("path", None)
        kwargs.pop("dialect", None)

        gdf = asset.as_geofeatures() if hasattr(asset, "as_geofeatures") else asset
        metadata_obj = getattr(asset, "metadata", None)

        gdf = self._orient_rings(gdf)
        if gdf.crs is not None and getattr(gdf.crs, "to_epsg", lambda: None)() != 4326:
            import warnings

            warnings.warn(
                "Writing non-WGS84 geometry as GeoJSON is non-conformant with RFC 7946; "
                "CRS is recorded in metadata but coordinates are not reprojected.",
                stacklevel=2,
            )

        if fmt == "topojson":
            doc = self._geodataframe_to_topojson(gdf)
        else:
            doc = json.loads(gdf.to_json())  # FeatureCollection; geopandas does not emit crs in v1
            doc.pop("crs", None)  # belt-and-suspenders for older geopandas

        if metadata_obj is not None:
            doc[_SUNSTONE_KEY] = metadata_obj.to_jsonld()

        stream.write(json.dumps(doc).encode("utf-8"))

    @staticmethod
    def _orient_rings(gdf: Any) -> Any:
        """Right-hand rule per RFC 7946: exterior CCW, holes CW."""
        from shapely.geometry.base import BaseGeometry
        from shapely.geometry.polygon import orient

        def _fix(geom: BaseGeometry) -> Any:
            if geom is None:
                return geom
            if geom.geom_type == "Polygon":
                return orient(geom, sign=1.0)
            if geom.geom_type == "MultiPolygon":
                from shapely.geometry import MultiPolygon

                return MultiPolygon([orient(g, sign=1.0) for g in geom.geoms])
            return geom

        out = gdf.copy()
        out[out.geometry.name] = out.geometry.apply(_fix)
        return out

    def _topojson_to_featurecollection(self, topo: dict) -> dict:
        transform = topo.get("transform")
        raw_arcs = topo.get("arcs", [])

        def decode_arc(arc: list) -> list:
            if transform is None:
                return [list(p) for p in arc]
            sx, sy = transform["scale"]
            tx, ty = transform["translate"]
            x = y = 0
            out = []
            for p in arc:
                x += p[0]
                y += p[1]
                out.append([x * sx + tx, y * sy + ty])
            return out

        arcs = [decode_arc(a) for a in raw_arcs]

        def deref(idx: int) -> list:
            return list(arcs[idx]) if idx >= 0 else list(reversed(arcs[~idx]))

        def stitch(indexes: list) -> list:
            line: list = []
            for k, idx in enumerate(indexes):
                pts = deref(idx)
                line.extend(pts[1:] if k > 0 else pts)
            return line

        def decode_point(p: list) -> list:
            if transform is None:
                return list(p)
            sx, sy = transform["scale"]
            tx, ty = transform["translate"]
            return [p[0] * sx + tx, p[1] * sy + ty]

        def to_geometry(g: dict) -> dict | None:
            t = g.get("type")
            if t is None:
                return None
            if t == "Point":
                return {"type": "Point", "coordinates": decode_point(g["coordinates"])}
            if t == "MultiPoint":
                return {"type": "MultiPoint", "coordinates": [decode_point(p) for p in g["coordinates"]]}
            if t == "LineString":
                return {"type": "LineString", "coordinates": stitch(g["arcs"])}
            if t == "MultiLineString":
                return {"type": "MultiLineString", "coordinates": [stitch(a) for a in g["arcs"]]}
            if t == "Polygon":
                return {"type": "Polygon", "coordinates": [stitch(r) for r in g["arcs"]]}
            if t == "MultiPolygon":
                return {
                    "type": "MultiPolygon",
                    "coordinates": [[stitch(r) for r in poly] for poly in g["arcs"]],
                }
            return None

        features = []
        for obj in topo.get("objects", {}).values():
            geometries = obj.get("geometries", [obj]) if obj.get("type") == "GeometryCollection" else [obj]
            for g in geometries:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": to_geometry(g),
                        "properties": g.get("properties", {}) or {},
                        **({"id": g["id"]} if "id" in g else {}),
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def _geodataframe_to_topojson(self, gdf: Any) -> dict:
        import topojson

        topo = topojson.Topology(gdf, prequantize=False)
        # topojson returns a JSON string; parse to a dict so we can attach metadata.
        result: dict = json.loads(topo.to_json())
        return result
