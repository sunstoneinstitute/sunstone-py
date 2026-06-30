"""geopandas reads should accept a file path, not only a slug."""

import json

import pytest

pytest.importorskip("geopandas")


def _make_geo_project(root):
    (root / "shapes.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "A"},
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                    }
                ],
            }
        )
    )
    (root / "datasets.yaml").write_text(
        "package:\n"
        "  title: Geo Test\n"
        '  version: "1.0.0"\n'
        "inputs:\n"
        "  - name: Shapes\n"
        "    slug: shapes\n"
        "    location: shapes.geojson\n"
        "    fields:\n"
        "      - name: name\n"
        "        type: string\n"
        "outputs: []\n"
    )


def test_read_geojson_by_path(tmp_path):
    from sunstone.geopandas import read_geojson

    _make_geo_project(tmp_path)
    gdf = read_geojson("shapes.geojson", project_path=tmp_path)
    assert len(gdf.data) == 1
    assert gdf.metadata.slug == "shapes"


def test_read_geojson_by_slug_still_works(tmp_path):
    from sunstone.geopandas import read_geojson

    _make_geo_project(tmp_path)
    gdf = read_geojson("shapes", project_path=tmp_path)
    assert len(gdf.data) == 1
