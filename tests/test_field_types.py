import pytest
from sunstone.field_types import (
    FieldTypeDescriptor,
    FieldTypeRegistry,
    validate_field_value,
    FieldTypeValidationError,
)


def test_builtin_scalar_types_present():
    reg = FieldTypeRegistry()
    for name in ("string", "integer", "number", "boolean", "date", "datetime", "any"):
        assert reg.get(name) is not None


def test_register_and_get_custom_type():
    reg = FieldTypeRegistry()
    desc = FieldTypeDescriptor(name="geometry", validate=lambda v: hasattr(v, "geom_type"))
    reg.register(desc)
    assert reg.get("geometry") is desc
    assert "geometry" in reg.known()


def test_validate_is_mode_gated():
    reg = FieldTypeRegistry()
    reg.register(FieldTypeDescriptor(name="geometry", validate=lambda v: v == "ok"))
    validate_field_value(reg, "geometry", "bad", strict=False)
    with pytest.raises(FieldTypeValidationError):
        validate_field_value(reg, "geometry", "bad", strict=True)
    validate_field_value(reg, "string", "anything", strict=True)
    validate_field_value(reg, "not-registered", "anything", strict=True)
