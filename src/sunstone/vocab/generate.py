"""Render JSON Schemas and the key reference from the vocabulary data. Run via scripts/gen_schemas.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import DP_PROFILE_URL, aliases, config_keys, dp_keys, legacy_emitted_keys, level_children

SCHEMA_BASE = "https://sunstoneinstitute.github.io/sunstone-py/schemas/"
RDF_KEY_PATTERNS: dict[str, Any] = {"^[A-Za-z][A-Za-z0-9_-]*:[^\\s]+$": {}, "^https?://": {}}
ARRAY_KEYS = frozenset({"inputs", "outputs", "packages", "contributors", "sources", "licenses", "fields", "resources"})
# Levels whose objects may carry a JSON-LD "@id" IRI. Agent objects and RDF object values are unconstrained.
ID_LEVELS = frozenset({"source"})
YAML_LEVELS = (
    "document",
    "dataset",
    "source",
    "schema",
    "field",
    "constraints",
    "license",
    "dialect",
    "package",
    "contributor",
    "publish",
    "lint",
    "defaults",
    "node",
)
DP_LEVELS = (
    "package",
    "resource",
    "source",
    "schema",
    "field",
    "constraints",
    "license",
    "dialect",
    "contributor",
    "node",
)
LEVEL_PATHS = {
    "document": ".",
    "dataset": "inputs / outputs",
    "source": "inputs.source",
    "schema": "inputs.schema",
    "field": "inputs.schema.fields",
    "constraints": "inputs.schema.fields.constraints",
    "license": "inputs.licenses / package.licenses",
    "dialect": "inputs.dialect",
    "package": "package / packages",
    "contributor": "package.contributors",
    "publish": "publish",
    "lint": "lint",
    "defaults": "defaults",
    "node": "<any RDF property object value>",
}
EXAMPLES: dict[tuple[str, str], str] = {
    ("document", "include"): "include: [data/extra.yaml]",
    ("document", "rdfPrefixes"): "rdfPrefixes: {ex: https://example.org/ns#}",
    ("document", "min_sunstone_version"): 'min_sunstone_version: "1.20.0"',
    ("document", "dcat-si:methodology"): "dcat-si:methodology: METHODOLOGY.md",
    ("dataset", "dct:temporal"): "dct:temporal: '2020/2024'",
    ("dataset", "dct:spatial"): "dct:spatial: Norway",
    ("dataset", "dcat:theme"): "dcat:theme: https://sunstone.institute/rdf/threats#01",
    ("dataset", "dcat:keyword"): "dcat:keyword: [aquaculture, salmon]",
    ("field", "sosa:observedProperty"): "sosa:observedProperty: http://qudt.org/vocab/quantitykind/Temperature",
    ("field", "qudt:hasQuantityKind"): "qudt:hasQuantityKind: http://qudt.org/vocab/quantitykind/Area",
    ("dataset", "title"): "title: Official UN Member States",
    ("dataset", "name"): "name: un-member-states",
    ("dataset", "path"): "path: inputs/un_members.csv",
    ("dataset", "description"): "description: One row per member state.",
    ("dataset", "licenses"): "licenses: [{name: CC-BY-4.0}]",
    ("dataset", "source"): "source: {title: ..., dcat:downloadURL: ...}",
    ("dataset", "schema"): "schema: {fields: [...], primaryKey: id}",
    ("dataset", "prov:generatedAtTime"): "prov:generatedAtTime: '2026-01-02'",
    ("dataset", "prov:wasGeneratedBy"): "prov:wasGeneratedBy: {'@type': prov:Activity, dct:type: manual-download}",
    ("dataset", "prov:wasQuotedFrom"): "prov:wasQuotedFrom: un-member-states",
    ("source", "@id"): '"@id": https://doi.org/10.1016/j.aqrep.2022.101316',
    ("source", "title"): "title: UN Member States Authority File",
    ("source", "dcat:downloadURL"): "dcat:downloadURL: https://example.org/data.csv",
    ("source", "dcat:landingPage"): "dcat:landingPage: https://example.org/about",
    ("source", "dct:publisher"): (
        "dct:publisher: {rdfs:label: Food and Agriculture Organization of the United Nations, skos:altLabel: FAO}"
    ),
    ("source", "dct:creator"): "dct:creator: [{rdfs:label: 'Aas, T. S.'}, {rdfs:label: 'Asgard, T. E.'}]",
    ("source", "dct:issued"): "dct:issued: '2022'",
    ("source", "dct:isPartOf"): "dct:isPartOf: {rdfs:label: 'Aquaculture Reports 26, 101316'}",
    ("source", "dct:bibliographicCitation"): (
        "dct:bibliographicCitation: 'Aas, T. S. & Asgard, T. E. (2022). Title. Aquaculture Reports 26.'"
    ),
    ("source", "prov:wasAttributedTo"): (
        "prov:wasAttributedTo: 'Aas, T. S.; Asgard, T. E. (Nofima); published by Elsevier'"
    ),
    ("source", "dct:license"): "dct:license: CC-BY-4.0",
    ("source", "dct:modified"): "dct:modified: '2026-01-01'",
    ("source", "dct:rights"): (
        "dct:rights: {rdfs:label: 'Permission from Example Org', dct:license: CC-BY-4.0, dct:date: '2026-10-19'}"
    ),
    ("field", "name"): "name: gdp_usd",
    ("field", "type"): "type: number",
    ("field", "title"): "title: GDP (USD)",
    ("field", "description"): "description: Gross domestic product.",
    ("field", "si:unit"): "si:unit: USD",
    ("package", "title"): "title: UN Member States Dataset",
    ("package", "licenses"): "licenses: [{name: CC-BY-4.0}]",
}

DESCRIPTION_OVERRIDES: dict[tuple[str, str], str] = {
    ("dataset", "prov:wasGeneratedBy"): (
        "How the data was obtained: a prov:Activity node, e.g. {dct:type: manual-download}."
    ),
    ("dataset", "source"): (
        "Single upstream source of an input; emitted as Data Package sources[0]. "
        "Use `source` in datasets.yaml, not the Data Package `sources` array."
    ),
}
ONE_OF_SOURCE_KEYS = frozenset({"@id", "dcat:downloadURL", "dcat:landingPage"})
SOURCE_NOTE = (
    '`"@id"`, `dcat:downloadURL` and `dcat:landingPage` are marked MUST (one of): at least one is required (R102).'
)
FULL_EXAMPLE = """\
min_sunstone_version: 1.20.0
dcat-si:methodology: METHODOLOGY.md
inputs:
  - name: fish-farms
    title: Fish Farms
    description: Salmon farms by site.
    path: inputs/fish_farms.csv
    prov:generatedAtTime: '2026-01-02'
    prov:wasGeneratedBy: {dct:type: manual-download}
    source:
      "@id": https://doi.org/10.1016/j.aqrep.2022.101316
      title: Salmon farm survey
      dct:publisher: &pub
        rdfs:label: Elsevier
        skos:altLabel: ELS
      dct:creator:
        - rdfs:label: 'Aas, T. S.'
      dct:issued: '2022'
      dct:modified: '2022-06-01'
      dct:isPartOf: {rdfs:label: 'Aquaculture Reports 26, 101316'}
      dct:license: CC-BY-4.0
  - name: feed-prices
    title: Feed Prices
    description: Monthly feed prices.
    path: inputs/feed_prices.csv
    prov:generatedAtTime: '2026-01-03'
    prov:wasGeneratedBy: {dct:type: manual-download}
    source:
      dcat:downloadURL: https://example.org/feed.csv
      title: Feed price series
      dct:publisher: *pub
      dct:issued: '2025'
      dct:modified: '2025-06-01'
      dct:license: CC-BY-4.0
"""


def _level_schema(level: str, keys: set[str], defs_available: set[str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    children = level_children(level)
    for key in sorted(keys):
        child = children.get(key)
        if child in defs_available:
            ref = {"$ref": f"#/definitions/{child}"}
            props[key] = {"type": "array", "items": ref} if key in ARRAY_KEYS else ref
        else:
            props[key] = {}
    if level in ID_LEVELS:
        props["@id"] = {"type": "string"}
    out: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "patternProperties": dict(RDF_KEY_PATTERNS),
        "additionalProperties": False,
    }
    if level == "node":
        out["properties"] = {"@id": {"type": "string"}, "@type": {"type": "string"}}
    return out


def render_datasets_schema() -> dict[str, Any]:
    levels = set(YAML_LEVELS)
    defs = {lvl: _level_schema(lvl, set(dp_keys(lvl)) | set(config_keys(lvl)), levels) for lvl in YAML_LEVELS}
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": SCHEMA_BASE + "datasets.schema.json",
        "title": "sunstone datasets.yaml",
        "description": "Keys are Data Package 2.0 properties, sunstone config keys, or RDF properties (prefix:local or IRI).",
        "$ref": "#/definitions/document",
        "definitions": defs,
    }


def render_datapackage_profile() -> dict[str, Any]:
    levels = set(DP_LEVELS)
    defs = {lvl: _level_schema(lvl, set(dp_keys(lvl)) | set(legacy_emitted_keys(lvl)), levels) for lvl in DP_LEVELS}
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": SCHEMA_BASE + "datapackage-profile.json",
        "title": "sunstone Data Package profile",
        "description": f"Data Package 2.0 ({DP_PROFILE_URL}) with extras restricted to prefixed names or IRIs.",
        "$ref": "#/definitions/package",
        "definitions": defs,
    }


def _example_path(level: str) -> str:
    return {
        "document": "",
        "dataset": "inputs",
        "source": "inputs.source",
        "schema": "inputs.schema",
        "field": "inputs.schema.fields",
        "constraints": "inputs.schema.fields.constraints",
        "license": "inputs.licenses",
        "dialect": "inputs.dialect",
        "package": "package",
        "contributor": "package.contributors",
        "publish": "publish",
        "lint": "lint",
        "defaults": "defaults",
    }[level]


def render_reference_md() -> str:
    from ..rules import RULES
    from ..vocab_search import explain

    lines = [
        "---",
        'description: "Every allowed datasets.yaml key at each level, with its source vocabulary and rule level."',
        "---",
        "",
        "# datasets.yaml key reference",
        "",
        "Generated by `scripts/gen_schemas.py` from `src/sunstone/vocab/`. Do not edit by hand.",
        "",
        "Every key is one of: a Data Package 2.0 property (`dp`) for its level, a sunstone config key (`config`), "
        "a JSON-LD keyword (`jsonld`), or an RDF property (`rdf`: `prefix:local` or an absolute IRI). "
        "RDF properties are allowed at every level; the rows marked `rdf` below are the ones a rule asks for. "
        "Rule levels follow RFC 2119 (`MUST`, `SHOULD`, `MAY`).",
        "",
        "Editor support: add `# yaml-language-server: $schema=" + SCHEMA_BASE + "datasets.schema.json` "
        "as the first line of `datasets.yaml`.",
        "",
        "## Agents and identifiers",
        "",
        "Agent objects (`dct:publisher`, each `dct:creator` entry) carry `rdfs:label` (full name), "
        'optional `skos:altLabel` (short name) and optional `"@id"` (IRI). '
        "Repeat an agent within one file with a YAML anchor: "
        "`dct:publisher: &fao {rdfs:label: ..., skos:altLabel: FAO}` on first use, `dct:publisher: *fao` after. "
        "Anchors do not cross include files.",
        "",
        'A source with a DOI puts it in `"@id"`: `"@id": https://doi.org/10.1016/j.aqrep.2022.101316`.',
        "",
    ]
    for level in YAML_LEVELS:
        if level == "node":
            continue
        lines += [
            f"## {level.capitalize()}",
            "",
            f"Path: `{LEVEL_PATHS[level]}`",
            "",
            "| Key | Class | Rule | Description | Example |",
            "|---|---|---|---|---|",
        ]
        for info in explain(_example_path(level)):
            example = EXAMPLES.get((level, info.key), f"{info.key}: ...")
            rule_text = info.rule_level
            if level == "source" and info.key in ONE_OF_SOURCE_KEYS:
                rule_text += " (one of)"
            definition = DESCRIPTION_OVERRIDES.get((level, info.key), info.definition)
            lines.append(f"| `{info.key}` | {info.cls} | {rule_text} | {definition} | `{example}` |")
        lines.append("")
        if level == "source":
            lines[-1:] = [SOURCE_NOTE, ""]
    lines += ["## Complete example", "", "```yaml", FULL_EXAMPLE.rstrip("\n"), "```", ""]
    lines += ["## Aliases (old key to new key)", "", "| Level | Old | New |", "|---|---|---|"]
    for level, entries in aliases().items():
        for e in entries:
            lines.append(f"| {level} | `{e['old']}` | `{e['new']}` |")
    lines += ["", "## Rules", "", "| Rule | Level | Category | Title |", "|---|---|---|---|"]
    for rule in sorted(RULES.values(), key=lambda r: r.id):
        lines.append(f"| {rule.id} | {rule.level.value} | {rule.category.value} | {rule.title} |")
    lines.append("")
    return "\n".join(lines)


def write_all(root: Path) -> list[Path]:
    out = [
        (root / "schemas" / "datasets.schema.json", json.dumps(render_datasets_schema(), indent=2) + "\n"),
        (root / "schemas" / "datapackage-profile.json", json.dumps(render_datapackage_profile(), indent=2) + "\n"),
        (root / "docs" / "datasets-yaml-reference.md", render_reference_md()),
    ]
    for path, text in out:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return [p for p, _ in out]
