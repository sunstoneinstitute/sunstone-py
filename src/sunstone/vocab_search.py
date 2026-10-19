"""Linear-scan search over shipped vocabularies and descriptor keys (``sunstone vocab search``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .conformance import KEY_LEVELS, split_camel
from .rules import Level
from .vocab import Term, all_terms, config_keys, dp_keys, key_definition, level_for_path

SOURCE_ORDER: tuple[str, ...] = (
    "dp",
    "config",
    "dct",
    "dcat",
    "prov",
    "schema",
    "skos",
    "rdfs",
    "qudt",
    "sosa",
    "si",
    "dcat-si",
)
_DP_LEVEL_ALIAS = {"dataset": "resource"}
_RULE_ORDER = {"MUST": 0, "MUST NOT": 0, "SHOULD": 1, "MAY": 2}
_JSONLD_DEFINITIONS = {
    "@id": "JSON-LD identifier of the node. On a source: the DOI as https://doi.org/<doi>, or another persistent IRI.",
    "@type": "JSON-LD type of the node, e.g. prov:Activity.",
}


@dataclass(frozen=True)
class KeyInfo:
    key: str
    cls: str
    level: str
    rule_level: str
    rule_id: Optional[str]
    definition: str


def _match_fields(term: Term) -> tuple[str, str, str, str]:
    local = term.curie.split(":", 1)[1] if term.iri else term.curie
    return (f"{local} {split_camel(local)}".lower(), term.curie.lower(), term.label.lower(), term.definition.lower())


def _tier(word: str, fields: tuple[str, str, str, str]) -> Optional[int]:
    if word in fields[0] or word in fields[1]:
        return 1
    if word in fields[2]:
        return 2
    if word in fields[3]:
        return 3
    return None


def _resolve_level(at: Optional[str]) -> Optional[str]:
    if at is None:
        return None
    level = level_for_path(at)
    if level is None:
        raise ValueError(f"unknown datasets.yaml path: {at!r}")
    return level


def _allowed_at(term: Term, level: str) -> bool:
    if term.source == "dp":
        return _DP_LEVEL_ALIAS.get(level, level) in term.levels
    return level in term.levels


def search(query: str, *, at: Optional[str] = None, limit: int = 20) -> list[Term]:
    words = query.lower().split()
    level = _resolve_level(at)
    scored: list[tuple[int, int, str, Term]] = []
    for term in all_terms():
        if level is not None and term.source in ("dp", "config") and not _allowed_at(term, level):
            continue
        fields = _match_fields(term)
        tiers = [_tier(w, fields) for w in words]
        if not words or any(t is None for t in tiers):
            continue
        best = max(t for t in tiers if t is not None)
        scored.append((best, SOURCE_ORDER.index(term.source), term.curie, term))
    scored.sort(key=lambda s: s[:3])
    return [s[3] for s in scored[:limit]]


def explain(at: str) -> list[KeyInfo]:
    level = _resolve_level(at)
    assert level is not None
    infos: dict[str, KeyInfo] = {}
    for key in dp_keys(level):
        infos[key] = KeyInfo(key, "dp", level, "MAY", None, key_definition(level, key))
    for key in config_keys(level):
        infos[key] = KeyInfo(key, "config", level, "MAY", None, key_definition(level, key))
    for (lvl, key), (rule_level, rule_id) in KEY_LEVELS.items():
        if lvl != level:
            continue
        existing = infos.get(key)
        cls = (
            existing.cls
            if existing
            else ("config" if key in config_keys(level) else "jsonld" if key.startswith("@") else "rdf")
        )
        definition = existing.definition if existing else _JSONLD_DEFINITIONS.get(key) or _rdf_definition(key)
        infos[key] = KeyInfo(key, cls, level, rule_level.value, rule_id, definition)
    return sorted(infos.values(), key=lambda k: (_RULE_ORDER[k.rule_level], k.key))


def _rdf_definition(curie: str) -> str:
    for term in all_terms():
        if term.curie == curie and term.iri:
            return term.definition
    return ""


def term_to_dict(term: Term) -> dict[str, Any]:
    return {
        "curie": term.curie,
        "iri": term.iri,
        "label": term.label,
        "definition": term.definition,
        "source": term.source,
        "levels": list(term.levels),
    }


def key_info_to_dict(info: KeyInfo) -> dict[str, Any]:
    return {
        "key": info.key,
        "class": info.cls,
        "level": info.level,
        "rule": info.rule_level,
        "rule_id": info.rule_id,
        "definition": info.definition,
    }


__all__ = ["KeyInfo", "SOURCE_ORDER", "explain", "key_info_to_dict", "search", "term_to_dict", "Level"]
