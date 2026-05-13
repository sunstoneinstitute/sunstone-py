from sunstone.component import ComponentSchema


def test_component_schema_required_fields():
    c = ComponentSchema(name="ndvi", component_kind="band")
    assert c.name == "ndvi"
    assert c.component_kind == "band"
    assert c.dtype is None
    assert c.units is None
    assert c.description is None
    assert c.custom_properties is None
    assert c.derived_from is None


def test_component_schema_full():
    c = ComponentSchema(
        name="temperature",
        component_kind="variable",
        dtype="float32",
        units="kelvin",
        description="2-metre air temperature",
        custom_properties={"sosa:observedProperty": "temperature"},
    )
    assert c.units == "kelvin"
    assert c.custom_properties["sosa:observedProperty"] == "temperature"


def test_component_kinds_documented():
    # Sanity: the four conventional component_kind values are accepted as strings.
    for kind in ("column", "band", "variable", "layer"):
        assert ComponentSchema(name="x", component_kind=kind).component_kind == kind
