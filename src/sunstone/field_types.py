"""Registry of field (column) value-types for dataset schemas.

Built-in scalar types mirror the Frictionless Table Schema vocabulary. Plugins
extend this with structured/domain types (e.g. the geo extra's ``geojson`` cell contract) via
``FieldTypeDescriptor`` — see ``PluginRegistry`` classification. This is the
extensibility seam for non-scalar columns; the geo extra is the first consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


class FieldTypeValidationError(ValueError):
    """A field value failed its registered type contract in strict mode."""


@dataclass(frozen=True)
class FieldTypeDescriptor:
    """Describes a field (column) value-type.

    ``validate`` is an optional cell-level contract: it returns True for a
    valid value. ``None`` means "no contract" (always accepted).
    """

    name: str
    validate: Optional[Callable[[Any], bool]] = None
    description: Optional[str] = None


# Frictionless Table Schema field types (plus "any"). The geo extra re-registers "geojson" with a cell contract.
_BUILTIN_SCALAR_TYPES: tuple[str, ...] = (
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "date",
    "datetime",
    "time",
    "year",
    "yearmonth",
    "duration",
    "geopoint",
    "geojson",
    "any",
)


class FieldTypeRegistry:
    """Holds known field value-types, keyed by name."""

    def __init__(self) -> None:
        self._types: dict[str, FieldTypeDescriptor] = {
            name: FieldTypeDescriptor(name=name) for name in _BUILTIN_SCALAR_TYPES
        }

    def register(self, descriptor: FieldTypeDescriptor) -> None:
        self._types[descriptor.name] = descriptor

    def get(self, name: str) -> Optional[FieldTypeDescriptor]:
        return self._types.get(name)

    def known(self) -> tuple[str, ...]:
        return tuple(self._types)


def validate_field_value(registry: FieldTypeRegistry, type_name: str, value: Any, *, strict: bool) -> None:
    """Validate ``value`` against the contract for ``type_name``.

    No-op when the type is unknown or has no contract. In strict mode a failed
    contract raises ``FieldTypeValidationError``; in lenient mode it is ignored.
    """
    descriptor = registry.get(type_name)
    if descriptor is None or descriptor.validate is None:
        return
    if not descriptor.validate(value) and strict:
        raise FieldTypeValidationError(f"Value {value!r} is not valid for field type {type_name!r}")
