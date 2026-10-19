"""Regenerate src/sunstone/vocab/<prefix>.json from upstream vocabularies.

Usage:
    uv run --group vocab python scripts/sync_vocab.py [--rdf-registry PATH] [--only PREFIX ...]

Upstream files are pinned below. ``si`` and ``dcat-si`` are read from a local
rdf-registry checkout (default: ~/git/sunstone/rdf-registry).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import rdflib
from rdflib import DCTERMS, OWL, RDF, RDFS, SKOS, URIRef

OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "sunstone" / "vocab"

# prefix -> (namespace recorded in JSON, source, rdflib format, extra namespace spellings accepted in the file)
SOURCES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "dct": (
        "http://purl.org/dc/terms/",
        "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/dublin_core_terms.ttl",
        "turtle",
        (),
    ),
    "dcat": ("http://www.w3.org/ns/dcat#", "https://www.w3.org/ns/dcat.ttl", "turtle", ()),
    "prov": ("http://www.w3.org/ns/prov#", "https://www.w3.org/ns/prov-o.ttl", "turtle", ()),
    "schema": (
        "http://schema.org/",
        "https://schema.org/version/latest/schemaorg-current-https.ttl",
        "turtle",
        ("https://schema.org/",),
    ),
    "skos": ("http://www.w3.org/2004/02/skos/core#", "https://www.w3.org/2009/08/skos-reference/skos.rdf", "xml", ()),
    "rdfs": ("http://www.w3.org/2000/01/rdf-schema#", "https://www.w3.org/2000/01/rdf-schema.ttl", "turtle", ()),
    "qudt": ("http://qudt.org/schema/qudt/", "https://qudt.org/3.1.4/schema/qudt.ttl", "turtle", ()),
    "sosa": ("http://www.w3.org/ns/sosa/", "https://www.w3.org/ns/sosa/sosa.ttl", "turtle", ()),
    "si": ("https://sunstone.institute/rdf/vocab#", "rdf/vocab.ttl", "turtle", ()),
    "dcat-si": ("https://sunstone.institute/rdf/data#", "rdf/data.ttl", "turtle", ()),
}

PROPERTY_TYPES = {
    RDF.Property,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.FunctionalProperty,
}
LABEL_PREDICATES = (RDFS.label, DCTERMS.title, SKOS.prefLabel)
DEFINITION_PREDICATES = (RDFS.comment, SKOS.definition, DCTERMS.description)


def _first_literal(g: rdflib.Graph, s: URIRef, predicates: tuple[URIRef, ...]) -> str:
    for p in predicates:
        values = [o for o in g.objects(s, p) if isinstance(o, rdflib.Literal)]
        if not values:
            continue
        english = [v for v in values if (v.language or "en").startswith("en")]
        chosen = english[0] if english else values[0]
        return " ".join(str(chosen).split())
    return ""


def build(prefix: str, registry: Path) -> dict[str, Any]:
    namespace, source, fmt, extra_ns = SOURCES[prefix]
    location = str(registry / source) if not source.startswith("http") else source
    g = rdflib.Graph()
    g.parse(location, format=fmt)
    accepted = (namespace,) + extra_ns
    terms: dict[str, dict[str, str]] = {}
    for s in set(g.subjects(RDF.type, None)):
        if not isinstance(s, URIRef):
            continue
        if not any(t in PROPERTY_TYPES for t in g.objects(s, RDF.type)):
            continue
        iri = str(s)
        ns_hit = next((ns for ns in accepted if iri.startswith(ns)), None)
        if ns_hit is None:
            continue
        local = iri[len(ns_hit) :]
        if not local or "/" in local or "#" in local:
            continue
        terms[local] = {
            "curie": f"{prefix}:{local}",
            "iri": namespace + local,
            "label": _first_literal(g, s, LABEL_PREDICATES),
            "definition": _first_literal(g, s, DEFINITION_PREDICATES),
        }
    return {
        "prefix": prefix,
        "namespace": namespace,
        "source": source,
        "terms": [terms[k] for k in sorted(terms)],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rdf-registry", default=str(Path.home() / "git" / "sunstone" / "rdf-registry"))
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    registry = Path(args.rdf_registry)
    for prefix in args.only or SOURCES:
        data = build(prefix, registry)
        if not data["terms"]:
            print(f"error: no properties found for {prefix}", file=sys.stderr)
            return 1
        out = OUT_DIR / f"{prefix}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"{prefix}: {len(data['terms'])} terms -> {out.relative_to(OUT_DIR.parent.parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
