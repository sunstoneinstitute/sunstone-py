# Geo Phase 2: The `[geo]` Plugin (GeoJSON/TopoJSON) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read/write GeoJSON and TopoJSON into a `geopandas.GeoDataFrame` with lineage, behind an optional `[geo]` extra, via a new `GEOFEATURES` asset kind and a `sunstone.geopandas` facade.

**Architecture:** A new `AssetKind.GEOFEATURES` (payload = `GeoDataFrame`). `handlers_geo.py` provides `GeoFeaturesFormatHandler` (geojson + topojson, lazy geopandas imports) and registers a `geometry` field type. Metadata embeds as a top-level `"sunstone"` foreign member. A `sunstone.geopandas` facade + `GeoDataFrame` wrapper mirror the `pandas` facade. Core never imports geopandas.

**Tech Stack:** Python 3.11+, geopandas, shapely, pyogrio, topojson (all under the `[geo]` extra), pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-geojson-topojson-vector-support-design.md` (D1, D3, D5–D8). **Format refs:** `docs/references/geojson.md`, `docs/references/topojson.md`.

**Depends on:** Phase 1 (`field_types` registry, `format`-driven resolution).

---

### Task 1: Add `AssetKind.GEOFEATURES` and the accessor

**Files:**
- Modify: `src/sunstone/asset.py` (`AssetKind` enum ~line 26; accessors ~line 60-83)
- Test: `tests/test_dataframe_coverage.py` (or a new `tests/test_asset.py`)

- [ ] **Step 1: Write the failing test**

```python
def test_geofeatures_kind_and_accessor():
    import pytest
    from sunstone.asset import Asset, AssetKind
    from sunstone.errors import IncompatibleAssetKindError
    from sunstone.lineage import Metadata

    payload = object()  # stand-in for a GeoDataFrame
    a = Asset(payload=payload, kind=AssetKind.GEOFEATURES, metadata=Metadata())
    assert a.as_geofeatures() is payload

    t = Asset(payload=[], kind=AssetKind.TABULAR, metadata=Metadata())
    with pytest.raises(IncompatibleAssetKindError):
        t.as_geofeatures()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dataframe_coverage.py::test_geofeatures_kind_and_accessor -v --no-cov`
Expected: FAIL — `AttributeError: GEOFEATURES` / `as_geofeatures`

- [ ] **Step 3: Add the enum member**

In `src/sunstone/asset.py`, in `AssetKind`, after `BLOB = "blob"`:

```python
    GEOFEATURES = "geofeatures"
```

- [ ] **Step 4: Add the accessor**

In `src/sunstone/asset.py`, alongside the other `as_*` accessors:

```python
    def as_geofeatures(self) -> Any:
        """Return the geopandas GeoDataFrame payload (typed Any: core has no geopandas dep)."""
        if self.kind is not AssetKind.GEOFEATURES:
            raise IncompatibleAssetKindError(expected=AssetKind.GEOFEATURES, actual=self.kind)
        return self.payload
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_dataframe_coverage.py::test_geofeatures_kind_and_accessor -v --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/sunstone/asset.py tests/test_dataframe_coverage.py
git commit -m "feat: add GEOFEATURES asset kind and accessor"
```

---

### Task 2: Declare the `[geo]` optional extra

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies]`)

- [ ] **Step 1: Add the extra**

In `pyproject.toml` under `[project.optional-dependencies]`, add:

```toml
geo = ["geopandas>=1.0", "shapely>=2.0", "pyogrio>=0.8", "topojson>=1.9"]
```

- [ ] **Step 2: Sync and verify import availability**

Run: `uv sync --extra geo`
Then: `uv run python -c "import geopandas, shapely, topojson; print('geo ok')"`
Expected: prints `geo ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add optional [geo] extra"
```

---

### Task 3: Handler skeleton + `geometry` field type (no geopandas at import)

**Files:**
- Create: `src/sunstone/handlers_geo.py`
- Test: `tests/test_handlers_geo.py`

- [ ] **Step 1: Write the failing test**

```python
def test_geo_handler_resolution_is_dependency_free():
    # This test must pass even without the [geo] extra installed.
    from sunstone.handlers_geo import GeoFeaturesFormatHandler
    from sunstone.asset import AssetKind

    h = GeoFeaturesFormatHandler()
    assert h.can_read("x.geojson", None)
    assert h.can_read("x.topojson", None)
    assert h.can_read("x.json", "geojson")
    assert not h.can_read("x.json", None)          # plain .json is NOT geo
    assert not h.can_read("x.csv", None)
    assert h.supported_kinds() == (AssetKind.GEOFEATURES,)


def test_geometry_field_type_descriptor_exposed():
    from sunstone.handlers_geo import GeoFeaturesFormatHandler
    names = {ft.name for ft in GeoFeaturesFormatHandler().field_types()}
    assert "geometry" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers_geo.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sunstone.handlers_geo'`

- [ ] **Step 3: Write the skeleton**

Create `src/sunstone/handlers_geo.py`:

```python
"""GeoJSON/TopoJSON format handler for AssetKind.GEOFEATURES.

geopandas/shapely/topojson are imported lazily inside read()/write() so that
importing this module (and resolving handlers) is dependency-free. Registered
only when the [geo] extra is importable — see PluginRegistry._register_builtins.
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
            "Reading/writing GeoJSON/TopoJSON requires the geo extra. "
            "Install it with: pip install sunstone-py[geo]"
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
        return (FieldTypeDescriptor(
            name="geometry",
            validate=_is_geometry,
            description="A geographic geometry (shapely) with a CRS.",
        ),)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers_geo.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers_geo.py tests/test_handlers_geo.py
git commit -m "feat: geo handler skeleton + geometry field type"
```

---

### Task 4: GeoJSON read (with `"sunstone"` extraction + default CRS)

**Files:**
- Modify: `src/sunstone/handlers_geo.py`
- Test: `tests/test_handlers_geo.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

geopandas = pytest.importorskip("geopandas")


def _fc():
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
             "properties": {"name": "A"}},
        ],
    }


def test_geojson_read_builds_geodataframe(tmp_path):
    import io
    from sunstone.handlers_geo import GeoFeaturesFormatHandler
    from sunstone.asset import AssetKind

    stream = io.BytesIO(json.dumps(_fc()).encode("utf-8"))
    asset = GeoFeaturesFormatHandler().read(stream, format="geojson", path="x.geojson")

    assert asset.kind == AssetKind.GEOFEATURES
    gdf = asset.payload
    assert list(gdf["name"]) == ["A"]
    assert gdf.geometry.iloc[0].x == 10.0
    assert gdf.crs.to_epsg() == 4326          # default per RFC 7946
    assert asset.extras.get("crs") is not None
```

(add `import json` at the top of the test module if not present)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers_geo.py::test_geojson_read_builds_geodataframe -v --no-cov`
Expected: FAIL — `GeoFeaturesFormatHandler` has no attribute `read`

- [ ] **Step 3: Implement `read` (GeoJSON branch)**

Add to `GeoFeaturesFormatHandler` in `src/sunstone/handlers_geo.py`:

```python
    def read(self, stream: BinaryIO, **kwargs: object) -> "Any":
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
```

(`_topojson_to_featurecollection` is implemented in Task 6; for now add a stub that raises `NotImplementedError` so the GeoJSON path compiles:)

```python
    def _topojson_to_featurecollection(self, doc: dict) -> dict:
        raise NotImplementedError  # implemented in Task 6
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers_geo.py::test_geojson_read_builds_geodataframe -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers_geo.py tests/test_handlers_geo.py
git commit -m "feat: GeoJSON read into GEOFEATURES asset"
```

---

### Task 5: GeoJSON write (no `crs` member, ring winding, `id`, `"sunstone"` embed)

**Files:**
- Modify: `src/sunstone/handlers_geo.py`
- Test: `tests/test_handlers_geo.py`

- [ ] **Step 1: Write the failing test**

```python
def test_geojson_write_roundtrip_and_conformance(tmp_path):
    import io, json
    from sunstone.handlers_geo import GeoFeaturesFormatHandler
    from sunstone.asset import Asset, AssetKind
    from sunstone.lineage import Metadata

    h = GeoFeaturesFormatHandler()
    src = io.BytesIO(json.dumps(_fc()).encode("utf-8"))
    asset = h.read(src, format="geojson", path="x.geojson")
    asset.metadata.slug = "pts"
    asset.metadata.name = "Points"

    out = io.BytesIO()
    h.write(asset, out, format="geojson", path="x.geojson")
    doc = json.loads(out.getvalue().decode("utf-8"))

    assert doc["type"] == "FeatureCollection"
    assert "crs" not in doc                      # RFC 7946: never emit crs
    assert doc["sunstone"]["slug"] == "pts" or doc["sunstone"].get("@graph")  # metadata embedded
    # round-trips back to a GeoDataFrame
    asset2 = h.read(io.BytesIO(out.getvalue()), format="geojson", path="x.geojson")
    assert asset2.metadata.slug == "pts"
    assert list(asset2.payload["name"]) == ["A"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers_geo.py::test_geojson_write_roundtrip_and_conformance -v --no-cov`
Expected: FAIL — no `write` method.

- [ ] **Step 3: Implement `write` (GeoJSON branch) + helpers**

Add to `GeoFeaturesFormatHandler`:

```python
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
            doc.pop("crs", None)             # belt-and-suspenders for older geopandas

        if metadata_obj is not None:
            doc[_SUNSTONE_KEY] = metadata_obj.to_jsonld()

        stream.write(json.dumps(doc).encode("utf-8"))

    @staticmethod
    def _orient_rings(gdf: "Any") -> "Any":
        """Right-hand rule per RFC 7946: exterior CCW, holes CW."""
        from shapely.geometry.polygon import orient
        from shapely.geometry.base import BaseGeometry

        def _fix(geom: "BaseGeometry"):
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
```

(`_geodataframe_to_topojson` is implemented in Task 7; add a stub raising `NotImplementedError`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers_geo.py::test_geojson_write_roundtrip_and_conformance -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers_geo.py tests/test_handlers_geo.py
git commit -m "feat: GeoJSON write with RFC 7946 conformance + metadata embed"
```

---

### Task 6: TopoJSON read (decode topology → features)

**Files:**
- Modify: `src/sunstone/handlers_geo.py` (`_topojson_to_featurecollection`)
- Test: `tests/test_handlers_geo.py`

Implements the decode algorithm from `docs/references/topojson.md` (delta-decode + scale/translate, arc stitch, negative-index reversal).

- [ ] **Step 1: Write the failing test**

```python
def test_topojson_read_decodes_line(tmp_path):
    import io, json
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    topo = {
        "type": "Topology",
        "transform": {"scale": [1.0, 1.0], "translate": [0.0, 0.0]},
        "objects": {"ex": {"type": "GeometryCollection", "geometries": [
            {"type": "LineString", "properties": {"k": "v"}, "arcs": [0]},
        ]}},
        "arcs": [[[0, 0], [2, 0], [0, 2]]],   # delta-encoded: (0,0)->(2,0)->(2,2)
    }
    asset = GeoFeaturesFormatHandler().read(
        io.BytesIO(json.dumps(topo).encode("utf-8")), format="topojson", path="x.topojson")
    line = asset.payload.geometry.iloc[0]
    assert list(line.coords) == [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)]
    assert list(asset.payload["k"]) == ["v"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers_geo.py::test_topojson_read_decodes_line -v --no-cov`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement the decoder**

Replace the `_topojson_to_featurecollection` stub in `src/sunstone/handlers_geo.py`:

```python
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
                x += p[0]; y += p[1]
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
                return {"type": "MultiPolygon",
                        "coordinates": [[stitch(r) for r in poly] for poly in g["arcs"]]}
            return None

        features = []
        for obj in topo.get("objects", {}).values():
            geometries = obj.get("geometries", [obj]) if obj.get("type") == "GeometryCollection" else [obj]
            for g in geometries:
                features.append({
                    "type": "Feature",
                    "geometry": to_geometry(g),
                    "properties": g.get("properties", {}) or {},
                    **({"id": g["id"]} if "id" in g else {}),
                })
        return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers_geo.py::test_topojson_read_decodes_line -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers_geo.py tests/test_handlers_geo.py
git commit -m "feat: TopoJSON decode (topology -> features)"
```

---

### Task 7: TopoJSON write (encode via `topojson`)

**Files:**
- Modify: `src/sunstone/handlers_geo.py` (`_geodataframe_to_topojson`)
- Test: `tests/test_handlers_geo.py`

- [ ] **Step 1: Write the failing test**

```python
def test_topojson_write_roundtrip(tmp_path):
    import io, json
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    h = GeoFeaturesFormatHandler()
    src = io.BytesIO(json.dumps(_fc()).encode("utf-8"))
    asset = h.read(src, format="geojson", path="x.geojson")
    asset.metadata.slug = "pts"; asset.metadata.name = "Points"

    out = io.BytesIO()
    h.write(asset, out, format="topojson", path="x.topojson")
    doc = json.loads(out.getvalue().decode("utf-8"))
    assert doc["type"] == "Topology"
    assert "sunstone" in doc

    back = h.read(io.BytesIO(out.getvalue()), format="topojson", path="x.topojson")
    assert back.payload.geometry.iloc[0].x == 10.0
    assert back.metadata.slug == "pts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers_geo.py::test_topojson_write_roundtrip -v --no-cov`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement the encoder**

Replace the `_geodataframe_to_topojson` stub:

```python
    def _geodataframe_to_topojson(self, gdf: "Any") -> dict:
        import topojson

        topo = topojson.Topology(gdf, prequantize=False)
        # topojson returns a JSON string; parse to a dict so we can attach metadata.
        return json.loads(topo.to_json())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_handlers_geo.py::test_topojson_write_roundtrip -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/handlers_geo.py tests/test_handlers_geo.py
git commit -m "feat: TopoJSON encode (features -> topology)"
```

---

### Task 8: Register the handler conditionally + missing-extra error

**Files:**
- Modify: `src/sunstone/plugins.py` (`_register_builtins`, ~lines 326-337)
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Write the failing test**

```python
def test_geo_handler_registered_when_geopandas_present():
    import pytest
    pytest.importorskip("geopandas")
    from sunstone.plugins import PluginRegistry

    reg = PluginRegistry()
    h = reg.find_format_reader("x.geojson", None)
    assert h is not None and type(h).__name__ == "GeoFeaturesFormatHandler"
    # geometry field type came along with the handler registration
    assert reg.field_types.get("geometry") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins.py::test_geo_handler_registered_when_geopandas_present -v --no-cov`
Expected: FAIL — no handler claims `.geojson`.

- [ ] **Step 3: Register conditionally**

In `src/sunstone/plugins.py` `_register_builtins`, next to the `NpzFormatHandler` block (before `BuiltinFormatHandler` is appended), add:

```python
        try:
            import geopandas  # noqa: F401
            from .handlers_geo import GeoFeaturesFormatHandler

            geo_handler = GeoFeaturesFormatHandler()
            self._format_handlers.append(geo_handler)  # type: ignore[arg-type]
            for descriptor in geo_handler.field_types():
                self.field_types.register(descriptor)
        except ImportError:
            pass  # [geo] extra not installed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugins.py::test_geo_handler_registered_when_geopandas_present -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/plugins.py tests/test_plugins.py
git commit -m "feat: register geo handler + geometry field type when [geo] present"
```

---

### Task 9: `sunstone.geopandas` facade + `GeoDataFrame` wrapper

**Files:**
- Create: `src/sunstone/geopandas.py`
- Test: `tests/test_geopandas.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
pytest.importorskip("geopandas")


def test_facade_read_geojson_and_lineage(tmp_path):
    import json
    from sunstone import geopandas as gpd
    import sunstone

    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n  - name: Pts\n    slug: pts\n    location: pts.geojson\n    format: geojson\n"
    )
    (tmp_path / "pts.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                      "properties": {"name": "A"}}],
    }))

    sunstone.set_project_path(tmp_path)
    gdf = gpd.read_geojson("pts")
    assert gdf.data.geometry.iloc[0].x == 1.0
    assert gdf.metadata.slug == "pts"


def test_to_geojson_requires_slug_and_name(tmp_path):
    import json
    from sunstone import geopandas as gpd
    import sunstone

    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n  - name: Pts\n    slug: pts\n    location: pts.geojson\n    format: geojson\n"
    )
    (tmp_path / "pts.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                      "properties": {}}],
    }))
    sunstone.set_project_path(tmp_path)
    gdf = gpd.read_geojson("pts")
    with pytest.raises(ValueError):
        gdf.to_geojson(str(tmp_path / "out.geojson"))   # no slug/name for a new output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geopandas.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sunstone.geopandas'`

- [ ] **Step 3: Implement the wrapper + facade**

Create `src/sunstone/geopandas.py`:

```python
"""Lineage-tracking geopandas facade. Requires the [geo] extra.

Mirrors `sunstone.pandas`: read functions resolve a slug/path against the
project's datasets.yaml and return a `GeoDataFrame` wrapper backed by an
Asset(kind=GEOFEATURES).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset import Asset, AssetKind
from .context import get_project_path
from .datasets import DatasetsManager
from .errors import DatasetNotFoundError
from .lineage import Metadata
from .plugins import PluginRegistry


class GeoDataFrame:
    """Wraps a geopandas.GeoDataFrame with sunstone metadata + lineage."""

    def __init__(self, asset: Asset) -> None:
        if asset.kind is not AssetKind.GEOFEATURES:
            raise ValueError("GeoDataFrame must wrap a GEOFEATURES asset")
        self._asset = asset

    @property
    def asset(self) -> Asset:
        return self._asset

    @property
    def data(self) -> Any:
        return self._asset.payload

    @property
    def metadata(self) -> Metadata:
        return self._asset.metadata

    def to_geojson(self, path: str | Path, *, slug: str | None = None, name: str | None = None) -> None:
        self._write(path, "geojson", slug, name)

    def to_topojson(self, path: str | Path, *, slug: str | None = None, name: str | None = None) -> None:
        self._write(path, "topojson", slug, name)

    def _write(self, path: str | Path, fmt: str, slug: str | None, name: str | None) -> None:
        if slug is not None:
            self._asset.metadata.slug = slug
        if name is not None:
            self._asset.metadata.name = name
        if not self._asset.metadata.slug or not self._asset.metadata.name:
            raise ValueError("Writing a new geo output requires both slug and name.")
        registry = PluginRegistry.get(get_project_path())
        handler = registry.find_format_writer(str(path), fmt)
        if handler is None:
            raise ValueError(f"No format handler for {fmt!r} (install sunstone-py[geo]).")
        url_handler = registry.find_url_handler(str(path))
        with url_handler.open(str(path), "wb") as stream:
            handler.write(self._asset, stream, format=fmt, path=str(path))


def _read(slug_or_path: str, fmt: str, project_path: str | Path | None) -> GeoDataFrame:
    project = Path(project_path) if project_path is not None else get_project_path()
    manager = DatasetsManager(project)
    dataset = manager.find_dataset_by_slug(slug_or_path)
    if dataset is None:
        raise DatasetNotFoundError(
            f"Dataset '{slug_or_path}' not found in datasets.yaml."
        )
    location = str(manager.get_absolute_path(dataset.location))
    registry = PluginRegistry.get(manager.project_path)
    handler = registry.find_format_reader(location, fmt)
    if handler is None:
        raise ValueError(f"No format handler for {fmt!r} (install sunstone-py[geo]).")
    url_handler = registry.find_url_handler(location)
    with url_handler.open(location, "rb") as stream:
        asset = handler.read(stream, format=fmt, path=location)
    if not asset.metadata.slug:
        asset.metadata.slug = dataset.slug
        asset.metadata.name = dataset.name
    return GeoDataFrame(asset)


def read_geojson(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    return _read(slug_or_path, "geojson", project_path)


def read_topojson(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    return _read(slug_or_path, "topojson", project_path)


def read_file(slug_or_path: str, project_path: str | Path | None = None) -> GeoDataFrame:
    """Auto-detect geojson vs topojson from the dataset's format/extension."""
    project = Path(project_path) if project_path is not None else get_project_path()
    manager = DatasetsManager(project)
    dataset = manager.find_dataset_by_slug(slug_or_path)
    fmt = (dataset.format if dataset and dataset.format else None)
    if fmt is None and dataset is not None and dataset.location.endswith(".topojson"):
        fmt = "topojson"
    return _read(slug_or_path, fmt or "geojson", project_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_geopandas.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sunstone/geopandas.py tests/test_geopandas.py
git commit -m "feat: sunstone.geopandas facade + GeoDataFrame wrapper"
```

---

### Task 10: End-to-end round-trip + missing-extra message + CHANGELOG

**Files:**
- Test: `tests/test_handlers_geo.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the missing-extra message test (runs without the extra)**

```python
def test_missing_geo_extra_message(monkeypatch):
    import io, builtins, pytest
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "geopandas":
            raise ImportError("no geopandas")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"sunstone-py\[geo\]"):
        GeoFeaturesFormatHandler().read(io.BytesIO(b"{}"), format="geojson", path="x.geojson")
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_handlers_geo.py::test_missing_geo_extra_message -v --no-cov`
Expected: PASS (the `_require_geo()` guard fires)

- [ ] **Step 3: Run the full geo + plugin + dataframe suites with the extra**

Run: `uv run pytest tests/test_handlers_geo.py tests/test_geopandas.py tests/test_plugins.py tests/test_dataframe.py --no-cov`
Expected: PASS

- [ ] **Step 4: Add CHANGELOG entry**

Under `[Unreleased]` in `CHANGELOG.md`:

```
- Added: GeoJSON and TopoJSON read/write via the optional [geo] extra.
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_handlers_geo.py CHANGELOG.md
git commit -m "test: geo end-to-end + missing-extra; changelog"
```

---

## Self-review notes

- Spec coverage: D1 (GEOFEATURES + accessor) → Task 1; D8 extra → Task 2; D5 handler/conformance → Tasks 3–7; D6 metadata embed → Tasks 5,7; D3 geometry field type → Tasks 3,8; D7 facade/wrapper → Task 9; resolution + missing-extra → Tasks 8,10.
- Open question O1 resolved in this plan as **hand-rolled decode** (Task 6, per `docs/references/topojson.md`) — no decode-only dependency. If `pyogrio`'s GDAL build exposes a TopoJSON driver, an implementer may substitute it in `_topojson_to_featurecollection` without changing the public surface.
- Names are consistent: `GeoFeaturesFormatHandler`, `as_geofeatures()`, `AssetKind.GEOFEATURES`, `field_types()`, `read_geojson/read_topojson/read_file`, `to_geojson/to_topojson`.
- Deferred to a follow-up (noted, not silently dropped): primary-geometry-column selection for *multiple* geometry columns (spec D3) — the handler currently relies on geopandas' single active geometry column; multi-geometry support can layer on without changing the kind or facade.
- The derive policy for GEOFEATURES (CRS invalidation on geometry-dropping derivations) is not required for read/write round-trips and is omitted here; add it when GeoDataFrame derivations are exercised, registering into `KIND_DERIVE_POLICIES` from the geo module to keep geopandas out of core.
