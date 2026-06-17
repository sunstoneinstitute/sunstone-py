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
