"""RDF value wrappers used in `Metadata.custom_properties`.

Users write plain Python literals (str, int, float, bool, datetime, Decimal) for
most values. These three thin wrappers cover the cases where Python's type system
can't distinguish what RDF object is intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class IRI(str):
    """An IRI reference.

    Subclasses `str` so it stays string-comparable and JSON-friendly, but
    `isinstance(x, IRI)` distinguishes it from a string literal. Prefix
    resolution (e.g., `sosa:NDVI` → full URI) happens at JSON-LD serialise time
    using `Metadata.rdf_prefixes`.
    """

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return f"IRI({str.__repr__(self)})"


@dataclass(frozen=True)
class LangString:
    """A language-tagged literal. Serialises to JSON-LD as
    `{"@value": ..., "@language": ...}`."""

    value: str
    lang: str  # BCP-47 tag, e.g., "en", "fr-CA"


@dataclass(frozen=True)
class TypedLiteral:
    """A literal with an explicit XSD datatype. Use when Python-type inference
    would pick the wrong xsd type. Serialises to JSON-LD as
    `{"@value": ..., "@type": ...}`."""

    value: Any
    datatype: str  # e.g., "xsd:double"
