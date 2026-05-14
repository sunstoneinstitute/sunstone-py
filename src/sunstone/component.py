"""Per-component metadata: columns, bands, variables, layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, List

from .lineage import FieldDerivation


@dataclass
class ComponentSchema:
    """Neutral per-component metadata.

    The same shape covers tabular columns, raster bands, array variables, and
    tile layers. Used by the discovery layer for cross-kind queries.

    `component_kind` is a free string ("column", "band", "variable", "layer", ...)
    rather than an enum so external plugins can introduce new component kinds
    without an upstream change.
    """

    name: str
    component_kind: str
    dtype: Optional[str] = None
    units: Optional[str] = None  # Pint-parsable; emitted as qudt:unit IRI
    description: Optional[str] = None
    custom_properties: Optional[dict[str, Any]] = None
    derived_from: Optional[List[FieldDerivation]] = None
