import json

import pytest

pytest.importorskip("geopandas")


def test_facade_read_geojson_and_lineage(tmp_path):
    from sunstone import geopandas as gpd
    import sunstone

    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n  - name: Pts\n    slug: pts\n    location: pts.geojson\n    format: geojson\n"
    )
    (tmp_path / "pts.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                        "properties": {"name": "A"},
                    }
                ],
            }
        )
    )

    sunstone.set_project_path(tmp_path)
    gdf = gpd.read_geojson("pts")
    assert gdf.data.geometry.iloc[0].x == 1.0
    assert gdf.metadata.slug == "pts"


def test_to_geojson_requires_slug_and_name(tmp_path):
    from sunstone import geopandas as gpd
    import sunstone

    (tmp_path / "datasets.yaml").write_text(
        "inputs:\n  - name: Pts\n    slug: pts\n    location: pts.geojson\n    format: geojson\n"
    )
    (tmp_path / "pts.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                        "properties": {},
                    }
                ],
            }
        )
    )
    sunstone.set_project_path(tmp_path)
    gdf = gpd.read_geojson("pts")
    # Clear inherited slug/name so a brand-new output requires them explicitly.
    gdf.metadata.slug = None
    gdf.metadata.name = None
    with pytest.raises(ValueError):
        gdf.to_geojson(str(tmp_path / "out.geojson"))  # no slug/name for a new output
