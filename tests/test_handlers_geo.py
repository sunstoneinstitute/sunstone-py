import json

import pytest


def test_geo_handler_resolution_is_dependency_free():
    # This test must pass even without the [geo] extra installed.
    from sunstone.handlers_geo import GeoFeaturesFormatHandler
    from sunstone.asset import AssetKind

    h = GeoFeaturesFormatHandler()
    assert h.can_read("x.geojson", None)
    assert h.can_read("x.topojson", None)
    assert h.can_read("x.json", "geojson")
    assert not h.can_read("x.json", None)  # plain .json is NOT geo
    assert not h.can_read("x.csv", None)
    assert h.supported_kinds() == (AssetKind.GEOFEATURES,)


def test_geometry_field_type_descriptor_exposed():
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    names = {ft.name for ft in GeoFeaturesFormatHandler().field_types()}
    assert "geometry" in names


geopandas = pytest.importorskip("geopandas")


def _fc():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                "properties": {"name": "A"},
            },
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
    assert gdf.crs.to_epsg() == 4326  # default per RFC 7946
    assert asset.extras.get("crs") is not None


def test_geojson_write_roundtrip_and_conformance(tmp_path):
    import io
    from sunstone.handlers_geo import GeoFeaturesFormatHandler

    h = GeoFeaturesFormatHandler()
    src = io.BytesIO(json.dumps(_fc()).encode("utf-8"))
    asset = h.read(src, format="geojson", path="x.geojson")
    asset.metadata.slug = "pts"
    asset.metadata.name = "Points"

    out = io.BytesIO()
    h.write(asset, out, format="geojson", path="x.geojson")
    doc = json.loads(out.getvalue().decode("utf-8"))

    assert doc["type"] == "FeatureCollection"
    assert "crs" not in doc  # RFC 7946: never emit crs
    assert doc["sunstone"]["dct:identifier"] == "pts" or doc["sunstone"].get("@graph")
    asset2 = h.read(io.BytesIO(out.getvalue()), format="geojson", path="x.geojson")
    assert asset2.metadata.slug == "pts"
    assert list(asset2.payload["name"]) == ["A"]
