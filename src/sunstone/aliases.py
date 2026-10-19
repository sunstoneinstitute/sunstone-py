"""Rename old datasets.yaml / lock keys to their DP 2.0 or RDF names, in place.

Plain key renames come from ``sunstone.vocab.aliases()``. This module only
hardcodes what that table cannot express: location hoisting, the DOI move to
``"@id"``, the acquisition hoist to the dataset, agent-object wrapping, old/new
name detection and the ``schema`` move.

Works on plain dicts and on ruamel ``CommentedMap`` objects (comments, key
order and anchors kept). Never deletes a value: when a target key already holds
a different value, the old key stays and a ``Conflict`` is recorded. YAML
aliases load as the same object, so a shared node can be visited from several
parents; ``_Ctx`` defers deleting moved-out keys until every visit is done and
keeps a key that any visit could not move.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import vocab


def make_yaml() -> YAML:
    """Round-trip YAML with the same settings as ``datasets.py``."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


@dataclass(frozen=True)
class Rename:
    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Conflict:
    """``old`` was left in place because ``new`` already holds a different value."""

    path: str
    old: str
    new: str


@dataclass
class NormalizeResult:
    renames: list[Rename] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    new_form: bool = False
    """True when the input already used a new-form key (before renaming)."""
    conflicts: list[Conflict] = field(default_factory=list)
    field_sources: dict[int, Any] = field(default_factory=dict)
    """Old-form field ``source`` objects as authored, keyed by ``id()`` of their field mapping."""


MIN_NEW_FORM_VERSION = "1.20.0"
"""First sunstone-py version that reads the new key form (spec: Extras MUST)."""

Form = Literal["old", "new", "ambiguous", "untitled"]

_NEW_FORM_DATASET_KEYS = frozenset({"path", "schema", "licenses", "prov:generatedAtTime", "prov:wasGeneratedBy"})
_NEW_FORM_SOURCE_KEYS = frozenset(
    {
        "prov:wasAttributedTo",
        "dct:license",
        "dct:modified",
        "dcat:downloadURL",
        "dcat:landingPage",
        "dcat:accessURL",
        "rdfs:seeAlso",
        "@id",
        "dct:issued",
        "dct:isPartOf",
        "dct:bibliographicCitation",
    }
)
_NEW_FORM_FIELD_KEYS = frozenset({"si:unit", "dct:source", "qudt:hasUnit"})
_FIELD_SOURCE_KEYS = ("source", "si:sourceField")
"""Field keys renamed to ``dct:source``. ``si:sourceField`` stays the lock-file field derivation key."""

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/")
_DOI_LOCATION_KEYS = ("data", "web", "about")

# Keys with transforms the alias table cannot express; skipped by the plain-rename pass.
_SPECIAL: dict[str, frozenset[str]] = {
    "dataset": frozenset({"name", "slug", "license"}),
    "package": frozenset({"license"}),
    "source": frozenset({"attributedTo"}),
    "field": frozenset({"unit", *_FIELD_SOURCE_KEYS}),
}


def _table(level: str) -> list[tuple[str, str]]:
    return [(a["old"], a["new"]) for a in vocab.aliases().get(level, [])]


def _plain(level: str) -> list[tuple[str, str]]:
    """Single-key renames at ``level`` (no dotted path, no hoist, no special transform)."""
    skip = _SPECIAL.get(level, frozenset())
    return [(o, n) for o, n in _table(level) if "." not in o and "." not in n and o not in skip]


def _location_map() -> dict[str, str]:
    return {o.split(".", 1)[1]: n for o, n in _table("source") if o.startswith("location.")}


def _hoist_target(old: str) -> str:
    """Dataset-level target of a source key hoisted to its dataset, e.g. ``acquiredAt``."""
    new = dict(_table("source"))[old]
    return new.removeprefix("<dataset>.")


def is_doi_url(value: str) -> bool:
    """True for a resolvable DOI URL (spec: a DOI goes in ``"@id"``, never in a DCAT link)."""
    return value.startswith(_DOI_PREFIXES)


def uses_new_form(data: Mapping[str, Any]) -> bool:
    """True when any new-form key is present. Call before normalizing."""
    if "dcat-si:methodology" in data:
        return True
    for section in ("inputs", "outputs"):
        for entry in data.get(section) or []:
            if not isinstance(entry, Mapping):
                continue
            if _NEW_FORM_DATASET_KEYS & set(entry) or ("title" in entry and "slug" not in entry):
                return True
            src = entry.get("source")
            if isinstance(src, Mapping) and _NEW_FORM_SOURCE_KEYS & set(src):
                return True
            schema = entry.get("schema")
            fields = schema.get("fields") if isinstance(schema, Mapping) else entry.get("fields")
            for fld in fields or []:
                if isinstance(fld, Mapping) and _NEW_FORM_FIELD_KEYS & set(fld):
                    return True
    for pkg in [data.get("package"), *(data.get("packages") or [])]:
        if isinstance(pkg, Mapping) and "licenses" in pkg:
            return True
    return False


def lock_uses_new_form(lock: Mapping[str, Any]) -> bool:
    """True when a lock source entry carries a new-form key (``prov:wasAttributedTo``, ``dct:license``)."""
    new_keys = {n for _, n in _plain("lock_source")}
    for section in ("inputs", "outputs"):
        for entry in lock.get(section) or []:
            if isinstance(entry, Mapping):
                for src in entry.get("sources") or []:
                    if isinstance(src, Mapping) and new_keys & set(src):
                        return True
    return False


def version_key(v: str) -> tuple[int, ...]:
    """``"1.20.0rc1"`` -> ``(1, 19, 0)``: the leading digits of each dot-separated part."""
    return tuple(int(m.group()) if (m := re.match(r"\d+", p)) else 0 for p in str(v).split("."))


def ensure_min_version(data: MutableMapping[str, Any], required: str = MIN_NEW_FORM_VERSION) -> bool:
    """Insert or raise ``min_sunstone_version``; never lowers it. Returns True when the document changed."""
    current = data.get("min_sunstone_version")
    if current is not None and version_key(str(current)) >= version_key(required):
        return False
    if "min_sunstone_version" in data:
        data["min_sunstone_version"] = required
    else:
        _insert(data, 0, "min_sunstone_version", required)
    return True


def detect_form(entry: Mapping[str, Any]) -> Form:
    has_slug, has_title = "slug" in entry, "title" in entry
    if has_slug and has_title:
        return "ambiguous"
    if has_slug:
        return "old"
    if has_title:
        return "new"
    return "untitled"


def _insert(m: MutableMapping[str, Any], idx: int, key: str, value: Any) -> None:
    """Insert ``key`` at position ``idx``, keeping the mapping object's identity."""
    if isinstance(m, CommentedMap):
        m.insert(idx, key, value)
        return
    items = list(m.items())
    m.clear()
    for i, (k, v) in enumerate(items):
        if i == idx:
            m[key] = value
        m[k] = v
    if key not in m:
        m[key] = value


def _index(m: Mapping[str, Any], key: str) -> int:
    return list(m.keys()).index(key)


def _delete(m: MutableMapping[str, Any], key: str) -> Any:
    """Delete ``key`` and return its ruamel comment entry (or None)."""
    ca = getattr(m, "ca", None)
    comment = ca.items.pop(key, None) if ca is not None else None
    del m[key]
    return comment


def _attach(m: MutableMapping[str, Any], key: str, comment: Any, shift: int = 0) -> None:
    """Attach a comment entry to ``key``; ``shift`` moves an end-of-line comment to keep its gap."""
    ca = getattr(m, "ca", None)
    if ca is None or comment is None:
        return
    eol = comment[2] if len(comment) > 2 else None
    if shift and eol is not None and getattr(eol, "start_mark", None) is not None:
        eol.column = max(0, eol.column + shift)
    ca.items[key] = comment


_KEEP: Any = object()


def _same(a: Any, b: Any) -> bool:
    return bool(a == b or _iso(a) == _iso(b))


def _rename(
    m: MutableMapping[str, Any], old: str, new: str, path: str, result: NormalizeResult, value: Any = _KEEP
) -> bool:
    """Move ``old`` (optionally as ``value``) to ``new``. Returns True when the value landed.

    An equal value already at ``new`` collapses silently. A different one leaves
    ``old`` untouched and records a Conflict.
    """
    if old not in m:
        return False
    if value is _KEEP:
        value = m[old]
    if new in m:
        if not _same(m[new], value):
            result.conflicts.append(Conflict(path, old, new))
            return False
        _delete(m, old)
    else:
        idx = _index(m, old)
        shift = len(new) - len(old)
        old_value = m[old]
        if isinstance(value, (list, Mapping)) and not isinstance(old_value, (list, Mapping)):
            # A scalar became a block: its end-of-line comment now follows the key, not the value.
            shift -= len(str(old_value)) + 1
        comment = _delete(m, old)
        _insert(m, idx, new, value)
        _attach(m, new, comment, shift)
    result.renames.append(Rename(path, old, new))
    return True


def rename_key(m: MutableMapping[str, Any], old: str, new: str, path: str, result: NormalizeResult) -> None:
    """Rename ``old`` to ``new`` keeping position and comment. Never deletes a value (see ``_rename``)."""
    _rename(m, old, new, path, result)


def _land(m: MutableMapping[str, Any], idx: int, key: str, value: Any) -> bool:
    """Insert ``key`` at ``idx`` unless present. False when it holds a different value."""
    if key in m:
        return _same(m[key], value)
    _insert(m, idx, key, value)
    return True


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _license_list(value: Any) -> Any:
    if isinstance(value, list) or value is None:
        return value
    entry = CommentedMap()
    entry["name"] = value
    seq = CommentedSeq()
    seq.append(entry)
    return seq


@dataclass
class _Ctx:
    """Per-document state. Keys moved out of a node are deleted only in ``finish``.

    YAML aliases load as the same object, so a node can be visited from several
    parents. A key is deleted only when no visit had to keep it.
    """

    result: NormalizeResult
    seen: set[int] = field(default_factory=set)
    drops: dict[tuple[int, str], MutableMapping[str, Any]] = field(default_factory=dict)
    keeps: set[tuple[int, str]] = field(default_factory=set)
    locations: list[MutableMapping[str, Any]] = field(default_factory=list)

    def first_visit(self, node: Any) -> bool:
        if id(node) in self.seen:
            return False
        self.seen.add(id(node))
        return True

    def drop(self, m: MutableMapping[str, Any], key: str) -> None:
        self.drops[(id(m), key)] = m

    def keep(self, m: MutableMapping[str, Any], key: str) -> None:
        self.keeps.add((id(m), key))

    def finish(self) -> None:
        for (mid, key), m in self.drops.items():
            if (mid, key) not in self.keeps and key in m:
                _delete(m, key)
        for src in self.locations:
            loc = src.get("location")
            if isinstance(loc, Mapping) and not loc:
                _delete(src, "location")


def _wrap_agents(src: MutableMapping[str, Any], path: str, result: NormalizeResult) -> None:
    """SC16: a string publisher / creator becomes ``{rdfs:label: <string>}``; nothing is split."""
    if isinstance(src.get("dct:publisher"), str):
        node = CommentedMap()
        node["rdfs:label"] = src["dct:publisher"]
        src["dct:publisher"] = node  # same key, same position
        result.renames.append(Rename(path, "dct:publisher", "dct:publisher.rdfs:label"))
    creator = src.get("dct:creator")
    if isinstance(creator, str):
        node = CommentedMap()
        node["rdfs:label"] = creator
        seq = CommentedSeq()
        seq.append(node)
        src["dct:creator"] = seq
        result.renames.append(Rename(path, "dct:creator", "dct:creator[].rdfs:label"))
    elif isinstance(creator, list) and any(isinstance(c, str) for c in creator):
        for i, c in enumerate(creator):  # in place, so an anchored list stays shared
            if isinstance(c, str):
                node = CommentedMap()
                node["rdfs:label"] = c
                creator[i] = node
        result.renames.append(Rename(path, "dct:creator", "dct:creator[].rdfs:label"))


def _normalize_attributed_to(src: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    raw = src["attributedTo"]
    if not isinstance(raw, MutableMapping):
        rename_key(src, "attributedTo", "prov:wasAttributedTo", path, ctx.result)
        return
    if ctx.first_visit(raw):  # rewrite in place so an anchored agent stays shared
        for old, new in (("id", "@id"), ("type", "@type"), ("label", "rdfs:label")):
            _rename(raw, old, new, f"{path}.attributedTo", ctx.result)
        if "rdfs:label" in raw and raw["rdfs:label"] in ("", None):
            _delete(raw, "rdfs:label")
    version = raw.get("version")
    idx = _index(src, "attributedTo")
    landed = _rename(src, "attributedTo", "prov:wasAttributedTo", path, ctx.result)
    if version is None:
        return
    if landed and _land(src, idx + 1, "version", version):
        ctx.result.renames.append(Rename(path, "attributedTo.version", "version"))
        ctx.drop(raw, "version")
        return
    ctx.keep(raw, "version")
    if landed:
        ctx.result.conflicts.append(Conflict(path, "attributedTo.version", "version"))


def _hoist_location(src: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    """Move location keys to DCAT / rdfs keys on the source, in the file's key order (ruling M2)."""
    loc = src["location"]
    loc_path = f"{path}.location"
    targets = _location_map()
    ctx.locations.append(src)
    for old in list(loc.keys()):
        value = loc[old]
        if old in _DOI_LOCATION_KEYS and isinstance(value, str) and is_doi_url(value):
            new, idx = "@id", 0  # spec C7: a DOI is an identifier, not a link
        elif old in targets:
            new, idx = targets[old], _index(src, "location")
        else:
            continue
        if _land(src, idx, new, value):
            ctx.result.renames.append(Rename(loc_path, old, new))
            ctx.drop(loc, old)
        else:
            ctx.result.conflicts.append(Conflict(loc_path, old, new))
            ctx.keep(loc, old)


def _normalize_source(src: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    """Normalize a source block. ``acquiredAt`` / ``acquisitionMethod`` are hoisted by the dataset."""
    if not ctx.first_visit(src):
        return
    result = ctx.result
    for old, new in _plain("source"):
        rename_key(src, old, new, path, result)
    if "dct:modified" in src:
        src["dct:modified"] = _iso(src["dct:modified"])
    if "attributedTo" in src:
        _normalize_attributed_to(src, path, ctx)
    _wrap_agents(src, path, result)
    if isinstance(src.get("location"), MutableMapping):
        _hoist_location(src, path, ctx)


def _hoist_acquisition(entry: MutableMapping[str, Any], src: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    """Move source ``acquiredAt`` / ``acquisitionMethod`` to this dataset (checked per dataset)."""
    idx = _index(entry, "source") + 1
    for old in ("acquiredAt", "acquisitionMethod"):
        if src.get(old) is None:
            continue
        target = _hoist_target(old)
        key = target.split(".", 1)[0]
        if old == "acquiredAt":
            value: Any = _iso(src[old])
            ok = _land(entry, idx, key, value)
        elif key in entry:
            existing = entry[key]
            ok = isinstance(existing, Mapping) and _same(existing.get("dct:type"), src[old])
        else:
            node = CommentedMap()
            node["@type"] = "prov:Activity"
            node["dct:type"] = src[old]
            _insert(entry, idx, key, node)
            ok = True
        if ok:
            ctx.result.renames.append(Rename(path, old, target))
            ctx.drop(src, old)
            if key in entry:
                idx = _index(entry, key) + 1
        else:
            ctx.result.conflicts.append(Conflict(path, old, target))
            ctx.keep(src, old)


def _normalize_field_source(fld: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    """Rename ``source`` / ``si:sourceField`` to ``dct:source``; an object is normalized like a dataset source.

    Acquisition keys in a field source stay where they are (no dataset to hoist them to).
    """
    for key in ("dct:source", *_FIELD_SOURCE_KEYS):
        value = fld.get(key)
        if isinstance(value, MutableMapping):
            src_path = f"{path}.{key}"
            for old, new in _plain("field_source"):
                rename_key(value, old, new, src_path, ctx.result)
            _normalize_source(value, src_path, ctx)
    for old in _FIELD_SOURCE_KEYS:
        rename_key(fld, old, "dct:source", path, ctx.result)


def _normalize_field(fld: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    result = ctx.result
    if "unit" in fld:
        from .units import is_qudt_uri, parse_unit_string

        raw = fld["unit"]
        value = raw
        qudt = isinstance(raw, str) and is_qudt_uri(raw)
        if qudt:
            try:
                value = str(parse_unit_string(raw)[0])
            except Exception:
                value = raw
        if qudt and "qudt:hasUnit" in fld and not _same(fld["qudt:hasUnit"], raw):
            result.conflicts.append(Conflict(path, "unit", "qudt:hasUnit"))
        elif _rename(fld, "unit", "si:unit", path, result, value) and qudt and "qudt:hasUnit" not in fld:
            _insert(fld, _index(fld, "si:unit") + 1, "qudt:hasUnit", raw)
    _normalize_field_source(fld, path, ctx)
    for old, new in _plain("field"):
        rename_key(fld, old, new, path, result)


def _move_into_schema(entry: MutableMapping[str, Any], path: str, result: NormalizeResult) -> None:
    for old, new in _table("dataset"):
        if not new.startswith("schema.") or old not in entry:
            continue
        sub = new.split(".", 1)[1]
        value = entry[old]
        schema = entry.get("schema")
        if "schema" in entry and not isinstance(schema, MutableMapping):
            result.conflicts.append(Conflict(path, old, new))  # e.g. a schema path; never overwrite it
            continue
        if not isinstance(schema, MutableMapping):
            schema = CommentedMap()
            _insert(entry, _index(entry, old), "schema", schema)
        if sub in schema and not _same(schema[sub], value):
            result.conflicts.append(Conflict(path, old, new))
            continue
        if sub not in schema:
            schema[sub] = value
        _delete(entry, old)
        result.renames.append(Rename(path, old, new))


def _normalize_dataset(entry: MutableMapping[str, Any], path: str, ctx: _Ctx) -> None:
    result = ctx.result
    form = detect_form(entry)
    if form == "ambiguous":
        result.ambiguous.append(path)
    elif form == "old":
        # Table order matters: name -> title before slug -> name.
        for old, new in _table("dataset"):
            if old in ("name", "slug"):
                rename_key(entry, old, new, path, result)
    for old, new in _plain("dataset"):
        rename_key(entry, old, new, path, result)
    if "license" in entry:
        _rename(entry, "license", "licenses", path, result, _license_list(entry["license"]))
    _move_into_schema(entry, path, result)

    src = entry.get("source")
    if isinstance(src, MutableMapping):
        src_path = f"{path}.source"
        _normalize_source(src, src_path, ctx)
        _hoist_acquisition(entry, src, src_path, ctx)
    if "prov:generatedAtTime" in entry:
        entry["prov:generatedAtTime"] = _iso(entry["prov:generatedAtTime"])

    schema = entry.get("schema")
    if isinstance(schema, Mapping):
        fields = schema.get("fields")
        if isinstance(fields, list):
            for i, fld in enumerate(fields):
                if isinstance(fld, MutableMapping):
                    _normalize_field(fld, f"{path}.schema.fields[{i}]", ctx)


def _normalize_package(pkg: MutableMapping[str, Any], path: str, result: NormalizeResult) -> None:
    for old, new in _plain("package"):
        rename_key(pkg, old, new, path, result)
    if "license" in pkg:
        _rename(pkg, "license", "licenses", path, result, _license_list(pkg["license"]))


def _plain_copy(value: Any) -> Any:
    """Deep copy as plain dicts and lists, so a ruamel node can be emitted as JSON unchanged."""
    if isinstance(value, Mapping):
        return {k: _plain_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_copy(v) for v in value]
    return copy.copy(value)


def _field_source_originals(data: Mapping[str, Any]) -> dict[int, Any]:
    """Old-form field ``source`` objects before any renaming (an anchor may be shared with a dataset source)."""
    out: dict[int, Any] = {}
    for section in ("inputs", "outputs"):
        for entry in data.get(section) or []:
            if not isinstance(entry, Mapping):
                continue
            schema = entry.get("schema")
            fields = schema.get("fields") if isinstance(schema, Mapping) else entry.get("fields")
            for fld in fields if isinstance(fields, list) else []:
                if isinstance(fld, Mapping) and isinstance(fld.get("source"), Mapping):
                    out[id(fld)] = _plain_copy(fld["source"])
    return out


def legacy_field_source(value: Any) -> Any:
    """Old-form shape of a normalized field ``dct:source`` (datapackage.json ``source`` in 1.x).

    Used when the authored old-form object is not available (new-form input).
    Keys without an old form are kept as they are.
    """
    if not isinstance(value, Mapping):
        return value
    renames = {new: old for old, new in [*_plain("source"), *_plain("field_source")]}
    renames["prov:wasAttributedTo"] = "attributedTo"
    location: dict[str, str] = {}
    for old, new in _location_map().items():
        if ":" not in old:
            location.setdefault(new, old)  # first wins: dcat:landingPage -> web
    out: dict[str, Any] = {}
    loc: dict[str, Any] = {}
    for key, v in value.items():
        if key in location:
            out.setdefault("location", loc)
            loc[location[key]] = v
        elif key == "dct:publisher" and isinstance(v, Mapping) and v.get("rdfs:label"):
            out["publisher"] = v["rdfs:label"]
        else:
            out[str(renames.get(key, key))] = _plain_copy(v)
    doi = out.get("@id")
    if isinstance(doi, str) and is_doi_url(doi) and "web" not in loc:
        del out["@id"]  # migration moved it from location.web or location.data
        out.setdefault("location", loc)
        loc["web"] = doi
    return out


def normalize_document(data: MutableMapping[str, Any]) -> NormalizeResult:
    """Normalize a datasets.yaml document or include file in place. Never deletes a value."""
    ctx = _Ctx(NormalizeResult(new_form=uses_new_form(data), field_sources=_field_source_originals(data)))
    for old, new in _plain("document"):
        rename_key(data, old, new, "", ctx.result)
    for section in ("inputs", "outputs"):
        items = data.get(section)
        if isinstance(items, list):
            for i, entry in enumerate(items):
                if isinstance(entry, MutableMapping):
                    _normalize_dataset(entry, f"{section}[{i}]", ctx)
    pkg = data.get("package")
    if isinstance(pkg, MutableMapping):
        _normalize_package(pkg, "package", ctx.result)
    pkgs = data.get("packages")
    if isinstance(pkgs, list):
        for i, p in enumerate(pkgs):
            if isinstance(p, MutableMapping):
                _normalize_package(p, f"packages[{i}]", ctx.result)
    ctx.finish()
    return ctx.result


def normalize_lock(lock: MutableMapping[str, Any]) -> NormalizeResult:
    """Normalize the source entries of a datasets lock file in place."""
    result = NormalizeResult()
    renames = _plain("lock_source")
    for section in ("inputs", "outputs"):
        for i, entry in enumerate(lock.get(section) or []):
            if not isinstance(entry, MutableMapping):
                continue
            for j, src in enumerate(entry.get("sources") or []):
                if isinstance(src, MutableMapping):
                    p = f"{section}[{i}].sources[{j}]"
                    for old, new in renames:
                        rename_key(src, old, new, p, result)
    return result
