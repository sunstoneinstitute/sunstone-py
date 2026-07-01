"""Polars facade metadata accessors + set_field_metadata.

Mirrors sunstone.pandas.metadata.MetadataMixin; kept as a separate copy
so the polars package has no runtime dependency on the pandas package.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Dict, Optional

from sunstone.lineage import FieldSchema, LineageMetadata, Metadata

if TYPE_CHECKING:
    from .core import DataFrame  # noqa: F401  (type hint only)


class MetadataMixin:
    """Metadata property accessors and field-metadata helpers.

    Assumes the concrete subclass provides ``metadata`` (a
    :class:`~sunstone.lineage.Metadata` instance).
    """

    if TYPE_CHECKING:

        @property
        def metadata(self) -> Metadata: ...

    @property
    def lineage(self) -> LineageMetadata:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.metadata.lineage

    @lineage.setter
    def lineage(self, value: LineageMetadata) -> None:
        """Deprecated: use .metadata.lineage instead."""
        warnings.warn(
            "DataFrame.lineage is deprecated, use DataFrame.metadata.lineage",
            DeprecationWarning,
            stacklevel=2,
        )
        self.metadata.lineage = value

    @property
    def description(self) -> Optional[str]:
        return self.metadata.description

    @description.setter
    def description(self, value: Optional[str]) -> None:
        self.metadata.description = value

    @property
    def rdf_prefixes(self) -> Optional[Dict[str, str]]:
        return self.metadata.rdf_prefixes

    @rdf_prefixes.setter
    def rdf_prefixes(self, value: Optional[Dict[str, str]]) -> None:
        self.metadata.rdf_prefixes = value

    @property
    def custom_properties(self) -> Optional[Dict[str, Any]]:
        return self.metadata.custom_properties

    @custom_properties.setter
    def custom_properties(self, value: Optional[Dict[str, Any]]) -> None:
        self.metadata.custom_properties = value

    @property
    def unit_display(self) -> str:
        """Unit display mode: 'transparent' (default) or 'explicit'."""
        return getattr(self, "_unit_display", "transparent")

    @unit_display.setter
    def unit_display(self, value: str) -> None:
        self._unit_display = value

    def set_field_metadata(
        self,
        column: str,
        *,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        source: Optional[str] = None,
        type: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
    ) -> "DataFrame":
        """Set metadata for a column. Returns self for chaining.

        Args:
            column: Column name to annotate.
            description: Human-readable description of the field.
            unit: Unit of measure (e.g., 'kg', 'students').
            source: Slug of the input dataset this field comes from.
            type: Data type override. If None, inferred from dtype at write time.
            constraints: Optional constraints (e.g., enum values).
            custom_properties: Optional field-level custom properties.

        Returns:
            self, for method chaining.
        """
        if unit is not None:
            from sunstone.units import get_unit_mode, parse_unit_string

            if get_unit_mode() != "relaxed":
                parse_unit_string(unit)  # raises UnitError if invalid in strict/auto mode

        existing = self.metadata.field_metadata.get(column)
        if existing:
            if description is not None:
                existing.description = description
            if unit is not None:
                existing.unit = unit
            if source is not None:
                existing.source = source
            if type is not None:
                existing.type = type
            if constraints is not None:
                existing.constraints = constraints
            if custom_properties is not None:
                merged = dict(existing.custom_properties or {})
                merged.update(custom_properties)
                existing.custom_properties = merged or None
        else:
            self.metadata.field_metadata[column] = FieldSchema(
                name=column,
                type=type,
                description=description,
                unit=unit,
                source=source,
                constraints=constraints,
                custom_properties=custom_properties or None,
            )

        if source is not None:
            from sunstone.lineage import FieldDerivation

            fd = FieldDerivation(output_field=column, source_entity=source)
            if self.metadata.lineage.field_derivations is None:
                self.metadata.lineage.field_derivations = []
            self.metadata.lineage.field_derivations = [
                d for d in self.metadata.lineage.field_derivations if d.output_field != column
            ]
            self.metadata.lineage.field_derivations.append(fd)

        return self  # type: ignore[return-value]
