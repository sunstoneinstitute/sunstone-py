"""Shipped vocabulary data: DP 2.0 property sets, config keys and RDF terms.

All data is read from the JSON files next to this module. Nothing here
touches the network; ``scripts/sync_vocab.py`` regenerates the RDF files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent

SHIPPED_VOCABS: tuple[str, ...] = ("dct", "dcat", "prov", "schema", "skos", "rdfs", "qudt", "sosa", "si", "dcat-si")
"""Vocabularies whose terms are checked for existence (spec: Extras MUST)."""

# YAML level -> DP profile level used for key lookup.
_DP_LEVEL_ALIAS = {"dataset": "resource"}


@dataclass(frozen=True)
class Term:
    curie: str
    iri: str
    label: str
    definition: str
    source: str
    """Vocabulary prefix, or ``"dp"`` / ``"config"`` for descriptor keys."""
    levels: tuple[str, ...] = ()
    """Levels where a DP/config key is allowed; empty for RDF terms (allowed anywhere)."""


@lru_cache(maxsize=None)
def _dp() -> dict[str, Any]:
    with open(_DIR / "dp.json", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


@lru_cache(maxsize=None)
def aliases() -> dict[str, list[dict[str, str]]]:
    with open(_DIR / "aliases.json", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


DP_PROFILE_URL: str = _dp()["profile"]


@lru_cache(maxsize=None)
def load_vocab(prefix: str) -> dict[str, Any]:
    if prefix not in SHIPPED_VOCABS:
        raise KeyError(prefix)
    with open(_DIR / f"{prefix}.json", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


@lru_cache(maxsize=None)
def _locals(prefix: str) -> frozenset[str]:
    ns = load_vocab(prefix)["namespace"]
    return frozenset(t["iri"][len(ns) :] for t in load_vocab(prefix)["terms"])


def namespace_of(prefix: str) -> str:
    return str(load_vocab(prefix)["namespace"])


def term_exists(prefix: str, local: str) -> bool:
    return prefix in SHIPPED_VOCABS and local in _locals(prefix)


def dp_keys(level: str) -> frozenset[str]:
    return frozenset(_dp()["dp"].get(_DP_LEVEL_ALIAS.get(level, level), {}))


def config_keys(level: str) -> frozenset[str]:
    return frozenset(_dp()["config"].get(level, {}))


def lock_keys(level: str) -> frozenset[str]:
    return frozenset(_dp()["lock"].get(level, []))


def legacy_emitted_keys(level: str) -> frozenset[str]:
    return frozenset(_dp()["legacy_emitted"].get(_DP_LEVEL_ALIAS.get(level, level), []))


def recommended_keys(level: str) -> dict[str, str]:
    """Spec "Recommended properties": key -> "SHOULD" or "MAY" at this level."""
    return dict(_dp()["recommended"].get(level, {}))


def duplicate_keys(level: str) -> dict[str, str]:
    """Spec "Duplicate properties" (MUST NOT): key -> what to use instead. ``output`` adds to ``dataset``."""
    return dict(_dp()["duplicates"].get(level, {}))


def key_definition(level: str, key: str) -> str:
    dp_level = _DP_LEVEL_ALIAS.get(level, level)
    return str(_dp()["dp"].get(dp_level, {}).get(key) or _dp()["config"].get(level, {}).get(key) or "")


def level_children(level: str) -> dict[str, str]:
    return dict(_dp()["children"].get(level, {}))


def level_for_path(path: str) -> str | None:
    """Resolve a dotted ``datasets.yaml`` path (no array markers) to a level name."""
    level = "document"
    for part in [p for p in path.strip().strip(".").split(".") if p]:
        child = level_children(level).get(part)
        if child is None:
            return None
        level = child
    return level


@lru_cache(maxsize=None)
def all_terms() -> list[Term]:
    terms: list[Term] = []
    dp = _dp()
    by_key: dict[tuple[str, str], list[str]] = {}
    for kind in ("dp", "config"):
        for level, keys in dp[kind].items():
            for key in keys:
                by_key.setdefault((kind, key), []).append(level)
    for (kind, key), levels in sorted(by_key.items()):
        definition = next((dp[kind][lvl][key] for lvl in levels if dp[kind][lvl].get(key)), "")
        terms.append(Term(curie=key, iri="", label=key, definition=definition, source=kind, levels=tuple(levels)))
    for prefix in SHIPPED_VOCABS:
        for t in load_vocab(prefix)["terms"]:
            terms.append(
                Term(
                    curie=t["curie"],
                    iri=t["iri"],
                    label=t.get("label", ""),
                    definition=t.get("definition", ""),
                    source=prefix,
                )
            )
    return terms
